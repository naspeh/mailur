import imaplib
import os

from . import imap

USER = os.environ.get('MLR_USER', 'user')

ALL = 'All'
PARSED = 'Parsed'
TAGS = 'Tags'


def connect():
    con = imaplib.IMAP4('localhost', 143)
    imap.check(con.login('%s*root' % USER, 'root'))
    return con


def client(box=PARSED):
    class Local:
        pass

    ctx = Local()
    imap.client_full(ctx, connect)

    if box:
        ctx.select(box)
    return ctx
