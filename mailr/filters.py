from email.utils import getaddresses
from hashlib import md5

import arrow

__all__ = [
    'get_all', 'get_addr_name', 'get_gravatar',
    'localize_dt', 'humanize_dt', 'format_dt'
]


def get_all():
    return dict((n, globals()[n]) for n in __all__)


def get_addr_name(addr):
    return addr and getaddresses([addr])[0][1].split('@')[0]


def get_gravatar(addr):
    gen_hash = lambda e: md5(e.strip().lower().encode()).hexdigest()
    gen_url = lambda h: '//www.gravatar.com/avatar/%s' % h if h else None
    return addr and gen_url(gen_hash(getaddresses([addr])[0][1]))


def localize_dt(value):
    return arrow.get(value).to('Europe/Kiev')


def humanize_dt(value):
    return localize_dt(value).humanize()


def format_dt(value, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(value).strftime(fmt)
