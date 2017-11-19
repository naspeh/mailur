import functools as ft
import json
import os
import re
import time
from contextlib import contextmanager
from imaplib import CRLF

from gevent.lock import RLock
from gevent.pool import Pool

from . import log

DEBUG = int(os.environ.get('IMAP_DEBUG', 0))
commands = {}


class Error(Exception):
    def __repr__(self):
        return '%s.%s: %s' % (__name__, self.__class__.__name__, self.args)


def fn_desc(func, *a, **kw):
    args = ', '.join(
        [repr(i) for i in a] +
        (['**%r' % kw] if kw else [])
    )
    maxlen = 80
    if len(args) > maxlen:
        args = '%s...' % args[:maxlen]
    name = getattr(func, 'name', func.__name__)
    return '%s(%s)' % (name, args)


def fn_time(func, desc=None):
    @ft.wraps(func)
    def inner(*a, **kw):
        start = time.time()
        try:
            return func(*a, **kw)
        finally:
            d = desc if desc else fn_desc(func, *a, **kw)
            log.debug('## %s: done for %.2fs', d, time.time() - start)
    return inner


def cmd_lock(func):
    @ft.wraps(func)
    def inner(con, *a, **kw):
        with con.lock:
            return fn_time(func)(con, *a, **kw)
    return inner


def cmd_writable(func):
    @ft.wraps(func)
    def inner(con, *a, **kw):
        if con.is_readonly:
            raise ValueError('%s must be writable' % con)
        return func(con, *a, **kw)
    return inner


def cmd_error(func):
    @ft.wraps(func)
    def inner(con, *a, **kw):
        try:
            return func(con, *a, **kw)
        except con.error as e:
            raise Error(e)
    return inner


def check(res):
    typ, data = res
    if typ != 'OK':
        raise Error(typ, data)
    return data


def command(*, name=None, lock=True, writable=False, dovecot=False):
    def inner(func):
        if name:
            func.name = name
        else:
            func.name = func.__name__

        if lock:
            func = cmd_lock(func)

        func = cmd_error(func)
        commands[func] = {'writable': writable, 'dovecot': dovecot}
        return func
    return inner


class Conn:
    def username(self):
        raise NotImplementedError

    def current_box(self):
        raise NotImplementedError

    def __repr__(self):
        return str(self)

    def __str__(self):
        return '%s{%r, %r}' % (
            self.__class__.__name__, self.username, self.current_box
        )


class Ctx:
    def __init__(self, con):
        self._con = con

    def __repr__(self):
        return str(self)

    def __str__(self):
        return 'Ctx:%s' % (self._con)

    @property
    def box(self):
        return self._con.current_box

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.logout()


def client(connect, *, writable=False, dovecot=False, debug=DEBUG):
    def start():
        con = connect()
        con.debug = debug
        con.lock = RLock()
        con.new = new
        return con

    def new():
        c = start()
        if con.current_box:
            c.select(con.current_box, con.is_readonly)
        return c

    connect = fn_time(connect, '{0.__module__}.{0.__name__}'.format(connect))
    con = start()
    ctx = Ctx(con)

    for cmd, opts in commands.items():
        if not dovecot and opts['dovecot']:
            continue
        elif not writable and opts['writable']:
            continue
        setattr(ctx, cmd.name, ft.partial(cmd, con))
    return ctx


@contextmanager
def _cmd(con, name):
    tag = con._new_tag()

    def start(args):
        if isinstance(args, str):
            args = args.encode()
        return con.send(b'%s %s %s' % (tag, name.encode(), args))
    yield tag, start, lambda: con._command_complete(name, tag)


def _mdkey(key):
    if not key.startswith('/private'):
        key = '/private/%s' % key
    return key


@command(dovecot=True, writable=True)
def setmetadata(con, box, key, value):
    key = _mdkey(key)
    with _cmd(con, 'SETMETADATA') as (tag, start, complete):
        args = '%s (%s %s)' % (box, key, json.dumps(value))
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


@command(dovecot=True)
def getmetadata(con, box, key):
    key = _mdkey(key)
    with _cmd(con, 'GETMETADATA') as (tag, start, complete):
        args = '%s (%s)' % (box, key)
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


@command(dovecot=True, writable=True)
def multiappend(con, box, msgs):
    if not msgs:
        return

    with _cmd(con, 'APPEND') as (tag, start, complete):
        send = start
        for date_time, flags, msg in msgs:
            args = (' (%s) %s %s' % (flags, date_time, '{%s}' % len(msg)))
            if send == start:
                args = '%s %s' % (box, args)
            send(args.encode() + CRLF)
            send = con.send
            while con._get_response():
                if con.tagged_commands[tag]:
                    break
            con.send(msg)
        con.send(CRLF)
        return check(complete())


@command(dovecot=True)
def thread(con, *criteria):
    res = check(con.uid('THREAD', *criteria))
    return parse_thread(res[0].decode())


@command(dovecot=True)
def sort(con, fields, *criteria, charset='UTF-8'):
    return check(con.uid('SORT', fields, charset, *criteria))


@command()
def logout(con):
    return con.logout()


@command(name='list')
def xlist(con, folder='""', pattern='*'):
    return check(con.list(folder, pattern))


@command()
def select(con, box, readonly=True):
    con.current_box = box.decode() if isinstance(box, bytes) else box
    return check(con.select(box, readonly))


@command(lock=False)
def select_tag(con, tag, readonly=True):
    if isinstance(tag, str):
        tag = tag.encode()
    folder = None
    folders = xlist(con)
    for f in folders:
        if not re.search(br'^\([^)]*?%s' % re.escape(tag), f):
            continue
        folder = f.rsplit(b' "/" ', 1)[1]
        break
    if folder is None:
        raise ValueError('No folder with tag: %s\n%s' % (tag, folders))
    return select(con, folder, readonly)


@command()
def status(con, box, fields):
    box = con.current_box if box is None else box
    return check(con.status(box, fields))


@command()
def search(con, *criteria):
    return check(con.uid('SEARCH', None, *criteria))


@command(writable=True)
def append(con, box, flags, date_time, msg):
    return check(con.append(box, flags, date_time, msg))


@command(writable=True)
@cmd_writable
def expunge(con):
    return check(con.expunge())


@command(lock=False)
def fetch(con, uids, fields):
    uids = Uids(uids)
    if uids.batches:
        res = uids.call_async(fetch, con, uids, fields)
        return sum(res, [])

    desc = fn_desc(fetch, con, uids, fields)
    with con.lock:
        res = check(fn_time(con.uid, desc)('FETCH', uids.str, fields))
    if len(res) == 1 and res[0] is None:
        return []
    return res


@command(lock=False, writable=True)
@cmd_writable
def store(con, uids, cmd, flags):
    uids = Uids(uids)
    if uids.batches:
        res = uids.call_async(store, con, uids, cmd, flags)
        return sum(res, [])

    desc = fn_desc(store, con, uids, cmd, flags)
    with con.lock:
        res = check(fn_time(con.uid, desc)('STORE', uids.str, cmd, flags))
    if len(res) == 1 and res[0] is None:
        return []
    return res


class Threads(tuple):
    def __new__(cls, thrs, uids):
        obj = tuple.__new__(cls, thrs)
        obj.all_uids = uids
        return obj


def parse_thread(line):
    if isinstance(line, bytes):
        line = line.decode()

    threads = []
    all_uids = []
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
                threads.append(tuple(uids))
                all_uids.extend(uids)
                uids = []
        elif i == ' ':
            uids.append(uid)
            uid = ''
        else:
            uid += i
    return Threads(threads, all_uids)


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


class Uids:
    __slots__ = ['val', 'batches', 'threads']

    def __init__(self, uids, *, size=10000, threads=10):
        if isinstance(uids, Uids):
            uids = uids.val
        self.threads = threads
        self.val = uids
        self.batches = None
        if not self.is_str and len(uids) > size:
            self.batches = tuple(
                Uids(uids[i:i+size], size=size)
                for i in range(0, len(uids), size)
            )

    @property
    def str(self):
        if self.is_str:
            return self.val
        return ','.join(str(i) for i in self.val)

    @property
    def is_str(self):
        return isinstance(self.val, (str, bytes))

    def _call(self, fn, *args):
        num, uids = [i for i in enumerate(args) if self == i[1]][0]
        args = list(args)
        for i, few in enumerate(uids.batches or ([self] if self.val else [])):
            args[num] = few
            f = ft.partial(fn, *args)
            desc = fn_desc(fn, *args)
            yield fn_time(f, '#%s %s' % (i, desc))

    def call(self, fn, *args):
        return [f() for f in self._call(fn, *args)]

    def call_async(self, fn, *args):
        pool = Pool(self.threads)
        jobs = [pool.spawn(f) for f in self._call(fn, *args)]
        pool.join(raise_error=True)
        return (f.value for f in jobs)

    def __repr__(self):
        return str(self)

    def __str__(self):
        fmt = '"%s uids"'
        if self.is_str:
            uids = self.val
            uids = uids if isinstance(uids, str) else uids.decode()
            return uids if ':' in uids else fmt % (uids.count(',') + 1)
        return fmt % len(self.val)
