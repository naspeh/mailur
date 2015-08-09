import base64
import imaplib
import smtplib
from urllib.parse import urlencode

import requests

# FIXME: Hack imaplib limit
imaplib._MAXLINE = 100000

OAUTH_URL = 'https://accounts.google.com/o/oauth2/auth'
OAUTH_URL_TOKEN = 'https://accounts.google.com/o/oauth2/token'


class AuthError(Exception):
    pass


def auth_url(env, redirect_uri, email=None):
    params = {
        'client_id': env('google_id'),
        'scope': (
            'https://mail.google.com/ '
            'email '
            'profile'
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
        env.storage.set('gmail', auth)
        env.storage.set('gmail_info', info)
        env.db.commit()
        return info
    raise AuthError('%s: %s' % (res.reason, res.text))


def auth_refresh(env, email):
    refresh_token = env.storage.get('gmail').get('refresh_token')
    if not refresh_token:
        raise AuthError('refresh_token is empty')

    res = requests.post(OAUTH_URL_TOKEN, data={
        'client_id': env('google_id'),
        'client_secret': env('google_secret'),
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    })
    if res.ok:
        value = dict(env.storage.get('gmail'), **res.json())
        env.storage.set('gmail', value)
        env.db.commit()
        return
    raise AuthError('%s: %s' % (res.reason, res.text))


def xoauth2(env, email):
    token = env.storage.get('gmail').get('access_token')
    if not token:
        raise AuthError('No account for %r' % email)

    return 'user=%s\1auth=Bearer %s\1\1' % (email, token)


def imap_connect(env, email):
    def login(im, retry=False):
        header = xoauth2(env, email)
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


def smtp_connect(env, email):
    conn = smtplib.SMTP('smtp.gmail.com', 587)
    conn.set_debuglevel(env('smtp_debug'))
    conn.ehlo()
    conn.starttls()

    def send(*a, _retry=False, **kw):
        auth = xoauth2(env, email)
        auth = base64.b64encode(auth.encode()).decode()

        try:
            conn.docmd('AUTH', 'XOAUTH2 %s' % auth)
            conn.sendmail(*a, **kw)
        except OSError as e:
            if _retry:
                raise AuthError(e)
            auth_refresh(env, email)
            send(*a, _retry=True, **kw)
        finally:
            conn.close()
    return conn, send
