import email
import functools as ft
import hashlib
import imaplib
import json
import re

from gevent import socket

from . import MASTER, USER, fn_time, imap, log, message

SRC = 'Src'
ALL = 'All'


class Local(imaplib.IMAP4, imap.Conn):
    def __init__(self, username):
        self.username = username
        self.defaults()
        super().__init__('localhost')

    def _create_socket(self):
        return socket.create_connection((self.host, self.port))

    def login_root(self):
        master, pwd = MASTER
        username = '%s*%s' % (self.username, master)
        return imap.login(self, username, pwd)


def connect(username=None, password=None):
    con = Local(username or USER)
    if password is None:
        con.login_root()
    else:
        imap.login(con, username, password)

    # For searching with non ascii symbols (Dovecot understands this)
    con._encoding = 'utf-8'
    return con


def client(box=ALL, readonly=True):
    ctx = imap.client(connect, dovecot=True, writable=True)
    if box:
        ctx.select(box, readonly=readonly)
    return ctx


def using(box=ALL, readonly=True):
    return imap.using(client, box, readonly)


def fn_cache(fn):
    fn.cache = {}

    @ft.wraps(fn)
    def inner(*a, **kw):
        key = a, tuple((k, kw[k]) for k in sorted(kw))
        if key not in fn.cache.get(USER, {}):
            res = fn(*a, **kw)
            fn.cache.setdefault(USER, {})
            fn.cache[USER][key] = res
        return fn.cache[USER][key]

    inner.cache_clear = lambda: fn.cache.pop(USER, None)
    return inner


@fn_cache
@using(None)
def saved_tags(reverse=False, con=None):
    res = con.getmetadata(SRC, 'tags')
    if len(res) == 1:
        return {}
    return json.loads(res[0][1].decode())


def get_tag(name):
    if re.match(r'(?i)^[\\]?[a-z0-9/#\-.,:;!?]*$', name):
        tag = name
    else:
        tag = '#' + hashlib.md5(name.lower().encode()).hexdigest()[:8]

    tags = saved_tags()
    info = tags.get(tag)
    if info is None:
        info = {'name': name}
        if name != tag:
            tags[tag] = info
            with client(None) as con:
                con.setmetadata(SRC, 'tags', json.dumps(tags))
            log.info('## new tag %s: %r', tag, name)
    info.update(id=tag)
    return info


@fn_time
@using()
def save_uid_pairs(uids=None, con=None):
    if uids:
        pairs = uid_pairs()
    else:
        uids = '1:*'
        pairs = {}
    res = con.fetch(uids, '(UID BODY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        origin_uid = json.loads(res[i][1].decode())['origin_uid']
        pairs[origin_uid] = uid
    con.setmetadata(ALL, 'uidpairs', json.dumps(pairs))
    uid_pairs.cache_clear()


@fn_cache
@fn_time
@using(None)
def uid_pairs(con=None):
    res = con.getmetadata(ALL, 'uidpairs')
    if len(res) == 1:
        return {}

    return json.loads(res[0][1].decode())


@fn_time
def pair_origin_uids(uids):
    pairs = uid_pairs()
    return tuple(pairs[i] for i in uids if i in pairs)


@fn_time
def pair_parsed_uids(uids):
    pairs = {v: k for k, v in uid_pairs().items()}
    return tuple(pairs[i] for i in uids if i in pairs)


@fn_time
@using(SRC)
def save_msgids(uids=None, con=None):
    if uids:
        mids = msgids()
    else:
        uids = '1:*'
        mids = {}
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
    con.setmetadata(SRC, 'msgids', json.dumps(mids))
    msgids.cache_clear()


@fn_cache
@fn_time
@using(None)
def msgids(con=None):
    res = con.getmetadata(SRC, 'msgids')
    if len(res) == 1:
        return {}

    return json.loads(res[0][1].decode())


@using(SRC)
def parse_msgs(uids, con=None):
    res = con.fetch(uids.str, '(UID INTERNALDATE FLAGS BODY.PEEK[])')
    mids = msgids()

    def msgs():
        for i in range(0, len(res), 2):
            m = res[i]
            uid, time, flags = re.search(
                r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)',
                m[0].decode()
            ).groups()
            flags = flags.split()
            if flags.count('\\Recent'):
                flags.remove('\\Recent')
            try:
                msg_obj = message.parsed(m[1], uid, time, mids)
                if msg_obj['X-Dpulicate']:
                    flags.append('#dup')
                if msg_obj['X-Err-Parsed']:
                    flags.append('#err')
                msg = msg_obj.as_bytes()
            except Exception as e:
                msgid = re.findall(b'^(?im)message-id:.*', m[1])
                log.exception('## %r uid=%s %s', e, uid, msgid)
                continue
            yield time, ' '.join(flags), msg

    return con.multiappend(ALL, msgs())


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
    puids = ','.join(uids.call_async(parse_msgs, uids))
    if criteria.lower() == 'all' or count == '0':
        puids = '1:*'

    with client(ALL) as con:
        con.setmetadata(ALL, 'uidnext', str(uidnext))
        save_uid_pairs(puids)
        update_threads(con, 'UID %s' % uids.str)


@fn_time
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


@fn_time
@using(readonly=False)
def msgs_flag(uids, old, new, con=None):
    rm = set(old) - set(new) if old else []
    if rm:
        con.store(uids, '-FLAGS.SILENT', ' '.join(rm))

    add = set(new) - set(old) if new else []
    if add:
        con.store(uids, '+FLAGS.SILENT', ' '.join(add))


@fn_time
@using()
def link_threads(uids, con=None):
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
        con.select(ALL, readonly=False)
        con.store(refs, '+FLAGS.SILENT', '\\Deleted')
        con.expunge()
        con.select(ALL)

    res = con.fetch(uids, 'BODY.PEEK[1]')
    msgids = [
        json.loads(res[i][1].decode())['msgid']
        for i in range(0, len(res), 2)
    ]

    msg = message.link(msgids)
    uid = con.append(SRC, '#link', None, msg.as_bytes())
    save_msgids([uid])
    parse()
    return uid


@fn_time
@using(None)
def raw_msg(uid, box, part=None, con=None):
    con.select(box)
    field = 'BODY[]' if part is None else ('BINARY[%s]' % part)
    res = con.fetch(uid, field)
    if not res:
        return
    return res[0][1]


@fn_time
@using()
def search_msgs(query, sort='(REVERSE DATE)', con=None):
    res = con.sort(sort, 'UNKEYWORD #link %s' % query)
    uids = res[0].decode().split()
    log.debug('## query: %r; messages: %s', query, len(uids))
    return uids


@fn_time
@using()
def msgs_info(uids, hide_flags=None, con=None):
    res = con.fetch(uids, '(UID FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid, flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode())
            .groups()
        )
        flags = flags.split()
        if hide_flags:
            flags = sorted(set(flags) - set(hide_flags))
        yield uid, res[i][1], flags, None


@fn_time
@using()
def msgs_body(uids, con=None):
    res = con.fetch(uids, '(UID BINARY.PEEK[2])')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        yield uid, res[i][1].decode()


@fn_time
@using()
def search_thrs(query, con=None):
    criteria = 'INTHREAD REFS %s KEYWORD #latest' % query
    res = con.sort('(REVERSE DATE)', criteria)
    uids = res[0].decode().split()
    log.debug('## query: %r; threads: %s', query, len(uids))
    return uids


@fn_time
@using()
def thrs_info(uids, hide_flags=None, con=None):
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

    for thr in thrs:
        thrid = None
        thr_flags = []
        thr_from = []
        unseen = False
        for uid in thr:
            if uid not in all_msgs:
                continue
            info = all_msgs[uid]
            info['uids'] = thr
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
        if hide_flags:
            flags = sorted(set(flags) - set(hide_flags))
        addrs = [v for k, v in sorted(thr_from, key=lambda i: i[0])]
        yield thrid, all_msgs[thrid], flags, addrs


@fn_time
@using()
def tags_info(con=None):
    unread = {}
    res = con.search('UNSEEN')
    uids = res[0].decode().split()
    if uids:
        res = con.fetch(uids, 'FLAGS')
        for line in res:
            flags = re.search(
                r'FLAGS \(([^)]*)\)', line.decode()
            ).group(1)
            for f in flags.split():
                unread.setdefault(f, 0)
                unread[f] += 1
    tags = {
        t: dict(get_tag(t), unread=unread.get(t, 0))
        for t in con.flags
    }
    tags.update({
        t: dict(tags.get(t, get_tag(t)), pinned=1)
        for t in ('#inbox', '#spam', '#trash')
    })
    return tags
