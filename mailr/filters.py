from email.utils import getaddresses
from hashlib import md5
from urllib.parse import urlencode

import times

__all__ = [
    'get_all', 'get_addr', 'get_addr_name', 'get_gravatar',
    'localize_dt', 'humanize_dt', 'format_dt'
]


def get_all():
    return dict((n, globals()[n]) for n in __all__)


def get_addr(addr):
    return addr and getaddresses([addr])[0][1]


def get_addr_name(addr):
    return addr and getaddresses([addr])[0][0]


def get_gravatar(addr, size=16, default='identicon'):
    params = urlencode({'s': size, 'd': default})
    gen_hash = lambda e: md5(e.strip().lower().encode()).hexdigest()
    gen_url = lambda h: '//www.gravatar.com/avatar/%s?%s' % (h, params)
    return addr and gen_url(gen_hash(get_addr(addr)))


def localize_dt(value):
    return times.to_local(value, 'Europe/Kiev')


def humanize_dt(val):
    val = localize_dt(val)
    now = localize_dt(times.now())
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M'
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)


def format_dt(value, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(value).strftime(fmt)
