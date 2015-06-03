import functools as ft
import imaplib
import re
from urllib.parse import urlencode

import requests

from . import log
from .helpers import Timer

OAUTH_URL = 'https://accounts.google.com/o/oauth2/auth'
OAUTH_URL_TOKEN = 'https://accounts.google.com/o/oauth2/token'

re_noesc = r'(?:(?:(?<=[^\\][\\])(?:\\\\)*")|[^"])*'

# FIXME: Hack imaplib limit
imaplib._MAXLINE = 100000


class Error(Exception):
    def __str__(self):
        return '%s.%s: %s' % (__name__, self.__class__.__name__, self.args)


class NoError(Error):
    pass


class AuthError(Error):
    pass


def auth_url(env, redirect_uri, email=None):
    params = {
        'client_id': env('google_id'),
        'scope': (
            'https://mail.google.com/ '
            'https://www.googleapis.com/auth/userinfo.email'
        ),
        'login_hint': email,
        'redirect_uri': redirect_uri,
        'access_type': 'offline',
        'response_type': 'code',
        'approval_prompt': 'force',
    }
    return '?'.join([OAUTH_URL, urlencode(params)])


def auth_callback(env, redirect_uri, code):
    res = requests.post(OAUTH_URL_TOKEN, data={
        'code': code,
        'client_id': env('google_id'),
        'client_secret': env('google_secret'),
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    })
    if res.ok:
        auth = res.json()
        info = requests.get(
            'https://www.googleapis.com/oauth2/v1/userinfo',
            headers={'Authorization': 'Bearer %s' % auth['access_token']}
        ).json()
        env.accounts.add_or_update(info['email'], auth)
        env.db.commit()
        return
    raise AuthError('%s: %s' % (res.reason, res.text))


def auth_refresh(env, email):
    refresh_token = env.accounts.get_data(email).get('refresh_token')
    if not refresh_token:
        raise AuthError('refresh_token is empty')

    res = requests.post(OAUTH_URL_TOKEN, data={
        'client_id': env('google_id'),
        'client_secret': env('google_secret'),
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    })
    if res.ok:
        env.accounts.update(email, res.json())
        env.db.commit()
        return
    raise AuthError('%s: %s' % (res.reason, res.text))


class Client:
    NoError = NoError

    def __init__(self, env, email):
        im = connect(env, email)

        im.list = self.wraps(im.list)
        im.select = self.wraps(im.select)
        im.status = self.wraps(im.status)
        im.uid = self.wraps(im.uid)

        self.folders = ft.partial(folders, im)
        self.select = ft.partial(select, im)
        self.status = ft.partial(status, im)
        self.search = ft.partial(search, im)
        self.fetch_batch = ft.partial(fetch_batch, im)
        self.fetch = ft.partial(fetch, im)

        self.uid = im.uid

    def wraps(self, func):
        def inner(*a, **kw):
            ok, res = func(*a, **kw)
            if ok == 'NO':
                raise NoError(res)
            return ok, res
        return ft.wraps(func)(inner)


def connect(env, email):
    def login(im, retry=False):
        token = env.accounts.get_data(email).get('access_token')
        if not token:
            raise AuthError('No account for %r' % email)

        header = 'user=%s\1auth=Bearer %s\1\1' % (email, token)
        try:
            im.authenticate('XOAUTH2', lambda x: header)
        except im.error as e:
            if retry:
                raise AuthError(e)

            auth_refresh(env, email)
            login(im, True)

    try:
        client = imaplib.IMAP4_SSL
        im = client('imap.gmail.com')
        im.debug = env('imap_debug')
        im.conf_batch_size = env('imap_batch_size')
        im.conf_body_maxsize = env('imap_body_maxsize')

        login(im)
    except IOError as e:
        raise AuthError(e)
    return im


def folders(im):
    _, data = im.list()

    re_line = r'^[(]([^)]+)[)] "([^"]+)" "(%s)"$' % re_noesc
    lexer_line = re.compile(re_line)
    rows = []
    for line in data:
        matches = lexer_line.match(line.decode())
        row = matches.groups()
        row = tuple(row[0].split()), row[1], row[2]
        rows.append(row)
    return rows


def select(im, name, readonly=True):
    return im.select('"%s"' % name, readonly=readonly)


def status(im, name):
    uid_next = 'UIDNEXT'
    _, data = im.status('"%s"' % name, '(%s)' % uid_next)
    lexer_uid = re.compile(r'[(]%s (\d+)[)]' % uid_next)
    matches = lexer_uid.search(data[0].decode())
    uid = int(matches.groups()[0])
    return uid


def search(im, name):
    uid_next = status(im, name)
    uids, step = [], im.conf_batch_size
    for i in range(1, uid_next, step):
        _, data = im.uid('SEARCH', None, '(UID %d:%d)' % (i, i + step - 1))
        if data[0]:
            uids += data[0].decode().split(' ')
    return uids


def fetch_batch(im, uids, query, label=None):
    '''Fetch data from IMAP server

    Args:
        im: IMAP instance
        uids: a sequence of UID, it uses BATCH_SIZE for spliting to steps
              or sequence of (UID, BODY.SIZE), it uses BODY_MAXSIZE
        query: fetch query

    Kargs:
        label: label for logging

    Return:
        generator of batch data
    '''
    if not uids:
        return

    batch_size = im.conf_batch_size
    if isinstance(uids[0], (tuple, list)):
        step_size, group_size = 0, im.conf_body_maxsize
        step_uids, group_uids = [], []
        for uid, size in uids:
            if step_uids and step_size + size > group_size:
                group_uids.append(step_uids)
                step_uids, step_size = [], 0
            else:
                step_uids.append(uid)
                step_size += size
        if step_uids:
            group_uids.append(step_uids)
        steps = group_uids
    else:
        steps = range(0, len(uids), batch_size)
        steps = [uids[i: i + batch_size] for i in steps]

    log_ = log.info if label else (lambda *a, **kw: None)
    log_('  * Fetch (%d) %d %r...', len(steps), len(uids), query)

    timer = Timer()
    for num, uids_ in enumerate(steps, 1):
        if not uids_:
            continue
        data_ = _fetch(im, uids_, query)
        log_('  - (%d) %d ones for %.2fs', num, len(uids_), timer.time())
        yield data_
        log_('  - %s for %.2fs', label, timer.time())


def fetch(im, uids, query, label=None):
    timer = Timer()
    num = 1
    for data in fetch_batch(im, uids, query, label):
        for row in data:
            num += 1
            yield row
    log.info('  * Got %d %r for %.2fs', num, query, timer.time())


def _fetch(im, ids, query):
    if not isinstance(query, str):
        keys = list(query)
        query = ' '.join(query)
    else:
        keys = query.split()

    _, data_ = im.uid('fetch', ','.join(ids), '(%s)' % query)
    data = iter(data_)
    if 'UID' not in keys:
        keys.append('UID')

    re_keys = r'|'.join([re.escape(k) for k in keys])
    re_list = r'("(%s)"|[^ )"]+)' % re_noesc
    lexer_list = re.compile(re_list)
    lexer_line = re.compile(
        r'(%s) ((\d+)|({\d+})|"([^"]+)"|([(]( ?%s ?)*[)]))'
        % (re_keys, re_list)
    )

    def parse(item, row):
        if isinstance(item, tuple):
            line = item[0]
        else:
            line = item
        matches = lexer_line.findall(line.decode())
        if matches:
            for match in matches:
                key, value = match[0:2]
                if match[2]:
                    row[key] = int(value)
                elif match[3]:
                    row[key] = item[1]
                    row = parse(next(data), row)
                elif match[4]:
                    row[key] = value
                elif match[5]:
                    value_ = value[1:-1]
                    value_ = lexer_list.findall(value_)
                    value_ = [
                        re.sub(r'\\(.)', r'\1', v[1]) if v[1] else v[0]
                        for v in value_
                    ]
                    row[key] = value_
        return row

    rows = (parse(next(data), {}) for i in range(len(ids)))
    rows = ((str(row['UID']), row) for row in rows)
    return rows
