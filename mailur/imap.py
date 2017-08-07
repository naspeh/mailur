import functools as ft
import json
import os
import re
from concurrent import futures
from contextlib import contextmanager
from imaplib import CRLF, IMAP4, IMAP4_SSL

USER = os.environ.get('MLR_USER', 'user')
GM_USER = os.environ.get('GM_USER')
GM_PASS = os.environ.get('GM_PASS')
IMAP_DEBUG = int(os.environ.get('IMAP_DEBUG', 1))


class Error(Exception):
    def __repr__(self):
        return '%s.%s: %s' % (__name__, self.__class__.__name__, self.args)


def check(res):
    typ, data = res
    if typ != 'OK':
        raise Error(typ, data)
    return data


def check_fn(func):
    def inner(*a, **kw):
        return check(func(*a, **kw))
    return ft.wraps(func)(inner)


def check_uid(con, name):
    return check_fn(ft.partial(con.uid, name))


class Gmail:
    def __init__(self, tag='\\All'):
        con = self.login()
        con.debug = IMAP_DEBUG
        con.recreate = ft.partial(recreate, con, self.login)

        self.logout = con.logout
        self.list = check_fn(con.list)
        self.fetch = check_uid(con, 'FETCH')
        self.select = ft.partial(select, con)
        self.status = ft.partial(status, con)
        self.search = ft.partial(search, con)

        if tag is not None:
            self.select_tag(tag)

    def select_tag(self, tag, readonly=True):
        if isinstance(tag, str):
            tag = tag.encode()
        folders = self.list()
        for f in folders:
            if not re.search(br'^\([^)]*?%s' % re.escape(tag), f):
                continue
            folder = f.rsplit(b' "/" ', 1)[1]
            break
        return self.select(folder, readonly)

    def __hash__(self):
        box = getattr(self, 'current_box', None)
        return hash((self.__class__, GM_USER, box))

    @staticmethod
    def login():
        con = IMAP4_SSL('imap.gmail.com')
        con.login(GM_USER, GM_PASS)
        return con


class Local:
    ALL = 'All'
    PARSED = 'Parsed'
    TAGS = 'Tags'

    def __init__(self, box=ALL):
        con = self.login()
        con.debug = IMAP_DEBUG
        con.recreate = ft.partial(recreate, con, self.login)

        self.append = check_fn(con.append)
        self.expunge = check_fn(con.expunge)
        self.sort = check_uid(con, 'SORT')
        self.thread = check_uid(con, 'THREAD')
        self.fetch = ft.partial(fetch, con)
        self.store = ft.partial(store, con)
        self.select = ft.partial(select, con)
        self.status = ft.partial(status, con)
        self.search = ft.partial(search, con)
        self.getmetadata = ft.partial(getmetadata, con)
        self.setmetadata = ft.partial(setmetadata, con)
        self.multiappend = ft.partial(multiappend, con)

        if box is not None:
            self.select(box)

    def __hash__(self):
        box = getattr(self, 'current_box', None)
        return hash((self.__class__, GM_USER, box))

    @staticmethod
    def login():
        con = IMAP4('localhost', 143)
        check(con.login('%s*root' % USER, 'root'))
        return con


def recreate(con, login):
    box = getattr(con, 'current_box', None)
    con = login()
    if box:
        con.select(box)
    return con


@contextmanager
def cmd(con, name):
    tag = con._new_tag()

    def start(args):
        if isinstance(args, str):
            args = args.encode()
        return con.send(b'%s %s %s' % (tag, name.encode(), args))
    yield tag, start, lambda: con._command_complete(name, tag)


def multiappend(con, msgs, box=Local.ALL):
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
    con.current_box = box
    return res


def status(con, box, fields):
    box = con.current_box if box is None else box
    return check(con.status(box, fields))


def search(con, *criteria):
    return check(con.uid('SEARCH', None, *criteria))


def fetch(con, uids, fields):
    if not isinstance(uids, (str, bytes)):
        @ft.wraps(fetch)
        def fn(uids, once=False):
            c = con if once else con.recreate()
            uids = ','.join(uids)
            return fetch(c, uids, fields)
        res = partial_uids(list(uids), fn)
        return sum(res, [])
    return check(con.uid('FETCH', uids, fields))


def store(con, uids, command, flags):
    if not isinstance(uids, (str, bytes)):
        @ft.wraps(store)
        def fn(uids, once=False):
            c = con if once else con.recreate()
            uids = ','.join(uids)
            return store(c, uids, command, flags)
        res = partial_uids(list(uids), fn)
        return sum(res, [])
    return check(con.uid('STORE', uids, command, flags))


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


def partial_uids(uids, func, size=10000, threads=10):
    if not uids:
        return []
    elif len(uids) < size:
        res = func(uids, once=True)
        return [res]

    def inner(num, uids):
        res = func(uids)
        print('## %s#%s: done' % (func.__name__, num))
        return res

    jobs = []
    with futures.ThreadPoolExecutor(threads) as pool:
        for i in range(0, len(uids), size):
            num = '%02d' % (i // size + 1)
            few = uids[i:i+size]
            jobs.append(pool.submit(inner, num, few))
            print('## %s#%s: %s uids' % (func.__name__, num, len(few)))
    return [f.result() for f in futures.as_completed(jobs)]
