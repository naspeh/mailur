import imaplib
import sys
from pathlib import Path
from subprocess import call
from unittest.mock import patch

import pytest

root = (Path(__file__).parent / '..').resolve()
sys.path.insert(0, str(root))


@pytest.fixture(scope='session')
def init():
    call('''
    rm -rf /home/vmail/test*
    bin/install
    ''', shell=True, cwd=root)


@pytest.fixture
def setup(gmail):
    with patch('mailur.imap.USER', 'test1'):
        yield


@pytest.fixture
def clean_users():
    call('''
    rm -rf /home/vmail/test*/mails/mailboxes/*
    ''', shell=True, cwd=root)


class Some(object):
    "A helper object that compares equal to everything."

    def __eq__(self, other):
        self.value = other
        return True

    def __ne__(self, other):
        self.value = other
        return False

    def __repr__(self):
        return '<ANY>'


@pytest.fixture
def some():
    return Some()


def mock_gmail(self):
    def uid(name, *a, **kw):
        responces = getattr(gmail, name.lower(), None)
        if responces:
            return responces.pop()
        return con.uid_origin(name, *a, **kw)

    con = imaplib.IMAP4('localhost', 143)
    con.login('test2*root', 'root')

    con.uid_origin = con.uid
    con.uid = uid
    con.select_origin = con.select
    con.select = lambda n, readonly: con.select_origin('All', readonly)
    self.append = con.append
    gmail.con = con
    return con


@pytest.fixture
def gmail():
    from mailur import parse, imap

    def add_emails(items=None):
        con = imap.Gmail()
        if items is None:
            items = [{}]
        gmail.fetch = [('OK', [])]
        for item in items:
            gmail.uid += 1
            uid = gmail.uid
            gid = 100 * uid
            txt = item.get('txt', '42')
            flags = item.get('flags', '').encode()
            labels = item.get('labels', '').encode()
            msg = parse.binary_msg(txt)
            msg.add_header('Message-ID', '<%s@mlr>' % uid)
            in_reply_to = item.get('in_reply_to', '')
            if in_reply_to:
                msg.add_header('In-Reply-To', in_reply_to)
            refs = item.get('refs')
            if refs:
                msg.add_header('References', refs)

            msg = msg.as_bytes()
            con.append('All', None, None, msg)
            gmail.fetch[0][1].extend([
                (
                    b'1 (X-GM-MSGID %d X-GM-THRID %d X-GM-LABELS (%s) UID %d '
                    b'INTERNALDATE "08-Jul-2017 09:08:30 +0000" FLAGS (%s) '
                    b'BODY[] {%d}' % (gid, gid, labels, uid, flags, len(msg)),
                    msg
                ),
                b')'
            ])
    gmail.add_emails = add_emails
    gmail.uid = 100
    gmail.con = None

    with patch('mailur.imap.Gmail.login', mock_gmail):
        yield gmail
        if gmail.con and not gmail.con.file.closed:
            gmail.con.logout()
