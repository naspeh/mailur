import datetime as dt
import email
import json
import re
import subprocess
import sys
import time
import uuid
from email.utils import formatdate
from pathlib import Path
from unittest import mock

import pytest

root = (Path(__file__).parent / '..').resolve()
sys.path.insert(0, str(root))

users = []
test1 = None
test2 = None


@pytest.fixture(scope='session', autouse=True)
def init(request):
    for i in range(len(request.session.items)):
        users.append([
            'test1_%s' % uuid.uuid4().hex,
            'test2_%s' % uuid.uuid4().hex
        ])

    users_str = ' '.join(sum(users, []))
    subprocess.call('''
    path=/home/vmail/test
    rm -rf $path
    user="%s" home=$path append=1 bin/install-users
    systemctl restart dovecot
    sleep 1
    ''' % users_str, shell=True, cwd=root)


@pytest.fixture(autouse=True)
def setup(new_users, gm_client, patch):
    from mailur import cache

    conf = {'USER': test1}
    with patch.dict('mailur.conf', conf):
        cache.clear()

        yield


@pytest.fixture
def new_users():
    global test1, test2

    test1, test2 = users.pop()


@pytest.fixture
def load_file():
    def inner(name, charset=None):
        txt = (root / 'tests/files' / name).read_bytes()
        return txt.decode().encode(charset) if charset else txt
    return inner


@pytest.fixture
def load_email(gm_client, load_file, latest):
    def inner(name, charset=None, **opt):
        gm_client.add_emails([{'raw': load_file(name, charset=charset)}])
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


@pytest.fixture
def call():
    return mock.call


def gm_fake():
    from mailur import local

    def uid(name, *a, **kw):
        responces = getattr(gm_client, name.lower(), None)
        if responces:
            return responces.pop()
        return gm_client._uid(name, *a, **kw)

    def xlist(*a, **kw):
        responces = getattr(gm_client, 'list', None)
        if responces:
            return responces.pop()
        return 'OK', [
            b'(\\HasNoChildren \\All) "/" All',
            b'(\\HasNoChildren) "/" INBOX',
            b'(\\HasNoChildren \\Junk) "/" INBOX',
            b'(\\HasNoChildren \\Trash) "/" INBOX',
            b'(\\HasNoChildren \\Draft) "/" INBOX',
        ]

    con = local.connect(test2)

    gm_client.con = con
    gm_client._uid = con.uid
    con.uid = uid
    con.list = xlist
    return con


@pytest.fixture
def gm_client():
    from mailur import local, gmail, message

    gmail.SKIP_DRAFTS = False

    def add_emails(items=None, *, tag='\\All', fetch=True, parse=True):
        gmail.client()
        if items is None:
            items = [{}]
        gm_client.fetch = [('OK', []), ('OK', [])]
        for item in items:
            gm_client.uid += 1
            uid = gm_client.uid
            gid = item.get('gid', 100 * uid)
            raw = item.get('raw')
            if raw:
                msg = raw
                date = gm_client.time + uid
            else:
                txt = item.get('txt', '42')
                msg = message.binary(txt)

                subj = item.get('subj')
                if 'subj' not in item:
                    subj = 'Subj %s' % uid
                msg.add_header('Subject', subj)

                date = item.get('date')
                if not date:
                    date = gm_client.time + uid
                msg.add_header('Date', formatdate(date, usegmt=True))

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
                fr = item.get('from')
                if fr:
                    msg.add_header('From', fr)
                to = item.get('to')
                if to:
                    msg.add_header('To', to)

                msg = msg.as_bytes()

            arrived = dt.datetime.fromtimestamp(date)
            arrived = arrived.strftime('%d-%b-%Y %H:%M:%S %z').encode()
            flags = item.get('flags', '').encode()
            labels = item.get('labels', '').encode()
            folder = local.ALL if tag == '\\All' else local.SRC
            res = gm_client.con.append(
                folder, gmail.MAP_LABELS.get(tag), None, msg
            )
            if res[0] != 'OK':
                raise Exception(res)
            gm_client.fetch[1][1].append(
                (b'1 (X-GM-MSGID %d UID %d )' % (gid, uid))
            )
            gm_client.fetch[0][1].extend([
                (
                    b'1 (X-GM-MSGID %d X-GM-THRID %d X-GM-LABELS (%s) UID %d '
                    b'INTERNALDATE "%s" FLAGS (%s) '
                    b'BODY[] {%d}'
                    % (gid, gid, labels, uid, arrived, flags, len(msg)),
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


def _msgs(box=None, uids='1:*', *, parsed=False, raw=False, policy=None):
    from mailur import local, message

    def flags(m):
        res = re.search(r'FLAGS \(([^)]*)\)', m).group(1).split()
        if '\\Recent' in res:
            res.remove('\\Recent')
        return ' '.join(res)

    def msg(res):
        msg = {
            'uid': re.search(r'UID (\d+)', res[0].decode()).group(1),
            'flags': flags(res[0].decode()),
        }
        if parsed:
            body = email.message_from_bytes(res[1], policy=policy)
            parts = [p.get_payload() for p in body.get_payload()]
            txt = [p.get_payload() for p in parts[1]]
            msg['meta'] = json.loads(parts[0])
            msg['body'] = txt[0]
            msg['body_txt'] = txt[1] if len(txt) > 1 else None
            msg['body_end'] = parts[2] if len(parts) > 2 else None
            msg['body_full'] = body
            msg['raw'] = res[1]
        else:
            body = res[1]
            if not raw:
                body = email.message_from_bytes(res[1], policy=policy)
            msg['body'] = body

        return msg

    policy = policy if policy else message.policy
    con = local.client(box or local.ALL)
    res = con.fetch(uids, '(uid flags body[])')
    return [msg(res[i]) for i in range(0, len(res), 2)]


@pytest.fixture
def msgs():
    return _msgs


@pytest.fixture
def latest():
    def inner(box=None, *, parsed=False, raw=False, policy=None):
        return _msgs(box, '*', parsed=parsed, raw=raw, policy=policy)[0]
    return inner


@pytest.fixture
def web():
    from webtest import TestApp
    from mailur.web import app, assets, themes

    app.catchall = False

    class Wrapper(TestApp):
        def search(self, data, status=200):
            return self.post_json('/search', data, status=status).json

        def flag(self, data, status=200):
            return self.post_json('/msgs/flag', data, status=status)

        def body(self, uid, fix_privacy=True):
            data = {'uids': [uid], 'fix_privacy': fix_privacy}
            res = self.post_json('/msgs/body', data, status=200).json
            return res[uid]

    if not assets.exists():
        assets.mkdir()
        for i in themes():
            filename = 'theme-%s.css' % i
            (assets / filename).write_text('')
        for filename in ('login.js', 'index.js'):
            (assets / filename).write_text('')
    return Wrapper(app)


@pytest.fixture
def login(web):
    def inner(username=test1, password='user', tz='Asia/Singapore'):
        params = {'username': username, 'password': password, 'timezone': tz}
        web.post_json('/login', params, status=200)
        return web

    inner.user1 = test1
    inner.user2 = test2
    return inner
