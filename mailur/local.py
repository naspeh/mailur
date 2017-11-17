import datetime as dt
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
TRASH = 'Trash'
SPAM = 'Spam'
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
    return '#t' + tag


def get_xuid(line):
    return line.replace('X-UID:', '').strip().strip('<>')


def parsed_uids(con, origin_uids):
    q = ['OR HEADER X-UID <%s> ' % i for i in origin_uids]
    q = ''.join(q[:-1]) + q[-1][3:]
    uids = con.search(q)[0].decode().split()
    if not uids:
        return {}

    res = con.fetch(uids, 'BODY.PEEK[HEADER.FIELDS (X-UID)]')
    return {
        res[i][0].split()[2].decode(): get_xuid(res[i][1].decode())
        for i in range(0, len(res), 2)
    }


def origin_uids(con, parsed_uids):
    res = con.fetch(parsed_uids, 'BODY.PEEK[HEADER.FIELDS (X-UID)]')
    return {
        get_xuid(res[i][1].decode()): res[i][0].split()[2].decode()
        for i in range(0, len(res), 2)
    }


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
    # TODO: there is a bug with folding mechanism,
    # like this one https://bugs.python.org/issue30788,
    # so use `max_line_length=None` by now, not sure if it's needed at all
    policy = email.policy.SMTPUTF8.clone(max_line_length=None)
    orig = BytesParser(policy=policy).parsebytes(raw)
    meta = {
        k.replace('-', '_'): orig[k]
        for k in ('message-id', 'in-reply-to')
    }

    fields = (('from', 1), ('sender', 1), ('to', 0), ('cc', 0), ('bcc', 0))
    for n, one in fields:
        v = orig[n]
        if not v:
            continue
        v = addresses(v)
        meta[n] = v[0] if one else v

    subj = orig['subject']
    meta['subject'] = str(subj) if subj else subj
    meta['origin_uid'] = uid

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
        'message-id', 'in-reply-to', 'references',
        'from', 'sender', 'to', 'cc', 'bcc',
        'date'
    )
    for n, v in orig.items():
        if n.lower() not in headers or n.lower() in msg:
            continue
        msg.add_header(n, v)

    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('X-Subject', meta['subject'])
    msg.make_mixed()

    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary_msg(meta_txt, 'application/json'))
    msg.attach(binary_msg(body))
    return msg


def parse_uids(uids, con):
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

    res = con.multiappend(ALL, msgs())
    log.debug('## %s', res[0].decode())


def parse(criteria=None, *, batch=1000, threads=10):
    con = client(SRC)
    uidnext = 1
    if criteria is None:
        res = con.getmetadata(ALL, 'uidnext')
        if len(res) > 1:
            uidnext = int(res[0][1].decode())
            log.info('## saved: uidnext=%s', uidnext)
        criteria = 'UID %s:*' % uidnext

    res = con.sort('(DATE)', criteria)
    uids = [i for i in res[0].decode().split(' ') if i and int(i) >= uidnext]
    if not uids:
        log.info('## all parsed already')
        return

    res = con.status(SRC, '(UIDNEXT)')
    uidnext = re.search(r'UIDNEXT (?P<next>\d+)', res[0].decode()).group(1)
    log.info('## new: uidnext: %s', uidnext)

    log.info('## criteria: %r; %s uids', criteria, len(uids))
    count = con.select(ALL)
    if count[0] != b'0':
        count = None
        if criteria.lower() == 'all':
            puids = '1:*'
        else:
            puids = list(parsed_uids(con, uids))
        if puids:
            con.select(ALL, readonly=False)
            puids = imap.Uids(puids)
            log.info('## deleting %s from %r', puids, ALL)
            con.store(puids, '+FLAGS.SILENT', '\Deleted')
            con.expunge()

    # messages should be inserted in the particular order
    # for THREAD IMAP extension, so no async here
    con.select(SRC)
    uids = imap.Uids(uids, size=batch)
    uids.call(parse_uids, uids, con)

    con.setmetadata(ALL, 'uidnext', str(uidnext))
    con.select(ALL)
    update_threads(con, 'UID %s' % ','.join(parsed_uids(con, uids.val)))
    con.logout()


def update_threads(con, criteria=None):
    con.select(ALL)
    criteria = criteria or 'ALL'
    thrs_set = con.thread('REFS UTF-8 INTHREAD REFS %s' % criteria)
    if not thrs_set:
        log.info('## no threads are updated')
        return

    msgs = {}
    uids = thrs_set.all_uids
    res = con.fetch(uids, '(FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid, flags = re.search(
            r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode()
        ).groups()
        msgs[uid] = {
            'flags': flags.split(),
            'date': json.loads(res[i][1])['date']
        }

    thrs = {}
    for thrids in thrs_set:
        if len(thrids) == 1:
            latest = thrids[0]
        else:
            latest = sorted(
                (t for t in thrids if '#link' not in msgs[t]['flags']),
                key=lambda i: msgs[i]['date']
            )[-1]
        thrs[latest] = thrids

    con.select(ALL, readonly=False)
    res = con.search('KEYWORD #latest')
    clean = set(res[0].decode().split()).intersection(uids) - set(thrs)
    if clean:
        con.store(clean, '-FLAGS.SILENT', '#latest')
    con.store(list(thrs), '+FLAGS.SILENT', '#latest')
    log.info('## updated %s threads', len(thrs))


def link_threads(uids, box=ALL):
    con = client()
    res = con.search('INTHREAD REFS UID %s' % ','.join(uids))
    uids = res[0].decode().split()
    res = con.search('KEYWORD #link UID %s' % ','.join(uids))
    refs = res[0].decode().split()
    if refs:
        c = client(None)
        src_refs = origin_uids(con, refs)
        c.select(SRC, readonly=False)
        c.store(src_refs, '+FLAGS.SILENT', '\\Deleted')
        c.expunge()
        c.select(box, readonly=False)
        c.store(refs, '+FLAGS.SILENT', '\\Deleted')
        c.expunge()

    res = con.fetch(uids, 'BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]')
    msgids = [
        res[i][1].decode().strip().split(' ')[1]
        for i in range(0, len(res), 2)
    ]

    msgid = gen_msgid('link')
    msg = MIMEPart(email.policy.SMTPUTF8)
    msg.add_header('Subject', 'Dummy: linking threads')
    msg.add_header('References', ' '.join(msgids))
    msg.add_header('Message-Id', msgid)
    msg.add_header('From', msgid)
    msg.add_header('Date', formatdate())
    res = con.append(SRC, '#link', None, msg.as_bytes())
    con.logout()
    parse()
    return res[0].decode()
