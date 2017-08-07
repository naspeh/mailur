import imaplib
import os

from . import imap

USER = os.environ.get('GM_USER')
PASS = os.environ.get('GM_PASS')


def connect():
    con = imaplib.IMAP4_SSL('imap.gmail.com')
    imap.check(con.login(USER, PASS))
    return con


def client(tag='\\All'):
    class Gmail:
        pass

    ctx = Gmail()
    imap.client_readonly(ctx, connect)

    if tag:
        ctx.select_tag(tag)
    return ctx
