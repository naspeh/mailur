import imaplib
import re
from functools import wraps
from urllib.parse import urlencode

import requests

from . import log, conf, Timer
from .db import cursor, Account

OAUTH_URL = 'https://accounts.google.com/o/oauth2/auth'
OAUTH_URL_TOKEN = 'https://accounts.google.com/o/oauth2/token'

re_noesc = r'(?:(?:(?<=[^\\][\\])(?:\\\\)*")|[^"])*'
_client = None

# FIXME: Hack imaplib limit
imaplib._MAXLINE = 100000


class AuthError(Exception):
    pass


def auth_url(redirect_uri):
    params = {
        'client_id': conf('google_id'),
        'scope': (
            'https://mail.google.com/ '
            'https://www.googleapis.com/auth/userinfo.email'
        ),
        'login_hint': conf('email'),
        'redirect_uri': redirect_uri,
        'access_type': 'offline',
        'response_type': 'code',
        'approval_prompt': 'force',
    }
    return '?'.join([OAUTH_URL, urlencode(params)])


def auth_callback(redirect_uri, code):
    res = requests.post(OAUTH_URL_TOKEN, data={
        'code': code,
        'client_id': conf('google_id'),
        'client_secret': conf('google_secret'),
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    })
    if res.ok:
        auth = res.json()
        info = requests.get(
            'https://www.googleapis.com/oauth2/v1/userinfo',
            headers={'Authorization': 'Bearer %s' % auth['access_token']}
        ).json()
        with cursor() as cur:
            return Account.add_or_update(cur, info['email'], auth)
    raise AuthError('%s: %s' % (res.reason, res.text))


@cursor()
def auth_refresh(cur):
    refresh_token = Account.get_key(cur, conf('email'), 'refresh_token')
    if not refresh_token:
        raise AuthError('refresh_token is empty')

    res = requests.post(OAUTH_URL_TOKEN, data={
        'client_id': conf('google_id'),
        'client_secret': conf('google_secret'),
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    })
    if res.ok:
        Account.update(cur, conf('email'), res.json())
        return
    raise AuthError('%s: %s' % (res.reason, res.text))


@cursor()
def connect(cur):
    token = Account.get_key(cur, conf('email'), 'access_token')
    if token:
        def login(im, retry=False):
            header = 'user=%s\1auth=Bearer %s\1\1' % (conf('email'), token)
            try:
                im.authenticate('XOAUTH2', lambda x: header)
            except im.error as e:
                if retry:
                    raise AuthError(e)

                auth_refresh()
                login(im, True)
    elif conf('password'):
        def login(im):
            im.login(conf('email'), conf('password'))
    else:
        raise AuthError('Fill access_token or password in config')

    try:
        client = imaplib.IMAP4_SSL
        im = client('imap.gmail.com')
        im.debug = conf('imap_debug')
        login(im)
    except IOError as e:
        raise AuthError(e)
    return im


def client(func):
    @wraps(func)
    def inner(*a, **kw):
        global _client
        if not _client:
            _client = connect()

        return func(_client, *a, **kw)
    return inner


@client
def store(im, uids, key, value):
    for uid in uids:
        _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
        uid_ = data[0].decode().split(' ')[0]
        if not uid_:
            log.warn('%s is not found' % uid)
            continue
        res = im.uid('STORE', uid_, key, value)
        log.info('imap.store(%r, %r): %s', key, value, res)
    return


@client
def list_(im):
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


@client
def status(im, name, readonly=True):
    name = '"%s"' % name
    im.select(name, readonly=readonly)

    uid_next = 'UIDNEXT'
    _, data = im.status(name, '(%s)' % uid_next)
    lexer_uid = re.compile(r'[(]%s (\d+)[)]' % uid_next)
    matches = lexer_uid.search(data[0].decode())
    uid = int(matches.groups()[0])
    return uid


@client
def search(im, name):
    uid_next = status(name)
    uids, step = [], conf('imap_batch_size')
    for i in range(1, uid_next, step):
        _, data = im.uid('SEARCH', None, '(UID %d:%d)' % (i, i + step - 1))
        if data[0]:
            uids += data[0].decode().split(' ')
    return uids


@client
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

    batch_size = conf('imap_batch_size')
    if isinstance(uids[0], (tuple, list)):
        step_size, group_size = 0, conf('imap_body_maxsize')
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
        data_ = _fetch(uids_, query)
        log_('  - (%d) %d ones for %.2fs', num, len(uids_), timer.time())
        yield data_
        log_('  - %s for %.2fs', label, timer.time())


@client
def fetch(im, uids, query, label=None):
    timer = Timer()
    num = 1
    for data in fetch_batch(uids, query, label):
        for row in data:
            num += 1
            yield row
    log.info('  * Got %d %r for %.2fs', num, query, timer.time())


@client
def _fetch(im, ids, query):
    if not isinstance(query, str):
        keys = list(query)
        query = ' '.join(query)
    else:
        keys = query.split()

    status, data_ = im.uid('fetch', ','.join(ids), '(%s)' % query)
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
