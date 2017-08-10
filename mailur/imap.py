import functools as ft
import json
import os
import re
import time
import threading
from concurrent import futures
from contextlib import contextmanager
from imaplib import CRLF

from . import log

IMAP_DEBUG = int(os.environ.get('IMAP_DEBUG', 1))


class Error(Exception):
    def __repr__(self):
        return '%s.%s: %s' % (__name__, self.__class__.__name__, self.args)


def check(res):
    typ, data = res
    if typ != 'OK':
        raise Error(typ, data)
    return data


def check_fn(con, func, *a, **kw):
    if a or kw:
        func = ft.partial(func, *a, **kw)

    @ft.wraps(func)
    def inner(*a, **kw):
        with con.lock:
            return check(func(*a, **kw))
    return inner


def lock_fn(con, func):
    func = ft.partial(func, con)

    @ft.wraps(func)
    def inner(*a, **kw):
        with con.lock:
            return func(*a, **kw)
    return inner


def client_readonly(ctx, connect, debug=IMAP_DEBUG):
    con = connect()
    con.debug = debug
    con.lock = threading.RLock()

    ctx.logout = con.logout
    ctx.list = check_fn(con, con.list)
    ctx.fetch = lock_fn(con, fetch)
    ctx.status = lock_fn(con, status)
    ctx.search = lock_fn(con, search)
    ctx.select = lock_fn(con, select)
    ctx.select_tag = lock_fn(con, select_tag)
    ctx.box = lambda: getattr(con, 'current_box', None)
    ctx.str = lambda: '%s[%r]' % (ctx.__class__.__name__, ctx.box())
    return con


def client_full(ctx, connect, debug=IMAP_DEBUG):
    con = client_readonly(ctx, connect, debug=debug)
    ctx.append = check_fn(con, con.append)
    ctx.expunge = check_fn(con, con.expunge)
    ctx.sort = check_fn(con, con.uid, 'SORT')
    ctx.thread = lock_fn(con, thread)
    ctx.fetch = ft.partial(fetch, con)
    ctx.store = ft.partial(store, con)
    ctx.getmetadata = lock_fn(con, getmetadata)
    ctx.setmetadata = lock_fn(con, setmetadata)
    ctx.multiappend = lock_fn(con, multiappend)


@contextmanager
def cmd(con, name):
    tag = con._new_tag()

    def start(args):
        if isinstance(args, str):
            args = args.encode()
        return con.send(b'%s %s %s' % (tag, name.encode(), args))
    yield tag, start, lambda: con._command_complete(name, tag)


def multiappend(con, box, msgs):
    if not msgs:
        return

    with cmd(con, 'APPEND') as (tag, start, complete):
        send = start
        for time, flags, msg in msgs:
            args = (' (%s) %s %s' % (flags, time, '{%s}' % len(msg)))
            if send == start:
                args = '%s %s' % (box, args)
            send(args.encode() + CRLF)
            send = con.send
            while con._get_response():
                if con.tagged_commands[tag]:   # BAD/NO?
                    return tag
            con.send(msg)
        con.send(CRLF)
        return check(complete())


def _mdkey(key):
    if not key.startswith('/private'):
        key = '/private/%s' % key
    return key


def setmetadata(con, box, key, value):
    key = _mdkey(key)
    with cmd(con, 'SETMETADATA') as (tag, start, complete):
        args = '%s (%s %s)' % (box, key, json.dumps(value))
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


def getmetadata(con, box, key):
    key = _mdkey(key)
    with cmd(con, 'GETMETADATA') as (tag, start, complete):
        args = '%s (%s)' % (box, key)
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


def select(con, box, readonly=True):
    res = check(con.select(box, readonly))
    con.current_box = box.decode() if isinstance(box, bytes) else box
    return res


def select_tag(con, tag, readonly=True):
    if isinstance(tag, str):
        tag = tag.encode()
    folders = check(con.list())
    for f in folders:
        if not re.search(br'^\([^)]*?%s' % re.escape(tag), f):
            continue
        folder = f.rsplit(b' "/" ', 1)[1]
        break
    return select(con, folder, readonly)


def status(con, box, fields):
    box = con.current_box if box is None else box
    return check(con.status(box, fields))


def search(con, *criteria):
    return check(con.uid('SEARCH', None, *criteria))


def thread(con, *criteria):
    res = check(con.uid('THREAD', *criteria))
    return parse_thread(res[0].decode())


def fetch(con, uids, fields):
    if not isinstance(uids, (str, bytes)):
        @ft.wraps(fetch)
        def inner(uids, *args):
            return fetch(con, ','.join(uids), *args)

        res = partial_uids(delayed_uids(inner, uids, fields))
        res = ([] if len(i) == 1 and i[0] is None else i for i in res)
        return sum(res, [])

    with con.lock:
        return check(con.uid('FETCH', uids, fields))


def store(con, uids, cmd, flags):
    if not isinstance(uids, (str, bytes)):
        @ft.wraps(store)
        def inner(uids, *args):
            return store(con, ','.join(uids), *args)

        res = partial_uids(delayed_uids(inner, uids, cmd, flags))
        res = ([] if len(i) == 1 and i[0] is None else i for i in res)
        return sum(res, [])

    with con.lock:
        return check(con.uid('STORE', uids, cmd, flags))


def parse_thread(line):
    if isinstance(line, bytes):
        line = line.decode()

    threads = []
    uids = []
    uid = ''
    opening = 0
    for i in line:
        if i == '(':
            opening += 1
        elif i == ')':
            if uid:
                uids.append(uid)
                uid = ''

            opening -= 1
            if opening == 0:
                threads.append(uids)
                uids = []
        elif i == ' ':
            uids.append(uid)
            uid = ''
        else:
            uid += i
    return threads


def pack_uids(uids):
    uids = sorted(int(i) for i in uids)
    result = ''
    for i, uid in enumerate(uids):
        if i == 0:
            result += str(uid)
        elif uid - uids[i-1] == 1:
            if len(uids) == (i + 1):
                if not result.endswith(':'):
                    result += ':'
                result += str(uid)
            elif result.endswith(':'):
                pass
            else:
                result += ':'
        elif result.endswith(':'):
            result += '%d,%d' % (uids[i-1], uid)
        else:
            result += ',%s' % uid
    return result


def delayed_uids(func, uids, *a, **kw):
    @ft.wraps(func)
    def inner(uids, num=None):
        num = '%s#' % num if num else ''
        log.info('## %s%s: %s uids', num, inner.desc, len(uids))
        start = time.time()
        try:
            res = func(uids, *a, **kw)
            log.info(
                '## %s%s: done for %.2fs',
                num, inner.desc, time.time() - start
            )
        except Exception as e:
            log.exception('## %s%s: %r' % (num, inner.desc, e))
            raise
        return res

    inner.uids = list(uids)
    inner.desc = '%s(%s)' % (func.__name__, ', '.join(
        ['uids'] +
        [repr(i) for i in a] +
        (['**%r'] % kw if kw else [])
    ))
    return inner


def partial_uids(delayed, size=5000, threads=None):
    uids = delayed.uids
    if not uids:
        return []
    elif len(uids) <= size:
        return [delayed(uids)]

    jobs = []
    with futures.ThreadPoolExecutor(threads) as pool:
        for i in range(0, len(uids), size):
            num = '%02d' % (i // size + 1)
            few = uids[i:i+size]
            jobs.append(pool.submit(delayed, few, num))
    return [f.result() for f in jobs]
