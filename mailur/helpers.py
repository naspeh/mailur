import datetime as dt

ISO = '%Y-%m-%dT%H:%M:%S.%f%z'


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def to_iso(val):
    txt = dt.datetime.strftime(val, ISO)
    if val.tzinfo is None:
        txt += '+0000'
    return txt


def to_dt(val):
    return dt.datetime.strptime(val, ISO)


def localize_dt(value, offset=None):
    return value + dt.timedelta(hours=-(offset or 0))


def humanize_dt(val, offset=None, secs=False):
    if isinstance(val, str):
        val = to_dt(val)
    val = localize_dt(val, offset)
    now = localize_dt(utcnow(), offset)
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M' + (':%S' if secs else '')
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)
