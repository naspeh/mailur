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
    call('''
    rm -rf /home/vmail/test*
    ls -l /home/vmail
    bin/users
    ''', shell=True, cwd=root)
    with patch('mailur.parse.USER', 'test1'):
        yield


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


def mock_gmail():
    def uid(name, *a, **kw):
        responces = getattr(gmail, name.lower(), None)
        if responces:
            return responces.pop()
        return con.uid_origin(name, *a, **kw)

    con = imaplib.IMAP4('localhost', 143)
    con.login('test2*root', 'root')

    con.uid_origin = con.uid
    con.uid = uid
    return con


@pytest.fixture
def gmail():
    with patch('mailur.parse.login_gmail', mock_gmail):
        yield gmail
