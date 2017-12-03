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


def client(box=ALL, readonly=True):
    ctx = imap.client(connect, dovecot=True, writable=True)
    if box:
        ctx.select(box, readonly=readonly)
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
    with client() as con:
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
        tag = con.append(TAGS, '', None, msg.as_bytes())
    get_tags.cache_clear()
    tag = '#t' + tag
    log.info('## added new tag %s: %r', tag, name)
    return tag


@imap.fn_time
def save_uid_pairs(uids=None):
    if uids:
        pairs = uid_pairs()
    else:
        uids = '1:*'
        pairs = {}
    with client() as con:
        res = con.fetch(uids, '(UID BODY.PEEK[1])')
        for i in range(0, len(res), 2):
            uid = res[i][0].decode().split()[2]
            origin_uid = json.loads(res[i][1].decode())['origin_uid']
            pairs[origin_uid] = uid
        con.setmetadata(ALL, 'uidpairs', json.dumps(pairs))
    uid_pairs.cache_clear()


@ft.lru_cache(maxsize=None)
@imap.fn_time
def uid_pairs():
    with client(None) as con:
        res = con.getmetadata(ALL, 'uidpairs')
        if len(res) == 1:
            return {}

    return json.loads(res[0][1].decode())


@imap.fn_time
def pair_origin_uids(uids):
    pairs = uid_pairs()
    return tuple(pairs[i] for i in uids if i in pairs)


@imap.fn_time
def pair_parsed_uids(uids):
    pairs = {v: k for k, v in uid_pairs().items()}
    return tuple(pairs[i] for i in uids if i in pairs)


@imap.fn_time
def save_msgids(uids=None):
    if uids:
        mids = msgids()
    else:
        uids = '1:*'
        mids = {}
    with client(SRC) as con:
        res = con.fetch(uids, 'BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]')
        for i in range(0, len(res), 2):
            uid = res[i][0].decode().split()[2]
            line = res[i][1].strip()
            if line:
                mid = email.message_from_bytes(line)['message-id'].strip()
            else:
                mid = '<mailur@noid>'
            uids = mids.get(mid, [])
            uids.append(uid)
            if len(uids) > 1:
                uids = sorted(uids, key=lambda i: int(i))
            mids[mid] = uids
        con.setmetadata(ALL, 'msgids', json.dumps(mids))
    msgids.cache_clear()


@ft.lru_cache(maxsize=None)
@imap.fn_time
def msgids():
    with client(None) as con:
        res = con.getmetadata(ALL, 'msgids')
        if len(res) == 1:
            return {}

    return json.loads(res[0][1].decode())


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

    meta = {'origin_uid': uid}

    fields = (('from', 1), ('sender', 1), ('to', 0), ('cc', 0), ('bcc', 0))
    for n, one in fields:
        try:
            v = orig[n]
        except Exception as e:
            more = raw[:300].decode()
            log.error('## UID=%s error on header %r: %r\n%s', uid, n, e, more)
            continue
        if not v:
            continue
        v = addresses(v)
        meta[n] = v[0] if one else v

    subj = orig['subject']
    meta['subject'] = str(subj).strip() if subj else subj

    mids = msgids()
    refs = orig['references']
    refs = refs.split() if refs else []
    if not refs:
        in_reply_to = orig['in-reply-to']
        refs = [in_reply_to] if in_reply_to else []
    meta['parent'] = refs[0] if refs else None
    refs = [r for r in refs if r in mids]

    mid = orig['message-id']
    if mid is None:
        log.info('## UID=%s has no "Message-Id" header', uid)
        mid = '<mailur@noid>'
    else:
        mid = mid.strip()
    meta['msgid'] = mid
    if mids[mid][0] != uid:
        log.info('## UID=%s is a duplicate {%r: %r}', uid, mid, mids[mid])
        mid = gen_msgid('dup')

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    meta['arrived'] = int(arrived.timestamp())

    date = orig['date']
    meta['date'] = date and int(parsedate_to_datetime(date).timestamp())

    txt = orig.get_body(preferencelist=('plain', 'html'))
    body = ''
    if txt:
        try:
            body = txt.get_content()
            body = clean_html(body)
        except Exception as e:
            more = raw[:300].decode()
            log.error('## UID=%s error on body: %r\n%s', uid, e, more)
    meta['preview'] = re.sub('[\s ]+', ' ', body[:200])

    msg = MIMEPart(policy)
    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('Message-Id', mid)
    msg.add_header('Subject', meta['subject'])

    headers = ('Date', 'From', 'Sender', 'To', 'CC', 'BCC',)
    for n in headers:
        try:
            v = orig[n]
        except Exception as e:
            more = raw[:300].decode()
            log.error('## UID=%s error on header %r: %r\n%s', uid, n, e, more)
            continue
        if v is None:
            continue
        msg.add_header(n, v)

    if msg['from'] == 'mailur@link':
        msg.add_header('References', orig['references'])
    elif refs:
        msg.add_header('References', ' '.join(refs))

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

    res = con.sort('(DATE)', criteria)
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
            puids = pair_origin_uids(uids)
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
    save_uid_pairs(puids)
    update_threads(con, 'UID %s' % uids.str)
    con.logout()


def update_threads(con, criteria=None):
    con.select(SRC)
    criteria = criteria or 'ALL'
    res = con.search(criteria)
    src_uids = res[0].decode().split()
    if not src_uids:
        log.info('## all threads are updated already')
        return

    con.select(ALL)
    uids = pair_origin_uids(src_uids)
    criteria = 'UID %s' % ','.join(uids)

    thrs = con.thread('REFS UTF-8 INTHREAD REFS %s' % criteria)
    if not thrs:
        log.info('## no threads are updated')
        return

    msgs = {}
    uids = thrs.all_uids
    res = con.fetch(uids, '(FLAGS BODY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid, flags = re.search(
            r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode()
        ).groups()
        msgs[uid] = {
            'flags': flags.split(),
            'date': json.loads(res[i][1])['date']
        }

    latest = []
    for thrids in thrs:
        if len(thrids) == 1:
            thrid = thrids[0]
        else:
            thrid = sorted(
                (t for t in thrids if '#link' not in msgs[t]['flags']),
                key=lambda i: msgs[i]['date']
            )[-1]
        latest.append(thrid)

    con.select(ALL, readonly=False)
    res = con.search('KEYWORD #latest')
    clean = set(res[0].decode().split()).intersection(uids) - set(latest)
    if clean:
        con.store(clean, '-FLAGS.SILENT', '#latest')
    con.store(latest, '+FLAGS.SILENT', '#latest')
    log.info('## updated %s threads', len(thrs))


def link_threads(uids, box=ALL):
    con = client()
    thrs = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % ','.join(uids))
    uids = thrs.all_uids
    res = con.search('KEYWORD #link UID %s' % ','.join(uids))
    refs = res[0].decode().split()
    if refs:
        uids = set(uids) - set(refs)
        src_refs = pair_parsed_uids(refs)
        if src_refs:
            with client(SRC, readonly=False) as c:
                c.store(src_refs, '+FLAGS.SILENT', '\\Deleted')
        con.select(box, readonly=False)
        con.store(refs, '+FLAGS.SILENT', '\\Deleted')
        con.expunge()
        con.select(box)

    res = con.fetch(uids, 'BODY.PEEK[1]')
    msgids = [
        json.loads(res[i][1].decode())['msgid']
        for i in range(0, len(res), 2)
    ]

    msg = create_link(msgids)
    uid = con.append(SRC, '#link', None, msg.as_bytes())
    save_msgids([uid])
    con.logout()
    parse()
    return uid


def create_link(msgids):
    msgid = gen_msgid('link')
    msg = MIMEPart(email.policy.SMTPUTF8)
    msg.add_header('Subject', 'Dummy: linking threads')
    msg.add_header('References', ' '.join(msgids))
    msg.add_header('Message-Id', msgid)
    msg.add_header('From', 'mailur@link')
    msg.add_header('Date', formatdate())
    return msg


def raw_msg(uid, box):
    with client(box) as con:
        res = con.fetch(uid, 'body[]')
        if not res:
            return
        return res[0][1]


def search_msgs(query):
    with client() as con:
        res = con.sort('(REVERSE DATE)', 'UNKEYWORD #link %s' % query)
        uids = res[0].decode().split()
        log.debug('query: %r; messages: %s', query, len(uids))
        return uids


def msgs_info(uids):
    with client() as con:
        res = con.fetch(uids, '(UID FLAGS BINARY.PEEK[1])')
        for i in range(0, len(res), 2):
            uid, flags = (
                re.search(r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode())
                .groups()
            )
            yield uid, res[i][1], flags.split(), None


def search_thrs(query):
    with client() as con:
        criteria = 'INTHREAD REFS %s KEYWORD #latest' % query
        res = con.sort('(REVERSE DATE)', criteria)
        uids = res[0].decode().split()
        log.debug('query: %r; threads: %s', query, len(uids))
        return uids


def thrs_info(uids):
    con = client()
    thrs = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % ','.join(uids))
    all_flags = {}
    all_msgs = {}
    res = con.fetch(thrs.all_uids, '(FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid, flags = re.search(
            r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode()
        ).groups()
        flags = flags.split()
        if '#link' in flags:
            continue
        all_flags[uid] = flags
        all_msgs[uid] = json.loads(res[i][1])

    msgs = {}
    for thr in thrs:
        thrid = None
        thr_flags = []
        thr_from = []
        unseen = False
        for uid in thr:
            if uid not in all_msgs:
                continue
            info = all_msgs[uid]
            msg_flags = all_flags[uid]
            thr_from.append((info['date'], info.get('from')))
            if not msg_flags:
                continue
            if '\\Seen' not in msg_flags:
                unseen = True
            thr_flags.extend(msg_flags)
            if '#latest' in msg_flags:
                thrid = uid
        if thrid is None:
            raise ValueError('No #latest for %s' % thr)

        flags = list(set(' '.join(thr_flags).split()))
        if unseen and '\\Seen' in flags:
            flags.remove('\\Seen')
        if '#latest' in flags:
            flags.remove('#latest')
        addrs = [v for k, v in sorted(thr_from, key=lambda i: i[0])]
        yield thrid, all_msgs[thrid], flags, addrs

    log.debug('%s threads', len(msgs))
    con.logout()
    return msgs


def tags_info():
    with client() as con:
        res = con.search('UNSEEN')
        uids = res[0].decode().split()
        res = con.fetch(uids, 'FLAGS')
        unreed = {}
        for line in res:
            flags = re.search(
                r'FLAGS \(([^)]*)\)', line.decode()
            ).group(1)
            for f in flags.split():
                unreed.setdefault(f, 0)
                unreed[f] += 1
    tags = {
        t: {'name': t, 'unread': unreed.get(t, 0)}
        for t in ('#inbox',)
    }
    tags.update({
        t: {'name': n, 'unread': unreed.get(t, 0)}
        for t, n in get_tags().items()
    })
    return tags
