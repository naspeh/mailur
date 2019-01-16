import datetime as dt
import email
import functools as ft
import hashlib
import imaplib
import json
import re

from gevent import joinall, socket, spawn

from . import cache, conf, fn_time, html, imap, log, message, user_lock

SRC = 'INBOX'
ALL = 'mlr/All'
SYS = 'mlr/Sys'


class Local(imaplib.IMAP4, imap.Conn):
    def __init__(self, username):
        self.username = username
        self.defaults()
        super().__init__('localhost')

    def _create_socket(self):
        return socket.create_connection((self.host, self.port))

    def login_root(self):
        master, pwd = conf['MASTER']
        username = '%s*%s' % (self.username, master)
        return imap.login(self, username, pwd)


def connect(username=None, password=None):
    con = Local(username or conf['USER'])
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


def using(box=ALL, readonly=True, name='con', reuse=True):
    return imap.using(client, box, readonly, name, reuse)


@using(SYS)
def metadata_uids(con=None):
    def get_map():
        uids = {}
        all_uids = set()
        res = con.fetch('1:*', '(UID FLAGS)')
        for line in res:
            val = re.search(r'UID (\d+) FLAGS \(([^)]*)\)', line.decode())
            if not val:
                continue
            uid, flags = val.groups()
            name = [f for f in flags.split() if not f.startswith('\\')][0]
            if name not in uids or int(uids[name]) < int(uid):
                uids[name] = uid
            all_uids.add(uid)
        # clean = all_uids.difference(uids.values())
        # if clean:
        #     with client(SYS, readonly=False) as c:
        #         c.store(clean, '+FLAGS.SILENT', '\\Deleted')
        #         c.expunge()
        return uids

    get_map = fn_time(get_map, 'metadata_uids.get_map')

    cache_key = 'metadata'
    value = cache.get(cache_key)
    if not value or con.uidnext != value['uidnext']:
        data = {'uidnext': con.uidnext, 'map': get_map()}
        cache.set(cache_key, data)
    return cache.get(cache_key)['map']


def metadata(name, default):
    @user_lock(name)
    def inner(*a, con=None, **kw):
        val = inner.fn(*a, con=con, **kw)
        if val.get('skip'):
            return get()

        data = json.dumps(val['data'])
        con.append(SYS, name, None, data.encode())

        if val.get('post'):
            val['post']()
        return val['return'] if 'return' in val else val['data']

    @using(SYS)
    def get(con=None):
        def inner():
            res = con.fetch(uidlatest, 'BODY.PEEK[]')
            return json.loads(res[0][1].decode())

        uidlatest = metadata_uids(con=con).get(name)
        if not uidlatest:
            if isinstance(default, Exception):
                raise default
            return default()

        cache_key = 'metadata:%s' % name
        if cache.exists(cache_key):
            uid, value = cache.get(cache_key)
            if uid == uidlatest:
                return value

        value = inner()
        cache.set(cache_key, (uidlatest, value))
        return value

    def wrapper(fn):
        inner_fn = ft.wraps(fn)(inner)
        inner_fn.fn = fn

        get_fn = fn_time(get, '%s.get' % inner_fn.__name__)
        inner_fn.get = get_fn
        return inner_fn
    return wrapper


@using(None)
@metadata('tags', lambda: {})
def data_tags(tags, con=None):
    return {'data': tags}


def get_tag(name):
    if re.match(r'(?i)^[\\]?[a-z0-9/#\-.,:;!?]*$', name):
        tag = name
    else:
        tag = '#' + hashlib.md5(name.lower().encode()).hexdigest()[:8]

    tags = data_tags.get()
    info = tags.get(tag)
    if info is None:
        info = {'name': name}
        if name != tag:
            tags[tag] = info
            data_tags(tags)
            log.info('## new tag %s: %r', tag, name)
    info.update(id=tag)
    return info


@fn_time
@using()
@metadata('uidpairs', lambda: ({}, {}))
def data_uidpairs(uids=None, con=None):
    if uids:
        origin, parsed = data_uidpairs.get()
    else:
        uids = '1:*'
        origin = {}
        parsed = {}

    res = con.fetch(uids, '(UID BODY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        origin_uid = json.loads(res[i][1].decode())['origin_uid']
        origin[origin_uid] = uid
        parsed[uid] = origin_uid
    return {'data': [origin, parsed]}


@fn_time
def pair_origin_uids(uids):
    origin, _ = data_uidpairs.get()
    return tuple(origin[i] for i in uids if i in origin)


@fn_time
def pair_parsed_uids(uids):
    _, parsed = data_uidpairs.get()
    return tuple(parsed[i] for i in uids if i in parsed)


def pair_msgid(mid):
    origin_uid = data_msgids.get().get(mid.lower())
    return origin_uid and pair_origin_uids(origin_uid)[0]


@fn_time
@using(SRC)
@metadata('msgids', lambda: {})
def data_msgids(uids=None, rm=False, con=None):
    if uids:
        mids = data_msgids.get()
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
        if rm and len(uids) == 1:
            del mids[mid]
        elif rm:
            uids.remove(uid)
            mids[mid] = uids
        else:
            uids.append(uid)
            if len(uids) > 1:
                uids = sorted(uids, key=lambda i: int(i))
            mids[mid] = uids
    return {'data': mids}


@fn_time
@using()
@metadata('links', lambda: [])
def data_links(uids, unlink=False, con=None):
    thrids, thrs = data_threads.get()
    all_uids = sum((thrs[thrids[uid]] for uid in uids), [])

    res = con.fetch(all_uids, 'BODY.PEEK[1]')
    mids = []
    for i in range(0, len(res), 2):
        meta = json.loads(res[i][1].decode())
        mids.append(meta['msgid'])

    msgids_set = set(mids)
    links = data_links.get()
    links = [link for link in links if not msgids_set.intersection(link)]
    if not unlink:
        links.append(mids)

    return {
        'data': links,
        'return': all_uids,
        'post': lambda: data_threads(all_uids),
    }


def link_threads(uids):
    return data_links(uids)


def unlink_threads(uids):
    return data_links(uids, unlink=True)


@fn_time
@using()
@metadata('addresses', lambda: ({}, {}))
def data_addresses(uids=None, con=None):
    def fill(store, meta, fields):
        addrs = (meta[i] for i in fields if meta.get(i))
        addrs = sum(([a] if isinstance(a, dict) else a for a in addrs), [])
        for addr in addrs:
            a = addr['addr']
            if a not in store or store[a] != addr:
                addr['time'] = meta['date']
                store[a] = addr
            elif store[a]['time'] < meta['date']:
                store[a]['time'] = meta['date']

    if uids:
        addrs_from, addrs_to = data_addresses.get()
    else:
        uids = '1:*'
        addrs_from, addrs_to = {}, {}

    res = con.fetch(uids, '(FLAGS BODY.PEEK[1])')
    for i in range(0, len(res), 2):
        meta = json.loads(res[i][1].decode())
        fill(addrs_to, meta, ('from', 'to', 'cc'))
        flags = re.search(r'FLAGS \(([^)]*)\)', res[i][0].decode()).group(1)
        if {'#sent', '\\Draft'}.intersection(flags.split()):
            fill(addrs_from, meta, ('from',))

    return {'data': [addrs_from, addrs_to]}


@using(SRC, reuse=False)
def parse_msgs(uids, con=None):
    res = con.fetch(uids.str, '(UID INTERNALDATE FLAGS BODY.PEEK[])')
    mids = data_msgids.get()

    def msgs():
        for i in range(0, len(res), 2):
            line, body = res[i]
            pattern = r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)'
            uid, time, flags = re.search(pattern, line.decode()).groups()
            flags = flags.split()
            msg_obj, marks = message.parsed(body, uid, time, flags, mids)
            flags += marks
            msg = msg_obj.as_bytes()
            yield time, ' '.join(flags), msg

    return con.multiappend(ALL, list(msgs()))


@fn_time
@user_lock('parse')
@using(None)
def parse(criteria=None, con=None, **opts):
    uidnext = 1
    if criteria is None:
        res = con.getmetadata(ALL, 'uidnext')
        if len(res) > 1:
            uidnext = int(res[0][1].decode())
            log.info('## saved: uidnext=%s', uidnext)
        criteria = 'UID %s:*' % uidnext

    con.select(SRC)
    res = con.sort('(ARRIVAL)', criteria)
    uids = [i for i in res[0].decode().split(' ') if i and int(i) >= uidnext]
    if not uids:
        log.info('## all parsed already')
        return

    uidnext = con.uidnext
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
            con.store(puids, '+FLAGS.SILENT', '\\Deleted')
            con.expunge()
            data_uidpairs()
            data_addresses()

    uids = imap.Uids(uids, **opts)
    puids = ','.join(uids.call_async(parse_msgs, uids))
    if criteria.lower() == 'all' or count == '0':
        puids = '1:*'

    con.setmetadata(ALL, 'uidnext', str(uidnext))
    data_uidpairs(puids)
    data_addresses(puids)
    data_msgids()
    data_threads('UID %s' % uids.str)


@using(None)
@metadata('threads', lambda: [{}, {}])
def data_threads(criteria=None, con=None):
    con.select(SRC)
    # TODO: think about optimisation when criteria is partial
    # criteria = criteria or 'ALL'
    criteria = 'ALL'
    res = con.search(criteria)
    src_uids = res[0].decode().split()
    if not src_uids:
        log.info('## all threads are updated already')
        return {'skip': True}

    con.select(ALL)
    uids = pair_origin_uids(src_uids)
    criteria = 'UID %s' % ','.join(uids)

    orig_thrs = con.thread('REFS UTF-8 INTHREAD REFS %s' % criteria)
    if not orig_thrs:
        log.info('## no threads are updated')
        return {'skip': True}

    uids = set(orig_thrs.all_uids)

    mids = data_msgids.get()
    all_links = []
    linked_uids = set()
    for link in data_links.get():
        thrids = sum((mids[mid] for mid in link), [])
        thrids = pair_origin_uids(thrids)
        if not uids.intersection(thrids):
            continue
        all_links.append(thrids)
        linked_uids.update(thrids)

    msgs = {}
    res = con.fetch('1:*', '(INTERNALDATE FLAGS)')
    for line in res:
        pattern = r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)'
        uid, time, flags = re.search(pattern, line.decode()).groups()
        arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
        arrived = int(arrived.timestamp())
        msgs[uid] = {
            'flags': flags.split(),
            'arrived': arrived,
        }
    thrs = {}
    thrids = {}
    for uids in orig_thrs:
        uids_set = set(uids)
        if uids_set.intersection(linked_uids):
            uids = (list(l) for l in all_links if uids_set.intersection(l))
            uids = sum(uids, [])
            uids = uids + [uid for uid in uids_set if uid not in uids]

        if len(uids) == 1:
            thrid = uids[0]
        else:
            uids = sorted(uids, key=lambda i: msgs[i]['arrived'] or 0)
            thrid = uids[-1]

        for uid in uids:
            thrids[uid] = thrid
            if uid == thrid:
                thrs[uid] = uids
            elif uid in thrs:
                del thrs[uid]

    log.info('## updated %s threads', len(thrs))
    return {'data': [thrids, thrs]}


@fn_time
@using(SRC, name='con_src', readonly=False)
@using(ALL, name='con_all', readonly=False)
def msgs_flag(uids, old, new, con_src=None, con_all=None):
    def store(con, uids):
        rm = set(old) - set(new) if old else []
        if rm:
            con.store(uids, '-FLAGS.SILENT', ' '.join(rm))

        add = set(new) - set(old) if new else []
        if add:
            con.store(uids, '+FLAGS.SILENT', ' '.join(add))

    jobs = [
        spawn(store, con_all, uids),
        spawn(store, con_src, pair_parsed_uids(uids))
    ]
    joinall(jobs, raise_error=True)


@fn_time
@using(SRC, readonly=False)
def clean_flags(con=None):
    con.store('1:*', '-FLAGS.SILENT', '#err #dup #latest')
    res = con.search('HEADER MESSAGE-ID @mailur.link>')
    uids = res[0].decode().split()
    con.store(uids, '+FLAGS.SILENT', '#link \\Seen')
    sync_flags_to_all()
    data_threads()


@fn_time
@using(SRC, name='con_src')
@using(ALL, name='con_all', readonly=False)
def sync_flags_to_all(con_src=None, con_all=None):
    skip_flags = set(['#latest', '#err', '#dup'])
    for flag in con_src.flags:
        if flag in skip_flags:
            continue
        q = flag[1:] if flag.startswith('\\') else 'keyword %s' % flag
        res = con_src.search(q)
        oids = res[0].decode().split()
        pairs = set(pair_origin_uids(oids))
        res = con_all.search(q)
        pids = set(res[0].decode().split())
        con_all.store(pairs - pids, '+FLAGS.SILENT', flag)
        con_all.store(pids - pairs, '-FLAGS.SILENT', flag)
    rm_flags = set(con_all.flags) - set(con_src.flags) - skip_flags
    if rm_flags:
        con_all.store('1:*', '-FLAGS.SILENT', ' '.join(rm_flags))


@fn_time
@using(SRC, name='con_src', readonly=False)
@using(ALL, name='con_all')
def sync_flags_to_src(con_src=None, con_all=None):
    for flag in con_all.flags:
        if flag in ('#latest', '#err', '#dup'):
            continue
        q = flag[1:] if flag.startswith('\\') else 'keyword %s' % flag
        res = con_all.search(q)
        pids = res[0].decode().split()
        pairs = set(pair_parsed_uids(pids))
        res = con_src.search(q)
        oids = set(res[0].decode().split())
        con_src.store(pairs - oids, '+FLAGS.SILENT', flag)
        con_src.store(oids - pairs, '-FLAGS.SILENT', flag)
    rm_flags = set(con_src.flags) - set(con_all.flags)
    if rm_flags:
        con_src.store('1:*', '-FLAGS.SILENT', ' '.join(rm_flags))


@fn_time
@using(None, reuse=False)
def sync_flags(con=None, timeout=None):
    @using(SRC, name='con_src')
    @using(ALL, name='con_all', readonly=False)
    def handler(res, con_src=None, con_all=None):
        modseq0 = modseq[0]
        modseq_ = re.search(r'MODSEQ \((\d+)\)', res[0].decode()).group(1)
        if int(modseq_) < int(modseq0):
            return
        modseq[0] = modseq_
        res = con_src.fetch('1:*', '(UID FLAGS) (CHANGEDSINCE %s)' % modseq0)
        src_flags = {}
        for line in res:
            val = re.search(r'UID (\d+) FLAGS \(([^)]*)\)', line.decode())
            if not val:
                continue
            uid, flags = val.groups()
            src_flags[uid] = flags

        if not src_flags:
            return

        actions = {}
        _, parsed = data_uidpairs.get()
        pids = pair_origin_uids(src_flags)
        res = con_all.fetch(pids, '(UID FLAGS)')
        for line in res:
            pattern = r'UID (\d+) FLAGS \(([^)]*)\)'
            uid, flags = re.search(pattern, line.decode()).groups()
            flags = set(flags.split())
            orig_flags = set(src_flags[parsed[uid]].split())
            val = sorted(orig_flags - flags)
            if val:
                key = ('+FLAGS.SILENT', ' '.join(val))
                actions.setdefault(key, [])
                actions[key].append(uid)
            val = sorted(flags - orig_flags - set(['#latest']))
            if val:
                key = ('-FLAGS.SILENT', ' '.join(val))
                actions.setdefault(key, [])
                actions[key].append(uid)
        log.debug('## sync: MODSEQ=%s %s', modseq_, actions)
        for action, uids in actions.items():
            con_all.store(uids, *action)

    res = con.status(SRC, '(UIDVALIDITY HIGHESTMODSEQ)')
    pair = re.search(r'UIDVALIDITY (\d+) HIGHESTMODSEQ (\d+)', res[0].decode())
    uidval, modseq = pair.groups()
    log.info('## %s UIDVALIDITY=%s HIGHESTMODSEQ=%s', con, uidval, modseq)
    modseq = [modseq]
    con.select(SRC)
    con.idle(handler, 'FETCH', timeout=timeout)


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
        '(FLAGS BINARY.PEEK[HEADER] BINARY.PEEK[1] BINARY.PEEK[2.%s])'
        % ('2' if draft else '1')
    )
    res = con.fetch(uid, fields)
    flags = re.search(r'FLAGS \(([^)]*)\)', res[0][0].decode()).group(1)
    head = email.message_from_string(res[0][1].decode())
    meta = json.loads(res[1][1].decode())
    txt = res[2][1].decode()
    return flags, head, meta, txt


@fn_time
@using()
def search_msgs(query, sort='(REVERSE ARRIVAL)', con=None):
    res = con.sort(sort, query)
    uids = res[0].decode().split()
    log.debug('## query: %r; messages: %s', query, len(uids))
    return uids


@fn_time
@using()
def msgs_info(uids, con=None):
    res = con.fetch(uids, '(UID FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        pattern = r'UID (\d+) FLAGS \(([^)]*)\)'
        uid, flags = re.search(pattern, res[i][0].decode()).groups()
        flags = flags.split()
        yield uid, res[i][1], flags, None


@fn_time
@using()
def msgs_body(uids, fix_privacy=False, con=None):
    res = con.fetch(uids, '(UID BINARY.PEEK[2.1])')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        body = res[i][1].decode()
        body = html.fix_privacy(body, only_proxy=not fix_privacy)
        yield uid, body


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
    res = con.search(query)
    uids = res[0].decode().split()
    if uids:
        thrids, thrs = data_threads.get()
        uids = [thrids[uid] for uid in uids]
        res = con.sort('(REVERSE ARRIVAL)', 'UID %s' % ','.join(uids))
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

    thrids, thrs = data_threads.get()
    uids = [thrids[uid] for uid in uids]
    all_uids = sum((thrs[uid] for uid in uids), [])

    all_flags = {}
    all_msgs = {}
    res = con.fetch(all_uids, '(FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        pattern = r'UID (\d+) FLAGS \(([^)]*)\)'
        uid, flags = re.search(pattern, res[i][0].decode()).groups()
        all_flags[uid] = flags.split()
        all_msgs[uid] = json.loads(res[i][1])

    for thrid in uids:
        thr = thrs[thrid]
        thr_flags = []
        addrs = []
        unseen = False
        draft_id = None
        info = None
        for uid in thr:
            msg_flags = all_flags[uid]
            if not special_tag and {'#trash', '#spam'}.intersection(msg_flags):
                continue
            elif special_tag and special_tag not in msg_flags:
                continue
            info = all_msgs[uid]
            addrs.append(info.get('from'))
            if not msg_flags:
                continue
            if '\\Seen' not in msg_flags:
                unseen = True
            if '\\Draft' in msg_flags:
                draft_id = info['draft_id']
            thr_flags.extend(msg_flags)
        if not info:
            continue
        flags = list(set(' '.join(thr_flags).split()))
        if unseen and '\\Seen' in flags:
            flags.remove('\\Seen')
        info['uids'] = thr
        if draft_id:
            info['draft_id'] = draft_id
        yield thrid, info, flags, addrs


@fn_time
@using()
def tags_info(con=None):
    unread = {}
    hidden = {}
    res = con.search('UNSEEN UNKEYWORD #link')
    uids = res[0].decode().split()
    if uids:
        res = con.fetch(uids, 'FLAGS')
        for line in res:
            flags = re.search(r'FLAGS \(([^)]*)\)', line.decode()).group(1)
            flags = flags.split()
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
    data_msgids([uid], rm=True)
    pid = pair_origin_uids([uid])[0]
    for box, uid in ((SRC, uid), (ALL, pid)):
        con.select(box, readonly=False)
        con.store([uid], '+FLAGS.SILENT', '\\Deleted')
        con.expunge()
    data_threads()


@fn_time
@using(None, readonly=False)
def new_msg(msg, flags, no_parse=False, con=None):
    uid = con.append(SRC, flags, None, msg.as_bytes())
    data_msgids([uid])
    if no_parse:
        return uid, None
    parse()
    return uid, pair_origin_uids([uid])[0]
