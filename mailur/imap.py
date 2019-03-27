import functools as ft
import inspect
import json
import re
import time
from contextlib import contextmanager
from imaplib import CRLF, Time2Internaldate

from gevent import Timeout
from gevent.lock import RLock
from gevent.pool import Pool

from . import conf, fn_desc, fn_time, log

commands = {}
pool = {}


class Error(Exception):
    def __repr__(self):
        return '%s.%s: %s' % (__name__, self.__class__.__name__, self.args)


def using(client, box, readonly=True, name='con', reuse=True, parent=False):
    @contextmanager
    def use_or_create(kw):
        if kw.get(name):
            yield
            return

        if reuse:
            key = conf['USER'], client, box
            if key not in pool:
                pool[key] = client(None)
            con = pool[key]
            parent_orig = con.parent
            if not con.parent and box:
                con.select(box, readonly)
                if parent:
                    con.parent = parent
            if name:
                kw[name] = con
            yield
            if con.parent:
                con.parent = parent_orig
            return

        with client(box, readonly=readonly) as con:
            if name:
                kw[name] = con
            yield

    def inner_gen(*a, **kw):
        with use_or_create(kw):
            yield from wrapper.fn(*a, **kw)

    def inner_fn(*a, **kw):
        with use_or_create(kw):
            return wrapper.fn(*a, **kw)

    def wrapper(fn):
        wrapper.fn = fn
        inner = inner_gen if inspect.isgeneratorfunction(fn) else inner_fn
        return ft.wraps(fn)(inner)
    return wrapper


def clean_pool(user=None):
    if user is None:
        user = conf['USER']

    for key in list(pool.keys()):
        if key[0] != user:
            continue
        con = pool.pop(key)
        con.logout()


def cmd_locked(func):
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
            func = cmd_locked(func)

        func = cmd_error(func)
        commands[func] = {'writable': writable, 'dovecot': dovecot}
        return func
    return inner


class Conn:
    def defaults(self):
        self.current_box = None
        self.flags = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        return '%s{%r, %r}' % (
            self.__class__.__name__, self.username, self.current_box
        )


class Ctx:
    def __init__(self, con):
        self._con = con
        self.parent = False

    def __repr__(self):
        return str(self)

    def __str__(self):
        return 'Ctx:%s' % (self._con)

    @property
    def username(self):
        return self._con.username

    @property
    def box(self):
        return self._con.current_box

    @property
    def is_readonly(self):
        return self._con.is_readonly

    @property
    def flags(self):
        return self._con.flags

    @property
    def uidnext(self):
        return self._con.uidnext

    @property
    def uidvalidity(self):
        return self._con.uidvalidity

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.logout()


def client(connect, *, writable=False, dovecot=False, debug=None):
    def start():
        con = connect()
        con.debug = conf['DEBUG_IMAP'] if debug is None else debug
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


def login(con, username, password):
    try:
        return check(con.login(username, password))
    except con.error as e:
        raise Error(e)


@contextmanager
def _cmd(con, name):
    tag = con._new_tag()

    def start(args):
        if isinstance(args, str):
            args = args.encode()
        return con.send(b'%s %s%s' % (tag, name.encode(), args))
    yield tag, start, lambda: con._command_complete(name, tag)


def _mdkey(key):
    if not key.startswith('/private'):
        key = '/private/%s' % key
    return key


@command(dovecot=True, writable=True)
def setmetadata(con, box, key, value):
    key = _mdkey(key)
    with _cmd(con, 'SETMETADATA') as (tag, start, complete):
        args = ' %s (%s %s)' % (box, key, json.dumps(value))
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


@command(dovecot=True)
def getmetadata(con, box, key):
    key = _mdkey(key)
    with _cmd(con, 'GETMETADATA') as (tag, start, complete):
        args = ' %s (%s)' % (box, key)
        start(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


@command(dovecot=True)
def sieve(con, criteria, script):
    script = script.strip().encode()
    criteria = criteria.encode()
    with _cmd(con, 'FILTER') as (tag, start, complete):
        args = ' SIEVE SCRIPT {%s}' % len(script)
        start(args.encode() + CRLF)
        con.send(script)
        con.send(criteria + CRLF)
        typ, data = complete()
        log.debug('## %s; %s', typ, data[0].decode())
        err = con.untagged_responses.pop('FILTER', None)
        if err:
            err = err[0][1]
            raise Error(err)
        if typ != 'OK':
            raise Error(typ, data)
        filtered = con.untagged_responses.pop('FILTERED', [])
        return filtered


def clean_recent(flags):
    if not flags:
        return flags

    if isinstance(flags, bytes):
        flags = flags.decode()
    return re.sub(r'(^| )\\Recent( |$)', ' ', flags)


def _multiappend(con, box, msgs):
    with _cmd(con, 'APPEND') as (tag, start, complete):
        send = start
        for date_time, flags, msg in msgs:
            flags = clean_recent(flags)
            if date_time is None:
                date_time = Time2Internaldate(time.time())
            args = (' (%s) %s %s' % (flags, date_time, '{%s}' % len(msg)))
            if send == start:
                args = ' %s %s' % (box, args)
            send(args.encode() + CRLF)
            send = con.send
            while con._get_response():
                bad = con.tagged_commands[tag]
                if bad:
                    raise Error(bad)
            con.send(msg)
        con.send(CRLF)
        res = check(complete())
        log.debug('## %s', res[0].decode())
        uids = con.untagged_responses.pop('APPENDUID')
        uids = uids[0].decode().split(' ', 1)[-1]
        return uids


@command(dovecot=True, writable=True, lock=False)
def multiappend(con, box, msgs, *, batch=None, threads=10):
    if not msgs:
        return

    if batch and len(msgs) > batch:
        def multiappend_inner(num, few):
            with con.new() as c:
                res = multiappend(c, box, few)
                log.debug('## #%s multiappend %s messages', num, len(few))
                return res

        pool = Pool(threads)
        jobs = [
            pool.spawn(multiappend_inner, num, msgs[i:i+batch])
            for num, i in enumerate(range(0, len(msgs), batch))
        ]
        pool.join(raise_error=True)
        return ','.join(j.value for j in jobs)

    with con.lock:
        return _multiappend(con, box, msgs)


@command(dovecot=True)
def thread(con, *criteria):
    res = check(con.uid('THREAD', *criteria))
    return parse_thread(res[0].decode() if res else '')


@command(dovecot=True)
def sort(con, fields, *criteria, charset='UTF-8'):
    res = check(con.uid('SORT', fields, charset, *criteria))
    return res[0].decode().split()


@command()
def idle(con, handler, code='EXISTS', timeout=None):
    def match():
        return con._untagged_response('OK', [None], code)

    def inner():
        res = con._get_response()
        if res:
            log.debug('## received: %r', res.decode())
        bad = con.tagged_commands[tag]
        if bad:
            raise Error(bad)
        typ, dat = match()
        if not dat[-1]:
            return
        return dat

    match()
    log.info('## start idling %s...' % con)
    with _cmd(con, 'IDLE') as (tag, start, complete):
        start(CRLF)
        while 1:
            try:
                with Timeout(timeout):
                    res = inner()
                if res:
                    handler(res)
            except Timeout:
                log.debug('## timeout reached: %ss', timeout)
                return


@command()
def logout(con, timeout=1):
    with Timeout(timeout):
        return con.logout()


@command(name='list')
def xlist(con, folder='""', pattern='*'):
    return check(con.list(folder, pattern))


@command()
def select(con, box, readonly=True):
    res = check(con.select(box, readonly))
    con.current_box = box.decode() if isinstance(box, bytes) else box
    con.flags = con.untagged_responses['FLAGS'][0].decode()[1:-1].split()
    con.uidnext = int(con.untagged_responses['UIDNEXT'][0].decode())
    con.uidvalidity = con.untagged_responses['UIDVALIDITY'][0].decode()
    return res


@command(lock=False)
def select_tag(con, tag, readonly=True, exc=True):
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
        if exc:
            raise Error('No folder with tag: %s\n%s' % (tag, folders))
        return None
    return select(con, folder, readonly)


@command()
def status(con, box, fields):
    box = con.current_box if box is None else box
    return check(con.status(box, fields))


@command()
def search(con, *criteria):
    res = check(con.uid('SEARCH', None, *criteria))
    return res[0].decode().split()


@command(writable=True)
def append(con, box, flags, date_time, msg):
    check(con.append(box, clean_recent(flags), date_time, msg))
    uidlatest = con.untagged_responses.pop('APPENDUID')
    uidlatest = uidlatest[0].decode().split(' ', 1)[-1]
    # update "uidnext" because some stuff is relying on it
    # for example metadata cache
    con.uidnext = str(int(uidlatest) + 1)
    return uidlatest


@command(writable=True)
@cmd_writable
def expunge(con):
    return check(con.expunge())


@command()
def copy(con, uids, box):
    return check(con.uid('COPY', ','.join(uids), box))


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
    if not uids:
        return []

    flags = clean_recent(flags)
    if not flags:
        return []

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
                threads.append(uids)
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

    def __init__(self, uids, *, batch=10000, threads=10):
        if isinstance(uids, Uids):
            uids = uids.val
        self.threads = threads
        self.val = uids
        self.batches = None
        if not self.is_str and len(uids) > batch:
            self.batches = tuple(
                Uids(uids[i:i+batch], batch=batch)
                for i in range(0, len(uids), batch)
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

    @fn_time
    def call_async(self, fn, *args):
        if not self.batches:
            return self.call(fn, *args)

        def get_exceptions():
            return [j.exception for j in jobs if j.exception]

        jobs = []
        pool = Pool(self.threads)
        for f in self._call(fn, *args):
            if pool.wait_available():
                if get_exceptions():
                    break
                jobs.append(pool.spawn(f))
        pool.join()

        exceptions = get_exceptions()
        if exceptions:
            raise ValueError('Exception in the pool: %s' % exceptions)
        return (f.value for f in jobs)

    def __repr__(self):
        return str(self)

    def __str__(self):
        fmt = '"%s uids"'
        if self.is_str:
            uids = self.val
            uids = uids if isinstance(uids, str) else uids.decode()
            return uids if ':' in uids else fmt % (uids.count(',') + 1)
        if len(self.val) < 5:
            # show few uids as is
            return str(self.val)
        return fmt % len(self.val)
