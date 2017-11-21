import datetime as dt
import email
import email.policy
import functools as ft
import hashlib
import imaplib
import json
import os
import re
import uuid
from email.message import MIMEPart
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, getaddresses, formatdate

from gevent import socket

from . import log, imap

USER = os.environ.get('MLR_USER', 'user')

SRC = 'Src'
ALL = 'All'
TAGS = 'Tags'


class Local(imaplib.IMAP4, imap.Conn):
    def __init__(self, user):
        self.username = user
        self.current_box = None
        super().__init__('localhost')

    def _create_socket(self):
        return socket.create_connection((self.host, self.port))

    def login(self):
        return super().login('%s*root' % self.username, 'root')


def connect(user=None):
    con = Local(user or USER)
    imap.check(con.login())

    # For searching with non ascii symbols (Dovecot understands this)
    con._encoding = 'utf-8'
    return con


def client(box=ALL):
    ctx = imap.client(connect, dovecot=True, writable=True)
    if box:
        ctx.select(box)
    return ctx


def binary_msg(txt, mimetype='text/plain'):
    msg = MIMEPart()
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def gen_msgid(label):
    return '<%s@mailur.%s>' % (uuid.uuid4().hex, label)


@ft.lru_cache(maxsize=None)
def get_tags(reverse=False):
    con = client()
    count = con.select(TAGS)
    if count == [b'0']:
        return {}
    res = con.fetch('1:*', 'BODY.PEEK[1]')
    tags = (
        ('#t%s' % res[i][0].split()[2].decode(), res[i][1].decode())
        for i in range(0, len(res), 2)
    )
    return {v: k for k, v in tags} if reverse else dict(tags)


def get_tag(name):
    tag = get_tags(reverse=True).get(name)
    if tag is not None:
        return tag
    msg = binary_msg(name)
    msg.add_header('Subject', name)
    with client(TAGS) as con:
        res = con.append(TAGS, '', None, msg.as_bytes())
    get_tags.cache_clear()
    tag = re.search(r'\[APPENDUID \d+ (\d+)\]', res[0].decode()).group(1)
    tag = '#t' + tag
    log.info('## added new tag %s: %r', tag, name)
    return tag


def save_uid_pairs(con, uids=None):
    if uids:
        pairs = uid_pairs(con)
    else:
        uids = '1:*'
        pairs = {}
    res = con.fetch(uids, '(UID BODY[1])')
    pairs = dict(pairs, **{
        json.loads(res[i][1].decode())['origin_uid']:
        re.search(r'UID (\d+)', res[i][0].decode()).group(1)
        for i in range(0, len(res), 2)
    })
    con.setmetadata(ALL, 'uidpairs', json.dumps(pairs))


@imap.fn_time
def uid_pairs(con):
    res = con.getmetadata(ALL, 'uidpairs')
    if len(res) == 1:
        return {}

    return json.loads(res[0][1].decode())


@imap.fn_time
def pair_origin_uids(con, uids):
    pairs = uid_pairs(con)
    return tuple(pairs[i] for i in uids if i in pairs)


@imap.fn_time
def pair_parsed_uids(con, uids):
    # pairs = uid_pairs(con).items()
    # return tuple(origin for origin, parsed in pairs if parsed in uids)
    res = con.fetch(uids, 'BODY[1]')
    return tuple(sorted(
        json.loads(res[i][1].decode())['origin_uid']
        for i in range(0, len(res), 2)
        if res[i][1]
    ))


def address_name(a):
    if a[0]:
        return a[0]
    try:
        index = a[1].index('@')
    except ValueError:
        return a[1]
    return a[1][:index]


def addresses(txt):
    addrs = [
        {
            'addr': a[1],
            'name': address_name(a),
            'title': '{} <{}>'.format(*a) if a[0] else a[1],
            'hash': hashlib.md5(a[1].strip().lower().encode()).hexdigest(),
        } for a in getaddresses([txt])
    ]
    return addrs


def clean_html(htm):
    from lxml import html as lhtml
    from lxml.html.clean import Cleaner

    htm = re.sub(r'^\s*<\?xml.*?\?>', '', htm).strip()
    if not htm:
        return ''

    cleaner = Cleaner(
        links=False,
        safe_attrs_only=False,
        kill_tags=['head', 'style'],
        remove_tags=['html', 'base']
    )
    htm = lhtml.fromstring(htm)
    htm = cleaner.clean_html(htm)

    # return lhtml.tostring(htm, encoding='utf-8').decode()
    return '\n'.join(i.rstrip() for i in htm.xpath('//text()') if i.rstrip())


def create_msg(raw, uid, time):
    if isinstance(raw, bytes):
        # TODO: there is a bug with folding mechanism,
        # like this one https://bugs.python.org/issue30788,
        # so use `max_line_length=None` by now, not sure if it's needed at all
        policy = email.policy.SMTPUTF8.clone(max_line_length=None)
        orig = BytesParser(policy=policy).parsebytes(raw)
    else:
        orig = raw

    meta = {
        k.replace('-', '_'): orig[k]
        for k in ('message-id', 'in-reply-to')
    }
    meta['origin_uid'] = uid

    fields = (('from', 1), ('sender', 1), ('to', 0), ('cc', 0), ('bcc', 0))
    for n, one in fields:
        v = orig[n]
        if not v:
            continue
        v = addresses(v)
        meta[n] = v[0] if one else v

    subj = orig['subject']
    meta['subject'] = str(subj) if subj else subj

    # refs = orig['references']
    # meta['refs'] = refs.split() if refs else []

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    meta['arrived'] = int(arrived.timestamp())

    date = orig['date']
    meta['date'] = date and int(parsedate_to_datetime(date).timestamp())

    txt = orig.get_body(preferencelist=('plain', 'html'))
    body = txt.get_content()
    body = clean_html(body)
    meta['preview'] = re.sub('[\s ]+', ' ', body[:200])

    msg = MIMEPart(policy)
    headers = (
        'message-id', 'date',
        'from', 'sender', 'to', 'cc', 'bcc',
    )
    for n, v in orig.items():
        if n.lower() not in headers or n.lower() in msg:
            continue
        msg.add_header(n, v)

    if msg['from'] == 'mailur@link':
        msg.add_header('References', orig['references'])

    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('X-Subject', meta['subject'])
    msg.make_mixed()

    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary_msg(meta_txt, 'application/json'))
    msg.attach(binary_msg(body))
    return msg


def parse_uids(uids):
    con = client(SRC)
    res = con.fetch(uids.str, '(UID INTERNALDATE FLAGS BODY.PEEK[])')

    def msgs():
        for i in range(0, len(res), 2):
            m = res[i]
            uid, time, flags = re.search(
                r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)',
                m[0].decode()
            ).groups()
            flags = flags.replace('\\Recent', '').strip()
            try:
                msg_obj = create_msg(m[1], uid, time)
                msg = msg_obj.as_bytes()
            except Exception as e:
                msgid = re.findall(b'^(?im)message-id:.*', m[1])
                log.exception('## %r uid=%s %s', e, uid, msgid)
                continue
            yield time, flags, msg

    try:
        return con.multiappend(ALL, msgs())
    finally:
        con.logout()


def parse(criteria=None, *, batch=1000, threads=10):
    con = client(SRC)
    uidnext = 1
    if criteria is None:
        res = con.getmetadata(ALL, 'uidnext')
        if len(res) > 1:
            uidnext = int(res[0][1].decode())
            log.info('## saved: uidnext=%s', uidnext)
        criteria = 'UID %s:*' % uidnext

    res = con.search(criteria)
    uids = [i for i in res[0].decode().split(' ') if i and int(i) >= uidnext]
    if not uids:
        log.info('## all parsed already')
        return

    res = con.status(SRC, '(UIDNEXT)')
    uidnext = re.search(r'UIDNEXT (?P<next>\d+)', res[0].decode()).group(1)
    log.info('## new: uidnext: %s', uidnext)

    log.info('## criteria: %r; %s uids', criteria, len(uids))
    count = con.select(ALL)[0].decode()
    if count != '0':
        if criteria.lower() == 'all':
            puids = '1:*'
        else:
            puids = pair_origin_uids(con, uids)
        if puids:
            con.select(ALL, readonly=False)
            puids = imap.Uids(puids)
            log.info('## deleting %s from %r', puids, ALL)
            con.store(puids, '+FLAGS.SILENT', '\Deleted')
            con.expunge()

    con.logout()
    uids = imap.Uids(uids, size=batch, threads=threads)
    puids = ','.join(uids.call_async(parse_uids, uids))
    if criteria.lower() == 'all' or count == '0':
        puids = '1:*'

    con = client(ALL)
    con.setmetadata(ALL, 'uidnext', str(uidnext))
    save_uid_pairs(con, puids)
    update_threads(con, 'UID %s' % uids.str)
    con.logout()


def update_threads(con, criteria=None):
    con.select(SRC)
    criteria = criteria or 'ALL'
    src_thrs = con.thread('REFS UTF-8 INTHREAD REFS %s' % criteria)
    if not src_thrs:
        log.info('## all threads are updated already')
        return

    src_refs = {}
    res = con.fetch(
        src_thrs.all_uids, 'BODY.PEEK[HEADER.FIELDS (MESSAGE-ID REFERENCES)]'
    )
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        msg = email.message_from_bytes(res[i][1])
        refs = msg['references'].split() if msg['references'] else []
        src_refs[uid] = [msg['message-id']] + refs

    con.select(ALL)
    uids = pair_origin_uids(con, src_thrs.all_uids)
    res = con.search('INTHREAD REFS UID %s KEYWORD #link' % ','.join(uids))
    old_links = list(set(res[0].decode().split()) - set(uids))
    if old_links:
        con.select(ALL, readonly=False)
        con.store(old_links, '+FLAGS', '\\Deleted')
        con.expunge()
        con.select(ALL)

    links = []
    for thr in src_thrs:
        if len(thr) == 1:
            continue
        refs = []
        for i in thr:
            r = src_refs.get(i)
            if not r:
                continue
            new = set(r) - set(refs)
            if not new:
                continue
            refs.extend(new)
        link = create_link(refs)
        links.append((None, '#link', link.as_bytes()))

    new = con.multiappend(ALL, links, batch=1000)
    if new:
        res = con.search('UID %s' % new)
        links = res[0].decode().split()

    msgs = {}
    thrs = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % ','.join(uids))
    res = con.fetch(thrs.all_uids, '(FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid, flags = re.search(
            r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode()
        ).groups()
        if not res[i][1]:
            continue
        msgs[uid] = {
            'flags': flags.split(),
            'date': json.loads(res[i][1])['date'],
        }

    all_latest = []
    for thrids in thrs:
        if len(thrids) == 1:
            latest = thrids[0]
        else:
            thrids = set(thrids).intersection(uids)
            latest = sorted(
                (t for t in thrids if '#link' not in msgs[t]['flags']),
                key=lambda i: msgs[i]['date']
            )[-1]
        all_latest.append(latest)

    con.select(ALL, readonly=False)
    res = con.search('INTHREAD REFS UID %s KEYWORD #latest' % ','.join(uids))
    clean = set(res[0].decode().split()) - set(all_latest)
    if clean:
        con.store(clean, '-FLAGS.SILENT', '#latest')
    con.store(all_latest, '+FLAGS.SILENT', '#latest')
    log.info('## updated %s threads', len(all_latest))


def link_threads(uids, box=ALL):
    con = client()
    res = con.search('INTHREAD REFS UID %s' % ','.join(uids))
    uids = res[0].decode().split()
    res = con.search('KEYWORD #link UID %s' % ','.join(uids))
    refs = res[0].decode().split()
    if refs:
        uids = set(uids) - set(refs)
        c = client(None)
        src_refs = pair_parsed_uids(con, refs)
        if src_refs:
            c.select(SRC, readonly=False)
            c.store(src_refs, '+FLAGS.SILENT', '\\Deleted')
            c.expunge()
        c.select(box, readonly=False)
        c.store(refs, '+FLAGS.SILENT', '\\Deleted')
        c.expunge()
        c.logout()

    res = con.fetch(uids, 'BODY.PEEK[1]')
    msgids = [
        json.loads(res[i][1].decode())['message_id']
        for i in range(0, len(res), 2)
    ]

    msg = create_link(msgids)
    res = con.append(SRC, '#link', None, msg.as_bytes())
    con.logout()
    parse()
    return res[0].decode()


def create_link(msgids):
    msgid = gen_msgid('link')
    msg = MIMEPart(email.policy.SMTPUTF8)
    msg.add_header('Subject', 'Dummy: linking threads')
    msg.add_header('References', ' '.join(msgids))
    msg.add_header('Message-Id', msgid)
    msg.add_header('From', 'mailur@link')
    msg.add_header('Date', formatdate())
    return msg
