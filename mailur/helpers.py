import datetime as dt
import base64

from gevent.pool import Pool
from geventhttpclient import HTTPClient


def fetch_avatars(hashes, size=20, default='identicon', b64=True):
    def _avatar(hash):
        if hash in cache:
            return cache[hash]
        res = http.get(
            '/avatar/{hash}?d={default}&s={size}'
            .format(hash=hash, size=size, default=default)
        )
        result = hash, res.read() if res.status_code == 200 else None
        cache[hash] = result
        return result

    if not hasattr(fetch_avatars, 'cache'):
        fetch_avatars.cache = {}
    key = (size, default)
    fetch_avatars.cache.setdefault(key, {})
    cache = fetch_avatars.cache[key]

    http = HTTPClient.from_url('https://www.gravatar.com/')
    pool = Pool(20)
    res = pool.map(_avatar, hashes)
    return [(i[0], base64.b64encode(i[1]) if b64 else i[1]) for i in res if i]


def localize_dt(val, offset=None):
    if isinstance(val, (float, int)):
        val = dt.datetime.fromtimestamp(val)
    return val + dt.timedelta(hours=-(offset or 0))


def format_dt(value, offset=None, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(value, offset).strftime(fmt)


def humanize_dt(val, offset=None, secs=False):
    val = localize_dt(val, offset)
    now = localize_dt(dt.datetime.utcnow(), offset)
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M' + (':%S' if secs else '')
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)
