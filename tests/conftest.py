import email
import json
import re
import sys
import time
from email.utils import formatdate
from pathlib import Path
from subprocess import call
from unittest import mock

import pytest

root = (Path(__file__).parent / '..').resolve()
sys.path.insert(0, str(root))


@pytest.fixture(scope='session', autouse=True)
def init():
    call('''
    bin/dovecot
    sleep 2
    ''', shell=True, cwd=root)


@pytest.fixture(autouse=True)
def setup(gm_client):
    from mailur import local

    with mock.patch('mailur.local.USER', 'test1'):
        local.uid_pairs.cache_clear()
        local.msgids.cache_clear()
        local.saved_tags.cache_clear()

        yield


@pytest.fixture
def clean_users():
    call('''
    rm -rf /home/vmail/test*
    bin/users
    ''', shell=True, cwd=root)


@pytest.fixture
def load_file():
    def inner(name):
        return (root / 'tests/files' / name).read_bytes()
    return inner


@pytest.fixture
def load_email(gm_client, load_file, latest):
    def inner(name, **opt):
        gm_client.add_emails([{'raw': load_file(name)}])
        return latest(**opt)
    return inner


class Some(object):
    "A helper object that compares equal to everything."

    def __eq__(self, other):
        self.value = other
        return True

    def __ne__(self, other):
        self.value = other
        return False

    def __getitem__(self, name):
        return self.value[name]

    def __repr__(self):
        return '<ANY>'


@pytest.fixture
def some():
    return Some()


@pytest.fixture
def raises():
    return pytest.raises


@pytest.fixture
def patch():
    return mock.patch


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
    from mailur import local, gmail, message

    def add_emails(items=None, *, tag='\\All', fetch=True, parse=True):
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
                msg = message.binary(txt)

                subj = item.get('subj')
                if not subj:
                    subj = 'Subj %s' % uid
                msg.add_header('Subject', subj)

                date = item.get('date')
                if not date:
                    date = gm_client.time + uid
                msg.add_header('Date', formatdate(date))

                mid = item.get('mid')
                if not mid:
                    mid = '<%s@mlr>' % uid
                msg.add_header('Message-ID', mid)

                in_reply_to = item.get('in_reply_to')
                if in_reply_to:
                    msg.add_header('In-Reply-To', in_reply_to)
                refs = item.get('refs')
                if refs:
                    msg.add_header('References', refs)

                msg = msg.as_bytes()
            flags = item.get('flags', '').encode()
            labels = item.get('labels', '').encode()
            res = gm_client.con.append(
                local.ALL, gmail.MAP_LABELS.get(tag), None, msg
            )
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
        if parse:
            local.parse()

    gm_client.add_emails = add_emails
    gm_client.uid = 100
    gm_client.time = time.time() - 36000

    with mock.patch('mailur.gmail.connect', gm_fake):
        yield gm_client


def _msgs(box=None, uids='1:*', *, parsed=False, raw=False):
    from mailur import local

    def flags(m):
        res = re.search('FLAGS \(([^)]*)\)', m).group(1).split()
        if '\\Recent' in res:
            res.remove('\\Recent')
        return ' '.join(res)

    def msg(res):
        msg = {
            'uid': re.search('UID (\d+)', res[0].decode()).group(1),
            'flags': flags(res[0].decode()),
            'body': res[1] if raw else email.message_from_bytes(res[1])
        }
        if parsed:
            parts = email.message_from_bytes(res[1]).get_payload()
            msg['meta'] = json.loads(parts[0].get_payload())
            msg['body'] = parts[1].get_payload()

        return msg

    con = local.client(box or local.ALL)
    res = con.fetch(uids, '(uid flags body[])')
    return [msg(res[i]) for i in range(0, len(res), 2)]


@pytest.fixture
def msgs():
    return _msgs


@pytest.fixture
def latest():
    def inner(box=None, *, parsed=False, raw=False):
        return _msgs(box, '*', parsed=parsed, raw=raw)[0]
    return inner


@pytest.fixture
def web():
    from webtest import TestApp
    from mailur.web import app, assets, themes

    app.catchall = False

    if not assets.exists():
        assets.mkdir()
        for i in themes():
            filename = 'theme-%s.css' % i
            (assets / filename).write_text('')
        for filename in ('login.js', 'index.js'):
            (assets / filename).write_text('')
    return TestApp(app)


@pytest.fixture
def login(web):
    def inner(username='test1', password='user', tz='Asia/Singapore'):
        params = {'username': username, 'password': password, 'timezone': tz}
        web.post_json('/login', params, status=200)
        return web
    return inner
