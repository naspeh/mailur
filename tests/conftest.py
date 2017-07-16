import imaplib
import sys
from pathlib import Path
from subprocess import call
from unittest.mock import patch

import pytest

root = (Path(__file__).parent / '..').resolve()
sys.path.insert(0, str(root))


@pytest.fixture
def setup(gmail):
    with patch('mailur.imap.USER', 'test1'):
        yield


@pytest.fixture
def clean_users():
    call('''
    rm -rf /home/vmail/test*
    ls -l /home/vmail
    bin/users
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
    self.append = con.append
    return con


@pytest.fixture
def gmail():
    from mailur import parse

    def add_emails(con, items=None):
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
            msg = parse.binary_msg(txt).as_bytes()
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

    with patch('mailur.imap.Gmail.login', mock_gmail):
        yield gmail
