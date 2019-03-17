import email
import functools as ft
import hashlib
import imaplib
import re
import textwrap

from gevent import joinall, socket, spawn

from . import cache, conf, fn_time, html, imap, json, lock, log, message

SRC = 'mlr'
ALL = 'mlr/All'
SYS = 'mlr/Sys'
DEL = 'mlr/Del'


class Local(imaplib.IMAP4, imap.Conn):
    def __init__(self, username):
        self.username = username
        self.defaults()
        super().__init__('localhost')

    def _create_socket(self):
        return socket.create_connection((self.host, self.port))


def connect(username, password):
    con = Local(username)
    imap.login(con, username, password)

    # For searching with non ascii symbols (Dovecot understands this)
    con._encoding = 'utf-8'
    return con


def master_login(key='MASTER', username=None):
    master, pwd = conf[key]
    username = '%s*%s' % (username or conf['USER'], master)
    return username, pwd


def client(box=ALL, *, master='MASTER', readonly=True):
    connect_fn = ft.wraps(connect)(ft.partial(connect, *master_login(master)))
    ctx = imap.client(connect_fn, dovecot=True, writable=True)
    if box:
        ctx.select(box, readonly=readonly)
    return ctx


def using(box=ALL, **kw):
    return imap.using(client, box, **kw)


@using(SYS)
def metadata_uids(con=None):
    def get_map():
        uids = {}
        all_uids = set()
        res = con.fetch('1:*', '(UID BODY[HEADER.FIELDS (Subject)])')
        for i in range(0, len(res), 2):
            uid = res[i][0].decode().split()[2]
            name = re.sub(r'^Subject: ?', '', res[i][1].decode()).strip()
            if name not in uids or int(uids[name]) < int(uid):
                uids[name] = uid
            all_uids.add(uid)
        clean = all_uids.difference(uids.values())
        if clean and len(clean) > 100:
            with client(SYS, readonly=False) as c:
                c.store(clean, '+FLAGS.SILENT', '\\Deleted')
                c.expunge()
        return uids

    get_map = fn_time(get_map, 'metadata_uids.get_map')

    cache_key = 'metadata'
    value = cache.get(cache_key)
    if not value or con.uidnext != value['uidnext']:
        data = {'uidnext': con.uidnext, 'map': get_map()}
        cache.set(cache_key, data)
    return cache.get(cache_key)['map']


def metadata(name, default):
    cache_key = 'metadata:%s' % name

    @using(SYS, name='_con')
    @lock.user_scope(name)
    def inner(*a, **kw):
        con = kw.pop('_con')
        val = inner.fn(*a, **kw)
        data = json.dumps(val, sort_keys=True)
        msg = message.binary(data)
        msg.add_header('Subject', name)
        uidlatest = con.append(SYS, name, None, msg.as_bytes())
        cache.set(cache_key, (uidlatest, val))
        return val

    @using(SYS)
    def get(con=None):
        uidlatest = metadata_uids(con=con).get(name)
        if not uidlatest:
            if isinstance(default, Exception):
                raise default
            return default()

        if cache.exists(cache_key):
            uid, value = cache.get(cache_key)
            if uid == uidlatest:
                return value

        def fetch():
            res = con.fetch(uidlatest, 'BODY.PEEK[1]')
            if res and res[0]:
                data = json.loads(res[0][1].decode())
                return data
            return default()

        value = fn_time(fetch, '%s.fetch' % inner.__name__)()
        cache.set(cache_key, (uidlatest, value))
        return value

    def key(name, default=None):
        return get().get(name, default)

    def wrapper(fn):
        inner_fn = ft.wraps(fn)(inner)
        inner_fn.fn = fn
        inner_fn.get = get
        inner_fn.key = key
        return inner_fn
    return wrapper


def metakey(metavalue, name, default=None):
    @lock.user_scope('%s:%s' % (metavalue.__name__, name))
    def inner(*a, **kw):
        val = inner.fn(*a, **kw)
        metavalue({name: val})
        return val

    def unset():
        metavalue({name: None})

    def get(default=default):
        value = metavalue.key(name)
        if value is not None:
            return value
        elif default and isinstance(default, Exception):
            raise default
        elif callable(default):
            return default()
        else:
            return default

    def key(name, default=None):
        return get().get(name, default)

    def wrapper(fn):
        inner_fn = ft.wraps(fn)(inner)
        inner_fn.fn = fn
        inner_fn.get = get
        inner_fn.key = key
        inner_fn.unset = unset
        return inner_fn
    return wrapper


@metadata('settings', lambda: {})
def data_settings(update=None):
    """All persistent stuff saved under the one metadata row."""
    settings = data_settings.get()
    settings.update(update)
    return settings


setting = ft.partial(metakey, data_settings)


@setting('uidnext')
def data_uidnext(value):
    return value


@setting('links', lambda: [])
def data_links(links):
    return links


@setting('drafts', lambda: {})
def data_drafts(update):
    data = data_drafts.get()
    for key, val in update.items():
        if val is None:
            data.pop(key, None)
        else:
            data[key] = val
    return data


@setting('filters', lambda: {})
def data_filters(update):
    data = data_filters.get()
    for key, val in update.items():
        if val is None:
            data.pop(key, None)
        else:
            data[key] = val
    return data


@setting('tags', lambda: {})
def data_tags(update=None):
    tags = data_tags.get()
    tags.update(update)
    return tags


@using(SYS, name=None, parent=True)
def get_tag(name, *, tags=None):
    def query(tag):
        if tag in special or tag.startswith('\\'):
            q = special.get(tag, {}).get('query')
            if q is None:
                q = ':raw %s' % tag[1:]
        else:
            q = 'tag:%s' % tag.lower()
        return ':threads %s' % q

    special = {
        '\\Flagged': {'alias': '#pinned', 'query': ':pinned'},
        '\\Draft': {'alias': '#draft', 'query': ':draft'},
        '#all': {'query': ''},
        '#inbox': {'query': ':inbox'},
        '#unread': {'query': ':unread'},
        '#sent': {'query': ':sent'},
        '#spam': {'query': ':spam'},
        '#trash': {'query': ':trash'},
    }

    if re.match(r'(?i)^[\\]?[a-z0-9/#\-.,:;!?]*$', name):
        tag = name
    else:
        tag = '#' + hashlib.md5(name.lower().encode()).hexdigest()[:8]

    if not tags:
        tags = data_tags.get()
    info = tags.get(tag)
    if info is None:
        info = {'name': name}
        if tag in special:
            info.update(name=special[tag].get('alias', tag))
        elif name != tag:
            tags[tag] = info
            data_tags({tag: info.copy()})
            log.info('## new tag %s: %r', tag, name)
    info.update(id=tag, query=query(tag))
    return info


@fn_time
@using()
@using(SYS, name=None, parent=True)
def tags_info(con=None):
    def query(tag):
        if tag.startswith('\\'):
            return tag[1:]
        return 'keyword %s' % tag

    thrids, thrs = data_threads.get()
    unread_uids = set(con.search('(UNSEEN UNKEYWORD #trash UNKEYWORD #spam)'))
    special = {
        '\\Seen', '\\Deleted', '\\Answered', '\\Flagged', '\\Draft',
        '#trash', '#spam', '#sent', '#err'
    }
    tags = {
        '#unread': {'unread': len(unread_uids)},
        '#inbox': {'pinned': 1, 'unread': 0}
    }
    tags_info = data_tags.get()
    for tag in con.flags:
        if tag in special:
            continue
        uids = con.search(query(tag))
        if not uids:
            continue
        tags.setdefault(tag, {'unread': 0})
        name = tags_info.get(tag, {}).get('name', tag)
        if not re.search('^[#.-]', name):
            continue
        unread = set()
        for uid in uids:
            thr = thrs[thrids[uid]]
            unread.update(unread_uids.intersection(thr))
        tags[tag].update(unread=len(unread), pinned=1)
    tags = {t: dict(get_tag(t), **v) for t, v in tags.items()}
    tags.update({
        t: dict(get_tag(t), **tags.get(t, {'unread': 0}))
        for t in (
            '\\Flagged', '\\Draft', '#inbox', '#all', '#unread', '#sent',
            '#spam', '#trash'
        )
    })
    return tags


@using()
def sieve_run(query, script, box=SRC, con=None):
    msgs = data_msgs.get()
    _, addrs_to = data_addresses.get()
    uids = con.search('keyword #spam')
    spamers = (msgs[uid].get('from', {}).get('addr') for uid in uids)
    spamers = [a for a in spamers if a]
    values = {
        'spamers': json.dumps(spamers or ''),
        'my_recipients': json.dumps(addrs_to.keys() or ''),
    }
    with client(box, master='SIEVE', readonly=False) as c:
        script = script % values
        return c.sieve(query, script)


def sieve_scripts(name=None):
    auto = textwrap.dedent('''
    # it runs every time when new message appears in your mailbox
    # - use %(my_recipients)s to get all your previous recipients
    # - use %(spamers)s to get all addresses from #spam
    require ["imap4flags", "variables"];

    if allof(
        not string :is "" %(spamers)s,
        address :is "from" %(spamers)s
    ) {
        addflag "#spam";
    }
    if allof(
        not string :is "" %(my_recipients)s,
        address :is "from" %(my_recipients)s
    ) {
        addflag "#personal";
    }
    ''').strip()

    manual = textwrap.dedent('''
    # this script you run manually
    require ["imap4flags"];
    ''').strip()

    data = data_filters.get()
    data['manual'] = data.get('manual', manual)
    data['auto'] = data.get('auto', auto)
    return data[name] if name else data


@metadata('uidpairs', lambda: {})
def data_uidpairs(pairs):
    return pairs


@metadata('addresses', lambda: ({}, {}))
def data_addresses(addrs_from, addrs_to):
    return [addrs_from, addrs_to]


@metadata('msgs', lambda: {})
def data_msgs(msgs):
    return msgs


@metadata('msgids', lambda: {})
def data_msgids(mids):
    return mids


def clean_threads(uids):
    thrids, thrs = data_threads.get()
    cleaned_uids = []
    cleaned = set()
    for uid in uids:
        thrid = thrids.pop(uid, None)
        thr = thrs.get(thrid)
        if uid == thrid:
            del thrs[uid]
            cleaned_uids.extend(thr)
            cleaned.add(uid)
        elif thr:
            thr.remove(uid)
    for uid in cleaned_uids:
        thrids.pop(uid, None)

    data_threads(thrids, thrs)
    log.info('## cleaned %s threads', len(cleaned))
    return cleaned_uids


def clean_msgs(uids):
    msgs = data_msgs.get()
    uidpairs = data_uidpairs.get()
    msgids = data_msgids.get()

    for uid in uids:
        msg = msgs.pop(uid)
        uidpairs.pop(msg['origin_uid'], None)
        mid = msg['msgid']
        ids = msgids[mid]
        if len(ids) == 1:
            del msgids[mid]
        else:
            ids.remove(uid)
            msgids[mid] = ids

    data_msgs(msgs)
    data_uidpairs(uidpairs)
    data_msgids(msgids)
    log.info('## cleaned %s messages' % len(uids))


@fn_time
@using(parent=True)
@using(SYS, name=None, parent=True)
@lock.user_scope('update_metadata')
def update_metadata(uids=None, clean=False, con=None):
    if clean:
        clean_msgs(uids)
        uids = clean_threads(uids)
        if not uids:
            return

    if uids == '1:*':
        msgs = {}
        addrs_from, addrs_to = {}, {}
        uidpairs = {}
        msgids = {}
    else:
        msgs = data_msgs.get()
        addrs_from, addrs_to = data_addresses.get()
        uidpairs = data_uidpairs.get()
        msgids = data_msgids.get()
        thrids, thrs = data_threads.get()

        if uids is None:
            if uidpairs:
                uidmax = max(uidpairs.values(), key=lambda v: int(v))
            else:
                uidmax = 1
            uids = '%s:*' % uidmax

    def fill_addrs(store, meta, fields):
        addrs = (meta[i] for i in fields if meta.get(i))
        addrs = sum(([a] if isinstance(a, dict) else a for a in addrs), [])
        for addr in addrs:
            a = addr['addr']
            if a not in store or store[a] != addr:
                addr['time'] = meta['date']
                store[a] = addr
            elif store[a]['time'] < meta['date']:
                store[a]['time'] = meta['date']

    res = con.fetch(imap.Uids(uids), '(FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        pattern = r'UID (\d+) FLAGS \(([^)]*)\)'
        uid, flags = re.search(pattern, res[i][0].decode()).groups()
        info = json.loads(res[i][1])
        keys = ('arrived', 'draft_id', 'msgid', 'origin_uid', 'from')
        small_info = {k: v for k, v in info.items() if k in keys}
        msgs[uid] = small_info
        uidpairs[info['origin_uid']] = uid

        # message-ids
        mid = info['msgid']
        ids = msgids.get(mid, [])
        if uid not in ids:
            ids.append(uid)
            if len(ids) > 1:
                ids = sorted(ids, key=lambda i: int(i))
            msgids[mid] = ids

        # addresses
        if {'#sent', '\\Draft'}.intersection(flags.split()):
            fill_addrs(addrs_from, info, ('from',))
            fill_addrs(addrs_to, info, ('from', 'to', 'cc'))

    data_msgs(msgs)
    data_uidpairs(uidpairs)
    data_msgids(msgids)
    data_addresses(addrs_from, addrs_to)
    update_threads(uids)
    return msgs


def pair_origin_uids(uids, uidpairs=None):
    if uidpairs is None:
        uidpairs = data_uidpairs.get()
    return tuple(uidpairs[i] for i in uids if i in uidpairs)


def pair_parsed_uids(uids, msgs=None):
    if msgs is None:
        msgs = data_msgs.get()
    return tuple(msgs[i]['origin_uid'] for i in uids if i in msgs)


@fn_time
@using(parent=True)
@using(SYS, name=None, parent=True)
@lock.user_scope('link_threads')
def link_threads(uids, unlink=False, con=None):
    thrids, thrs = data_threads.get()
    all_uids = set(sum((thrs[thrids[uid]] for uid in uids), []))

    msgs = data_msgs.get()
    links = data_links.get()

    link = set(msgs[uid]['msgid'] for uid in all_uids)
    links = [l for l in links if not link.intersection(l)]
    if not unlink:
        links.append(sorted(link))

    data_links(links)
    update_threads(all_uids)
    return sorted(all_uids)


def unlink_threads(uids):
    return link_threads(uids, unlink=True)


@using(SRC, reuse=False)
def parse_msgs(uids, con=None):
    res = con.fetch(uids.str, '(UID INTERNALDATE FLAGS BODY.PEEK[])')

    def msgs():
        for i in range(0, len(res), 2):
            line, body = res[i]
            pattern = r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)'
            uid, time, flags = re.search(pattern, line.decode()).groups()
            flags = flags.split()
            msg_obj, marks = message.parsed(body, uid, time, flags)
            flags += marks
            msg = msg_obj.as_bytes()
            yield time, ' '.join(flags), msg

    return con.multiappend(ALL, list(msgs()))


@fn_time
@lock.user_scope('parse')
@using(None)
def parse(criteria=None, con=None, **opts):
    uidnext = 1
    if criteria is None:
        saved = data_uidnext.get()
        if saved:
            uidnext = saved
            log.info('## saved: uidnext=%s', uidnext)
        else:
            uidmax = 0
            uidpairs = data_uidpairs.get()
            if uidpairs:
                uidmax = max(int(i) for i in uidpairs.keys())
            uidnext = uidmax + 1
        criteria = 'UID %s:*' % uidnext

    con.select(SRC)
    uids = con.sort('(ARRIVAL)', criteria)
    uids = [i for i in uids if i and int(i) >= uidnext]
    if not uids:
        log.info('## all parsed already')
        return

    uidnext = con.uidnext
    log.info('## new: uidnext: %s', uidnext)

    sieve_run('UID %s' % ','.join(uids), sieve_scripts('auto'))

    log.info('## criteria: %r; %s uids', criteria, len(uids))
    count = con.select(ALL)[0].decode()
    if count != '0':
        if criteria.lower() == 'all':
            puids = con.search('all')
        else:
            puids = pair_origin_uids(uids)
        if puids:
            con.select(ALL, readonly=False)
            puids = imap.Uids(puids)
            log.info('## deleting %s from %r', puids, ALL)
            con.store(puids, '+FLAGS.SILENT', '\\Deleted')
            con.expunge()
            update_metadata(puids.val, clean=True)

    uids = imap.Uids(uids, **opts)
    puids = ','.join(uids.call_async(parse_msgs, uids))
    if criteria.lower() == 'all' or count == '0':
        puids = '1:*'

    data_uidnext(uidnext)
    update_metadata(puids)


@metadata('threads', lambda: [{}, {}])
def data_threads(thrids, thrs):
    return [thrids, thrs]


@using()
@using(SYS, name=None, parent=True)
@lock.user_scope('update_threads')
def update_threads(uids, thrids=None, thrs=None, con=None):
    if thrids is None:
        thrids, thrs = data_threads.get()

    if not isinstance(uids, str):
        uids = ','.join(uids)

    orig_thrs = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % uids)
    if not orig_thrs:
        log.info('## no threads are updated')
        return

    all_uids = set(orig_thrs.all_uids)

    msgs = data_msgs.get()
    mids = data_msgids.get()

    all_links = []
    linked_uids = set()
    for link in data_links.get():
        uids = sum((mids.get(mid, []) for mid in link), [])
        if not all_uids.intersection(uids):
            continue
        all_links.append(uids)
        linked_uids.update(uids)

    if thrids:
        # clean exiting mapping
        cleaned = set()
        for uid in all_uids:
            thrs.pop(uid, None)
            thrid = thrids.pop(uid, None)
            if thrid == uid:
                cleaned.add(uid)
        log.info('## cleaned %s threads', len(cleaned))

    updated = set()
    for uids in orig_thrs:
        uids_set = set(uids)
        if uids_set.intersection(linked_uids):
            uids = (list(l) for l in all_links if uids_set.intersection(l))
            uids = sum(uids, [])
            uids = uids + [uid for uid in uids_set if uid not in uids]
        if len(uids) == 1:
            thrid = uids[0]
        else:
            uids = sorted(uids, key=lambda i: msgs[i]['arrived'])
            thrid = uids[-1]

        previous_thrids = set(thrids[i] for i in uids if thrids.get(i))
        previous_uids = (thrs[uid] for uid in previous_thrids if thrs.get(uid))
        previous_uids = sum(previous_uids, [])
        uids = set(previous_uids).union(uids)
        uids = sorted(uids, key=lambda i: msgs[i]['arrived'])
        for uid in uids:
            thrids[uid] = thrid
            if uid == thrid:
                thrs[uid] = uids
                updated.add(uid)
            elif uid in thrs:
                del thrs[uid]

    data_threads(thrids, thrs)
    log.info('## updated %s threads', len(updated))


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
        if '\\Deleted' in add:
            con.expunge()

    jobs = [
        spawn(store, con_all, uids),
        spawn(store, con_src, pair_parsed_uids(uids))
    ]
    joinall(jobs, raise_error=True)


@using(SRC)
def msgs_expunge(tag, con=None):
    uids = con.search('KEYWORD %s' % tag)
    con.copy(uids, DEL)
    parsed_uids = pair_origin_uids(uids)
    msgs_flag(parsed_uids, [], ['\\Deleted'])
    update_metadata(parsed_uids, clean=True)


@fn_time
@using(SRC, name='con_src', readonly=False)
@using(ALL, name='con_all', readonly=False)
def clean_flags(flags, con_all=None, con_src=None):
    flags = ' '.join(flags)
    con_all.store('1:*', '-FLAGS.SILENT', flags)
    con_src.store('1:*', '-FLAGS.SILENT', flags)


@fn_time
@using(SRC, name='con_src')
@using(ALL, name='con_all', readonly=False)
@using(SYS, name=None, parent=True)
def sync_flags_to_all(con_src=None, con_all=None):
    skip_flags = set(['#err'])
    for flag in con_src.flags:
        if flag in skip_flags:
            continue
        q = flag[1:] if flag.startswith('\\') else 'keyword %s' % flag
        oids = con_src.search(q)
        pairs = set(pair_origin_uids(oids))
        pids = set(con_all.search(q))
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
        if flag in ('#err'):
            continue
        q = flag[1:] if flag.startswith('\\') else 'keyword %s' % flag
        pids = con_all.search(q)
        pairs = set(pair_parsed_uids(pids))
        oids = set(con_src.search(q))
        con_src.store(pairs - oids, '+FLAGS.SILENT', flag)
        con_src.store(oids - pairs, '-FLAGS.SILENT', flag)
    rm_flags = set(con_src.flags) - set(con_all.flags)
    if rm_flags:
        con_src.store('1:*', '-FLAGS.SILENT', ' '.join(rm_flags))


@fn_time
@using(None, reuse=False)
def sync_flags(con=None, timeout=None):
    @using(SRC, name='con_src', reuse=False)
    @using(ALL, name='con_all', readonly=False, reuse=False)
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
        parsed = data_msgs.get()
        pids = pair_origin_uids(src_flags)
        res = con_all.fetch(pids, '(UID FLAGS)')
        for line in res:
            pattern = r'UID (\d+) FLAGS \(([^)]*)\)'
            uid, flags = re.search(pattern, line.decode()).groups()
            flags = set(flags.split())
            orig_flags = set(src_flags[parsed[uid]['origin_uid']].split())
            val = sorted(orig_flags - flags)
            if val:
                key = ('+FLAGS.SILENT', ' '.join(val))
                actions.setdefault(key, [])
                actions[key].append(uid)
            val = sorted(flags - orig_flags)
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
    uids = con.sort(sort, query)
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
    msgs = data_msgs.get()
    drafts = data_drafts.get()
    res = con.fetch(uids, '(UID BINARY.PEEK[2.1])')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        draft_id = msgs[uid].get('draft_id')
        if draft_id:
            draft = drafts[draft_id]
            body = '<hr>'.join(
                p for p in [html.markdown(draft['txt']), drafts.get('quoted')]
                if p
            )
        else:
            body = res[i][1].decode()
        body = html.fix_privacy(body, only_proxy=not fix_privacy)
        yield uid, body


@fn_time
@using()
@using(SYS, name=None, parent=True)
def search_thrs(query, con=None):
    q = [query] if isinstance(query, str) else query.copy()
    if len(q) > 1:
        uids = []
        thrids, thrs = data_threads.get()
        for part in q:
            if uids:
                uids = set(sum((thrs[thrids[uid]] for uid in uids), []))
                part = ' '.join([part, 'UID %s' % ','.join(uids)])
            uids = con.search(part)
    else:
        uids = con.search(q[0])
    if uids:
        msgs = data_msgs.get()
        thrids, thrs = data_threads.get()
        uids = set(thrids[uid] for uid in uids)
        uids = sorted(uids, key=lambda uid: msgs[uid]['arrived'], reverse=True)
    log.debug('## query: %r; threads: %s', query, len(uids))
    return uids


@fn_time
@using()
@using(SYS, name=None, parent=True)
def thrs_info(uids, tags=None, con=None):
    special_tag = None
    if not tags:
        pass
    elif '#trash' in tags:
        special_tag = '#trash'
    elif '#spam' in tags:
        special_tag = '#spam'

    msgs = data_msgs.get()
    thrids, all_thrs = data_threads.get()
    uids = [thrids[uid] for uid in uids if uid in thrids]
    if not uids:
        return

    all_uids = sum((all_thrs[uid] for uid in uids), [])
    all_uids = imap.Uids(all_uids)

    all_flags = {}
    res = con.fetch(all_uids, '(UID FLAGS)')
    for line in res:
        pattern = r'UID (\d+) FLAGS \(([^)]*)\)'
        uid, flags = re.search(pattern, line.decode()).groups()
        all_flags[uid] = flags.split()

    thrs = {}
    for thrid in uids:
        thr = all_thrs[thrid]
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
            info = msgs[uid]
            info['uid'] = uid
            addrs.append(info.get('from'))
            if '\\Seen' not in msg_flags:
                unseen = True
            if not msg_flags:
                continue
            if '\\Draft' in msg_flags:
                draft_id = info['draft_id']
            thr_flags.extend(msg_flags)
        if not info:
            continue
        flags = list(set(' '.join(thr_flags).split()))
        if unseen and '\\Seen' in flags:
            flags.remove('\\Seen')
        thrs[info['uid']] = {
            'thrid': thrid,
            'uids': thr,
            'draft_id': draft_id,
            'flags': flags,
            'addrs': addrs
        }

    if not thrs:
        return

    res = con.fetch(imap.Uids(thrs.keys()), 'BINARY.PEEK[1]')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        info = json.loads(res[i][1])
        thr = thrs[uid]
        info['uids'] = thr['uids']
        if thr['draft_id']:
            info['draft_id'] = thr['draft_id']
        yield thr['thrid'], info, thr['flags'], thr['addrs']


@fn_time
def del_msg(uid):
    msgs_flag([uid], [], ['\\Deleted'])
    update_metadata([uid], clean=True)


@fn_time
@using(None, readonly=False)
def new_msg(msg, flags, no_parse=False, con=None):
    uid = con.append(SRC, flags, None, msg.as_bytes())
    if no_parse:
        return uid, None
    parse()
    return uid, pair_origin_uids([uid])[0]
