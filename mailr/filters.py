import datetime as dt
from email.utils import getaddresses
from hashlib import md5
from urllib.parse import urlencode

from jinja2 import contextfilter


__all__ = [
    'get_all', 'get_addr', 'get_addr_name', 'get_gravatar',
    'localize_dt', 'humanize_dt', 'format_dt'
]


def get_all():
    return dict((n, globals()[n]) for n in __all__)


def get_addr(addr):
    addr = [addr] if isinstance(addr, str) else addr
    return addr and getaddresses(addr)[0][1]


def get_addr_name(addr):
    return addr and getaddresses([addr])[0][0]


def get_gravatar(addr, size=16, default='identicon'):
    params = urlencode({'s': size, 'd': default})
    gen_hash = lambda e: md5(e.strip().lower().encode()).hexdigest()
    gen_url = lambda h: '//www.gravatar.com/avatar/%s?%s' % (h, params)
    return addr and gen_url(gen_hash(get_addr(addr)))


@contextfilter
def localize_dt(ctx, value):
    tz_offset = ctx.get('env').session['tz_offset']
    return value + dt.timedelta(hours=-(tz_offset or 0))


@contextfilter
def humanize_dt(ctx, val):
    val = localize_dt(ctx, val)
    now = localize_dt(ctx, dt.datetime.utcnow())
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M'
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)


@contextfilter
def format_dt(ctx, value, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(ctx, value).strftime(fmt)
