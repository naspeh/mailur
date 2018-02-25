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


def pair_msgid(mid):
    origin_uid = msgids().get(mid.lower())
    return origin_uid and pair_origin_uids(origin_uid)[0]


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
            mid = email.message_from_bytes(line)['message-id'].strip().lower()
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


@fn_time
@using(None)
def save_addrs(addrs, con=None):
    data = json.dumps(addrs)
    con.setmetadata(SRC, 'user/addresses', data)


@using(None)
def get_addrs(con=None):
    res = con.getmetadata(SRC, 'user/addresses')
    if len(res) == 1:
        return None
    data = res[0][1].decode()
    addrs = json.loads(data)
    return addrs


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
            msg_obj, marks = message.parsed(m[1], uid, time, flags, mids)
            flags += marks
            msg = msg_obj.as_bytes()
            yield time, ' '.join(flags), msg

    return con.multiappend(ALL, list(msgs()))


def parse(criteria=None, *, batch=1000, threads=10):
    con = client(SRC)
    uidnext = 1
    if criteria is None:
        res = con.getmetadata(ALL, 'uidnext')
        if len(res) > 1:
            uidnext = int(res[0][1].decode())
            log.info('## saved: uidnext=%s', uidnext)
        criteria = 'UID %s:*' % uidnext

    link_threads_by_headers(con, criteria)

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
            save_msgids()
        else:
            puids = pair_origin_uids(uids)
        if puids:
            con.select(ALL, readonly=False)
            puids = imap.Uids(puids)
            log.info('## deleting %s from %r', puids, ALL)
            con.store(puids, '+FLAGS.SILENT', '\\Deleted')
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


def link_threads_by_headers(con, criteria):
    res = con.search('%s HEADER X-Thread-ID <' % criteria)
    thrs = res[0].decode().split()
    if not thrs:
        return

    res = con.fetch(thrs, 'BODY.PEEK[HEADER.FIELDS (X-Thread-ID Message-ID)]')
    thrs = {}
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        hdr = email.message_from_bytes(res[i][1])
        msgid = hdr['Message-ID']
        thrid = hdr['X-Thread-ID']
        thrs.setdefault(thrid, [])
        thrs[thrid].append(msgid)

    mids = msgids()
    clean = []
    msgs = []
    for thrid, ids in thrs.items():
        linkid = thrid.lower()
        uid = mids.get(linkid)
        if uid:
            clean += uid
            res = con.fetch(uid, 'BODY.PEEK[HEADER.FIELDS (References)]')
            refs = email.message_from_bytes(res[0][1])['References'].split()
            ids = ids + refs
        msg = message.link(ids, linkid)
        msgs.append(msg)

    if clean:
        with client(ALL, readonly=False) as c:
            c.store(pair_origin_uids(clean), '+FLAGS.SILENT', '\\Deleted')
            c.expunge()
        con.select(SRC, readonly=False)
        con.store(clean, '+FLAGS.SILENT', '\\Deleted')
        con.expunge()
        con.select(SRC)

    con.multiappend(SRC, [(None, '#link', m.as_bytes()) for m in msgs])
    save_msgids()


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
                c.expunge()
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
def raw_msg(uid, box, parsed=False, con=None):
    con.select(box)
    res = con.fetch(uid, 'BODY.PEEK[]')
    body = res[0][1] if res else None
    if body and parsed:
        body = email.message_from_bytes(body)
    return body


@fn_time
@using(None)
def raw_part(uid, box, part, con=None):
    con.select(box)
    fields = '(BINARY.PEEK[{0}] BINARY.PEEK[{0}.mime])'.format(part)
    res = con.fetch(uid, fields)
    body = res[0][1]
    mime = res[1][1]
    content_type = email.message_from_bytes(mime).get_content_type()
    return body, content_type


@fn_time
@using()
def fetch_msg(uid, draft=False, con=None):
    fields = (
        '(FLAGS BINARY.PEEK[HEADER] BINARY.PEEK[1] BINARY.PEEK[%s])'
        % (3 if draft else 2)
    )
    res = con.fetch(uid, fields)
    flags = re.search(r'FLAGS \(([^)]*)\)', res[0][0].decode()).group(1)
    head = email.message_from_string(res[0][1].decode())
    meta = json.loads(res[1][1].decode())
    txt = res[2][1].decode()
    return flags, head, meta, txt


@fn_time
@using()
def search_msgs(query, sort='(REVERSE DATE)', con=None):
    res = con.sort(sort, query)
    uids = res[0].decode().split()
    log.debug('## query: %r; messages: %s', query, len(uids))
    return uids


@fn_time
@using()
def msgs_info(uids, con=None):
    res = con.fetch(uids, '(UID FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid, flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode())
            .groups()
        )
        flags = flags.split()
        yield uid, res[i][1], flags, None


@fn_time
@using()
def msgs_body(uids, con=None):
    res = con.fetch(uids, '(UID BINARY.PEEK[2])')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        yield uid, res[i][1].decode()


@fn_time
@using(None)
def msg_flags(uid, box=ALL, con=None):
    con.select(box)
    res = con.fetch(uid, 'FLAGS')
    flags = re.search(r'FLAGS \(([^)]*)\)', res[0].decode()).group(1)
    return flags


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
def thrs_info(uids, tags=None, con=None):
    special_tag = None
    if not tags:
        pass
    elif '#trash' in tags:
        special_tag = '#trash'
    elif '#spam' in tags:
        special_tag = '#spam'

    q = 'REFS UTF-8 INTHREAD REFS UID %s' % ','.join(uids)
    thrs = con.thread(q)
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
        draft_id = None
        for uid in thr:
            if uid not in all_msgs:
                continue
            msg_flags = all_flags[uid]
            if '#latest' in msg_flags:
                thrid = uid
            if not special_tag and {'#trash', '#spam'}.intersection(msg_flags):
                continue
            elif special_tag and special_tag not in msg_flags:
                continue
            info = all_msgs[uid]
            info['uids'] = thr
            thr_from.append((info['date'], info.get('from')))
            if not msg_flags:
                continue
            if '\\Seen' not in msg_flags:
                unseen = True
            if '\\Draft' in msg_flags:
                draft_id = info['draft_id']
            thr_flags.extend(msg_flags)
        if thrid is None:
            raise ValueError('No #latest for %s' % thr)

        flags = list(set(' '.join(thr_flags).split()))
        if unseen and '\\Seen' in flags:
            flags.remove('\\Seen')
        addrs = [v for k, v in sorted(thr_from, key=lambda i: i[0])]
        info = all_msgs[thrid]
        info['uids'] = thr
        if draft_id:
            info['draft_id'] = draft_id
        yield thrid, info, flags, addrs


@fn_time
@using()
def tags_info(con=None):
    unread = {}
    hidden = {}
    res = con.search('UNSEEN')
    uids = res[0].decode().split()
    if uids:
        res = con.fetch(uids, 'FLAGS')
        for line in res:
            flags = re.search(
                r'FLAGS \(([^)]*)\)', line.decode()
            ).group(1).split()
            for f in flags:
                unread.setdefault(f, 0)
                unread[f] += 1
                hide_flags = None
                if '#trash' in flags:
                    hide_flags = {'#trash'}
                elif '#spam' in flags:
                    hide_flags = {'#spam'}
                if hide_flags and hide_flags - {f}:
                    hidden.setdefault(f, 0)
                    hidden[f] += 1
    unread = {
        k: v - hidden.get(k, 0)
        for k, v in unread.items() if hidden.get(k) != v
    }
    tags = {
        t: dict(get_tag(t), unread=unread.get(t, 0))
        for t in con.flags
    }
    tags.update({
        t: dict(tags.get(t, get_tag(t)), pinned=1)
        for t in ('#inbox', '#spam', '#trash')
    })
    return tags


@fn_time
@using(None)
def del_msg(uid, con=None):
    pid = pair_origin_uids([uid])[0]
    for box, uid in ((SRC, uid), (ALL, pid)):
        con.select(box, readonly=False)
        con.store([uid], '+FLAGS.SILENT', '\\Deleted')
        con.expunge()


@fn_time
@using(None, readonly=False)
def new_msg(msg, flags, con=None):
    uid = con.append(SRC, flags, None, msg.as_bytes())
    save_msgids([uid])
    parse()
    return pair_origin_uids([uid])[0]
