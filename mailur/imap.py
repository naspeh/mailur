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


def func_desc(func, *a, **kw):
    args = ', '.join(
        [repr(i) for i in a] +
        (['**%r' % kw] if kw else [])
    )
    maxlen = 80
    if len(args) > maxlen:
        args = '%s...' % args[:maxlen]
    return '%s(%s)' % (func.__name__, args)


@contextmanager
def log_time(func, *a, **kw):
    start = time.time()
    yield
    desc = func_desc(func, *a, **kw)
    log.info('## %s: done for %.2fs', desc, time.time() - start)


def check(res):
    typ, data = res
    if typ != 'OK':
        raise Error(typ, data)
    return data


def lock_fn(func):
    @ft.wraps(func)
    def inner(con, *a, **kw):
        with con.lock:
            with log_time(func, *a, **kw):
                return func(con, *a, **kw)
    return inner


def client_readonly(ctx, connect, debug=IMAP_DEBUG):
    con = connect()
    con.debug = debug
    con.lock = threading.RLock()

    ctx.logout = con.logout
    ctx.list = ft.partial(list_folders, con)
    ctx.fetch = ft.partial(fetch, con)
    ctx.status = ft.partial(status, con)
    ctx.search = ft.partial(search, con)
    ctx.select = ft.partial(select, con)
    ctx.select_tag = ft.partial(select_tag, con)
    ctx.box = lambda: getattr(con, 'current_box', None)
    ctx.str = lambda: '%s[%r]' % (ctx.__class__.__name__, ctx.box())
    return con


def client_full(ctx, connect, debug=IMAP_DEBUG):
    con = client_readonly(ctx, connect, debug=debug)
    ctx.append = ft.partial(append, con)
    ctx.expunge = ft.partial(expunge, con)
    ctx.sort = ft.partial(sort, con)
    ctx.thread = ft.partial(thread, con)
    ctx.store = ft.partial(store, con)
    ctx.getmetadata = ft.partial(getmetadata, con)
    ctx.setmetadata = ft.partial(setmetadata, con)
    ctx.multiappend = ft.partial(multiappend, con)


@contextmanager
def cmd(con, name):
    tag = con._new_tag()

    def start(args):
        if isinstance(args, str):
            args = args.encode()
        return con.send(b'%s %s %s' % (tag, name.encode(), args))
    yield tag, start, lambda: con._command_complete(name, tag)


@lock_fn
def multiappend(con, box, msgs):
    if not msgs:
        return

    with cmd(con, 'APPEND') as (tag, start, complete):
        send = start
        for date_time, flags, msg in msgs:
            args = (' (%s) %s %s' % (flags, date_time, '{%s}' % len(msg)))
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


@lock_fn
def setmetadata(con, box, key, value):
    key = _mdkey(key)
    with cmd(con, 'SETMETADATA') as (tag, start, complete):
        args = '%s (%s %s)' % (box, key, json.dumps(value))
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


@lock_fn
def getmetadata(con, box, key):
    key = _mdkey(key)
    with cmd(con, 'GETMETADATA') as (tag, start, complete):
        args = '%s (%s)' % (box, key)
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


@lock_fn
def list_folders(con, directory='""', pattern='*'):
    return check(con.list(directory, pattern))


@lock_fn
def append(con, box, flags, date_time, msg):
    return check(con.append(box, flags, date_time, msg))


@lock_fn
def expunge(con):
    return check(con.expunge())


@lock_fn
def select(con, box, readonly=True):
    res = check(con.select(box, readonly))
    con.current_box = box.decode() if isinstance(box, bytes) else box
    return res


def select_tag(con, tag, readonly=True):
    if isinstance(tag, str):
        tag = tag.encode()
    folders = list_folders(con)
    for f in folders:
        if not re.search(br'^\([^)]*?%s' % re.escape(tag), f):
            continue
        folder = f.rsplit(b' "/" ', 1)[1]
        break
    return select(con, folder, readonly)


@lock_fn
def status(con, box, fields):
    box = con.current_box if box is None else box
    return check(con.status(box, fields))


@lock_fn
def search(con, *criteria):
    return check(con.uid('SEARCH', None, *criteria))


@lock_fn
def thread(con, *criteria):
    res = check(con.uid('THREAD', *criteria))
    return parse_thread(res[0].decode())


@lock_fn
def sort(con, sort_criteria, *search_criteria, charset='UTF-8'):
    return check(con.uid('SORT', sort_criteria, charset, *search_criteria))


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
    inner.desc = func_desc(func, 'uids', *a, **kw)
    return inner


def partial_uids(delayed, size=5000, threads=10):
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
