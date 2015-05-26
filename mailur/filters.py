import datetime as dt
import json
import re
from email.utils import getaddresses
from hashlib import md5
from urllib.parse import urlencode

import toronado
import lxml.html as lhtml


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


def get_preview(text):
    return (text or '')[:200].strip() or '>'


def is_subj_changed(subj, base):
    base = humanize_subj(base, None, None)
    subj = humanize_subj(subj, base, None)
    return subj != base


def humanize_subj(subj, base=None, empty='(no subject)'):
    base = base and humanize_subj(base, None, None)
    subj = subj and subj.strip()
    pattern = r'(?i)^(\w{2,3}(\[\d*\])?:\ ?)+' + (
        '(?=%s)' % re.escape(base) if base else ''
    )
    subj = subj and re.sub(pattern, '', subj)
    return subj or empty


def humanize_html(htm, parents=None, class_='email-quote'):
    htm = re.sub(r'(<br[ ]?[/]?>\s*)$', '', htm).strip()
    if htm and parents:
        htm = hide_quote(htm, parents, class_)
    if htm:
        htm = toronado.from_string(htm).decode()
    return htm


def hide_quote(msg, msgs, class_):
    # TODO: need reworking
    if not msg or not msgs:
        return msg

    def clean(v):
        v = re.sub('[\s]+', '', v.text_content())
        return v.rstrip()

    lmsg = lhtml.fromstring(msg)
    for parent in msgs:
        if not parent:
            continue
        cp = clean(lhtml.fromstring(parent))
        for block in lmsg.xpath('//blockquote'):
            cb = clean(block)
            if cp and cb and (cp.startswith(cb) or cp.endswith(cb)):
                block.attrib['class'] = class_
                parent = block.getparent()
                switch = lhtml.fromstring('<div class="%s-switch"/>' % class_)
                block.attrib['class'] = class_
                parent.insert(parent.index(block), switch)
                return lhtml.tostring(lmsg, encoding='utf8').decode()
    return msg


def get_hash(value):
    return md5(json.dumps(value).encode()).hexdigest()
