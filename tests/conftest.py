import email
import re
import sys
import time
from email.utils import formatdate
from pathlib import Path
from subprocess import call
from unittest.mock import patch

import pytest

root = (Path(__file__).parent / '..').resolve()
sys.path.insert(0, str(root))


@pytest.fixture(scope='session', autouse=True)
def init():
    call('''
    rm -rf /home/vmail/test*
    bin/dovecot
    ''', shell=True, cwd=root)


@pytest.fixture(autouse=True)
def setup(gm_client):
    with patch('mailur.local.USER', 'test1'):
        yield


@pytest.fixture
def clean_users():
    call('''
    rm -rf /home/vmail/test*/mailboxes/*
    bin/users
    ''', shell=True, cwd=root)


@pytest.fixture
def load_file():
    def inner(name):
        return (root / 'tests/files' / name).read_bytes()
    return inner


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


def gm_fake():
    from mailur import local

    def uid(name, *a, **kw):
        responces = getattr(gm_client, name.lower(), None)
        if responces:
            return responces.pop()
        return gm_client._uid(name, *a, **kw)

    con = local.connect('test2')

    gm_client.con = con
    gm_client._uid = con.uid
    con.uid = uid
    return con


@pytest.fixture
def gm_client():
    from mailur import local, gmail

    def add_emails(items=None, tag='\\All', fetch=True):
        box = dict(gmail.MAP_FOLDERS, **{'\\All': local.ALL})[tag]
        gmail.client()
        if items is None:
            items = [{}]
        gm_client.fetch = [('OK', [])]
        for item in items:
            gm_client.uid += 1
            uid = gm_client.uid
            gid = 100 * uid
            raw = item.get('raw')
            if raw:
                msg = raw
            else:
                txt = item.get('txt', '42')
                msg = local.binary_msg(txt)
                msg.add_header('Message-ID', '<%s@mlr>' % uid)
                msg.add_header('Date', formatdate(gm_client.time + uid))
                in_reply_to = item.get('in_reply_to', '')
                if in_reply_to:
                    msg.add_header('In-Reply-To', in_reply_to)
                refs = item.get('refs')
                if refs:
                    msg.add_header('References', refs)
                msg = msg.as_bytes()
            flags = item.get('flags', '').encode()
            labels = item.get('labels', '').encode()
            res = gm_client.con.append(box, None, None, msg)
            if res[0] != 'OK':
                raise Exception(res)
            gm_client.fetch[0][1].extend([
                (
                    b'1 (X-GM-MSGID %d X-GM-THRID %d X-GM-LABELS (%s) UID %d '
                    b'INTERNALDATE "08-Jul-2017 09:08:30 +0000" FLAGS (%s) '
                    b'BODY[] {%d}' % (gid, gid, labels, uid, flags, len(msg)),
                    msg
                ),
                b')'
            ])

        if fetch:
            gmail.fetch_folder(tag)

    gm_client.add_emails = add_emails
    gm_client.uid = 100
    gm_client.time = time.time() - 36000

    with patch('mailur.gmail.connect', gm_fake):
        yield gm_client


def _msgs(box, uids='1:*', raw=False):
    from mailur import local

    con = local.client(box)
    res = con.fetch(uids, '(flags body[])')
    return [(
        re.search('FLAGS \(([^)]*)\)', res[i][0].decode()).group(1),
        res[i][1] if raw else email.message_from_bytes(res[i][1])
    ) for i in range(0, len(res), 2)]


@pytest.fixture
def msgs():
    return _msgs


@pytest.fixture
def latest():
    def inner(box, raw=False):
        return _msgs(box, '*', raw=raw)[0]
    return inner
