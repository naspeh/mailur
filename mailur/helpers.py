import datetime as dt
from hashlib import md5
from urllib.parse import urlencode


def get_gravatar(addr, size=75, default='identicon'):
    params = urlencode((('d', default), ('s', size)))
    hash = md5(addr.strip().lower().encode()).hexdigest()
    return '//www.gravatar.com/avatar/%s?%s' % (hash, params)


def localize_dt(value, offset=None):
    return value + dt.timedelta(hours=-(offset or 0))


def humanize_dt(val, offset=None, secs=False):
    if isinstance(val, (float, int)):
        val = dt.datetime.fromtimestamp(val)
    val = localize_dt(val, offset)
    now = localize_dt(dt.datetime.utcnow(), offset)
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M' + (':%S' if secs else '')
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)
