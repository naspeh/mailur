import datetime as dt
import json
import re
from email.utils import parseaddr
from hashlib import md5
from urllib.parse import urlencode

import lxml.html as lhtml


def format_addr(env, v):
    v = parseaddr(v)
    return v[0] if env('ui_use_names') else v[1]


def get_addr(v):
    return parseaddr(v)[1]


def get_gravatar(addr, size=20, default='identicon'):
    params = urlencode({'s': size, 'd': default})
    hash = md5(addr.strip().lower().encode()).hexdigest()
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


def get_preview(text, files):
    files = ', '.join(v['name'] for v in files.values())
    files = ('[%s]' % files) if files else ''
    text = ' '.join([text or '', files])
    return text[:200].strip() or '>'


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
    return htm


def hide_quote(msg, msgs, class_):
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
            if cp and cb and cp.endswith(cb):
                block.attrib['class'] = class_
                parent = block.getparent()
                toggle = lhtml.fromstring('<div class="%s-toggle"/>' % class_)
                block.attrib['class'] = class_
                parent.insert(parent.index(block), toggle)
                return lhtml.tostring(lmsg, encoding='utf8').decode()
    return msg


def get_hash(value):
    return md5(json.dumps(value).encode()).hexdigest()
