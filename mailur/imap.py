import functools as ft
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


class Gmail:
    ALL = '\\All'
    SPAM = '\\Junk'
    DEL = '\\Trash'

    def __init__(self, tag=ALL):
        con = self.login()
        con.debug = IMAP_DEBUG

        self.logout = con.logout
        self.list = check_fn(con.list)
        self.status = check_fn(con.status)
        self.select = ft.partial(select, con)
        self.fetch = ft.partial(fetch, con)
        self.search = ft.partial(search, con)

        if isinstance(tag, str):
            tag = tag.encode()
        folders = self.list()
        for f in folders:
            if not re.search(br'^\([^)]*?%s' % re.escape(tag), f):
                continue
            folder = f.rsplit(b' "/" ', 1)[1]
            break
        self.select(folder)
        self.current_folder = folder.decode()

    @staticmethod
    def login():
        con = IMAP4_SSL('imap.gmail.com')
        con.login(GM_USER, GM_PASS)
        return con


class Local:
    ALL = 'All'
    PARSED = 'Parsed'

    def __init__(self, box=ALL):
        con = self.login()
        con.debug = IMAP_DEBUG

        self.status = check_fn(con.status)
        self.store = check_fn(con.store)
        self.expunge = check_fn(con.expunge)
        self.select = ft.partial(select, con)
        self.fetch = ft.partial(fetch, con)
        self.search = ft.partial(search, con)
        self.getmetadata = ft.partial(getmetadata, con)
        self.setmetadata = ft.partial(setmetadata, con)
        self.multiappend = ft.partial(multiappend, con)

        if box is not None:
            self.select(box)

    @staticmethod
    def login():
        con = IMAP4('localhost', 143)
        check(con.login('%s*root' % USER, 'root'))
        return con


@contextmanager
def cmd(con, name):
    tag = con._new_tag()
    con.send(b'%s %s ' % (tag, name.encode()))

    yield tag, lambda: con._command_complete(name, tag)


def multiappend(con, msgs, box=Local.ALL):
    print('## append messages to "%s"' % box)
    with cmd(con, 'APPEND') as (tag, complete):
        con.send(box.encode())
        for time, msg in msgs:
            args = (' () %s %s' % (time, '{%s}' % len(msg))).encode()
            con.send(args + CRLF)
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


def setmetadata(con, key, value):
    key = _mdkey(key)
    with cmd(con, 'SETMETADATA') as (tag, complete):
        args = '%s (%s %s)' % (con.ALL, key, value)
        con.send(args.encode() + CRLF)
        return check(complete())


def getmetadata(con, key):
    key = _mdkey(key)
    with cmd(con, 'GETMETADATA') as (tag, complete):
        args = '%s (%s)' % (con.ALL, key)
        con.send(args.encode() + CRLF)
        typ, data = complete()
        return check(con._untagged_response(typ, data, 'METADATA'))


def select(con, box, readonly=True):
    return check(con.select(box, readonly))


def fetch(con, uids, parts):
    return check(con.uid('FETCH', uids, parts))


def search(con, *criteria):
    return check(con.uid('SEARCH', None, *criteria))
