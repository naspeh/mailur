import datetime as dt
import re
from hashlib import md5
from urllib.parse import urlencode

import lxml.html as lh
import rapidjson as json
from werkzeug.utils import secure_filename
from unidecode import unidecode


def get_gravatar(addr, size=75, default='identicon'):
    params = urlencode((('d', default), ('s', size)))
    hash = md5(addr.strip().lower().encode()).hexdigest()
    return '//www.gravatar.com/avatar/%s?%s' % (hash, params)


def localize_dt(env, value):
    tz_offset = env.session.get('tz_offset')
    return value + dt.timedelta(hours=-(tz_offset or 0))


def humanize_dt(env, val, secs=False, ts=False):
    if ts:
        val = dt.datetime.fromtimestamp(val)
    val = localize_dt(env, val)
    now = localize_dt(env, dt.datetime.utcnow())
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M' + (':%S' if secs else '')
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)


def format_dt(env, value, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(env, value).strftime(fmt)


def get_preview(text, files):
    files = ', '.join(v['name'] for v in files)
    files = ('[%s]' % files) if files else ''
    text = re.sub(r'\s+', ' ', text) if text else ''
    text = ' '.join([t for t in (text, files) if t])
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

    lmsg = lh.fromstring(msg)
    msgs = [m for m in msgs if m]

    def clean(element):
        text = element.text_content()
        text = re.sub('[^\w]+', '', text)
        return text.rstrip()

    def toggle(block):
        block.attrib['class'] = class_
        parent = block.getparent()
        toggle = lh.fromstring('<div class="%s-toggle"/>' % class_)
        block.attrib['class'] = class_
        parent.insert(parent.index(block), toggle)
        return lh.tostring(lmsg, encoding='utf8').decode()

    for m in msgs:
        cp = clean(lh.fromstring(m))
        for block in lmsg.xpath('//blockquote'):
            cb = clean(block)
            if cp and cb and cb.endswith(cp):
                return toggle(block)

        tokens = re.findall('-{3,20}[ \w]*-{3,20}', msg)
        if not tokens:
            continue

        s = '(%s)' % '|'.join("//*[contains(text(),'%s')]" % t for t in tokens)
        for block in lmsg.xpath(s):
            blocks = [block] + [b for b in block.itersiblings()]
            cb = ''.join(clean(b) for b in blocks)
            if cp and cb and cb.endswith(cp):
                div = lh.Element('div')
                parent = blocks[0].getparent()
                index = parent.index(blocks[0])
                for b in blocks:
                    parent.remove(b)
                    div.append(b)
                parent.insert(index, div)
                return toggle(div)

    return msg


def get_hash(value):
    return md5(json.dumps(value).encode()).hexdigest()


def slugify(value):
    return secure_filename(unidecode(value).lower())
