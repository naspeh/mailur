import datetime as dt
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


def get_preview(msg):
    return (msg['text']or '')[:200].strip() or '>'


def is_subj_changed(msg, subj):
    index = msg['subj'].find(subj)
    if index == 0 or index and msg['subj'][:index].strip().endswith(':'):
        return False
    return True


def humanize_subj(subj):
    return (subj and subj.strip()) or '(no subject)'


def humanize_html(htm, parent=None, class_='email-quote'):
    htm = re.sub(r'(<br[ ]?[/]?>\s*)$', '', htm).strip()
    if htm and parent:
        htm = hide_quote(htm, parent, class_)
    if htm:
        htm = toronado.from_string(htm).decode()
    return htm


def hide_quote(mail1, mail0, class_):
    # TODO: need reworking
    if not mail0 or not mail1:
        return mail1

    def clean(v):
        v = re.sub('[\s]+', '', v.text_content())
        return v.rstrip()

    t0 = clean(lhtml.fromstring(mail0))
    root1 = lhtml.fromstring(mail1)
    for block in root1.xpath('//blockquote'):
        t1 = clean(block)
        if t0 and t1 and (t0.startswith(t1) or t0.endswith(t1) or t0 in t1):
            block.attrib['class'] = class_
            parent = block.getparent()
            switch = lhtml.fromstring('<div class="%s-switch"/>' % class_)
            block.attrib['class'] = class_
            parent.insert(parent.index(block), switch)
            return lhtml.tostring(root1, encoding='utf8').decode()
    return mail1
