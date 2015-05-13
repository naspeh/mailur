import datetime as dt
import re
from email.utils import getaddresses
from hashlib import md5
from html.parser import HTMLParser
from urllib.parse import urlencode


__all__ = [
    'get_all', 'get_addr', 'get_addr_name', 'get_gravatar',
    'localize_dt', 'humanize_dt', 'format_dt'
]


def get_all():
    names = globals()
    return dict((n, names[n]) for n in __all__)


def get_addr(addr):
    addr = [addr] if isinstance(addr, str) else addr
    return addr and getaddresses(addr)[0][1]


def get_addr_name(addr):
    addr = [addr] if isinstance(addr, str) else addr
    return addr and getaddresses(addr)[0][0]


def get_gravatar(addr, size=20, default='identicon'):
    params = urlencode({'s': size, 'd': default})
    hash = md5(get_addr(addr).strip().lower().encode()).hexdigest()
    return '//www.gravatar.com/avatar/%s?%s' % (hash, params)


def localize_dt(env, value):
    tz_offset = env.session.get('tz_offset')
    return value + dt.timedelta(hours=-(tz_offset or 0))


def humanize_dt(env, val):
    val = localize_dt(env, val)
    now = localize_dt(env, dt.datetime.utcnow())
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M'
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)


def format_dt(env, value, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(env, value).strftime(fmt)


def get_preview(msg):
    text = re.sub('<[^>]*?>', '', msg['text'] or msg['html'] or '')
    text = HTMLParser().unescape(text)
    return text.strip() or '>'


def humanize_subj(subj):
    return subj.strip() or '(no subject)'


def is_subj_changed(msg, subj):
    index = msg['subj'].index(subj)
    if index == 0 or index and msg['subj'][:index].strip().endswith(':'):
        return False
    return True
