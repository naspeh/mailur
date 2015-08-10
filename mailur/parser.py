import datetime as dt
import email
import email.header
import os
import re
from collections import OrderedDict
from html import escape as html_escape

import chardet
from lxml import html as lhtml
from lxml.html.clean import Cleaner

from . import log


def slugify(value):
    from werkzeug.utils import secure_filename
    from unidecode import unidecode

    return secure_filename(unidecode(value).lower())


def get_charset(name):
    # TODO: http://w3lib.readthedocs.org/en/latest/_modules/w3lib/encoding.html
    aliases = {
        'unknown-8bit': None,
        'cp-1251': 'cp1251',
        'gb2312': 'gbk',
        # Aliases from: https://github.com/SimonSapin/python-webencodings/
        'iso-8859-8-i': 'iso-8859-8',
        'x-mac-cyrillic': 'mac-cyrillic',
        'macintosh': 'mac-roman',
        'windows-874': 'cp874'
    }
    return aliases.get(name, name)


def guess_charsets(text, extra=None):
    extra = get_charset(extra)
    detected = chardet.detect(text)
    detected, confidence = detected['encoding'], detected['confidence']
    if confidence > 0.9:
        return [detected]
    charsets = [extra, detected]
    return [c for c in charsets if c]


def decode_str(text, charset, msg_id=None):
    if not text:
        return ''

    def guess_charsets():
        guess = getattr(decode_str, 'guess_charsets')
        if guess:
            return guess()
        return ['utf8']

    charset = get_charset(charset)
    charsets = [charset] if charset else guess_charsets()
    for charset_ in charsets:
        try:
            part = text.decode(get_charset(charset_))
            break
        except UnicodeDecodeError:
            part = None

    if not part:
        charset_ = charsets[0]
        log.debug('UnicodeDecodeError(%s) -- %s', charset_, msg_id)
        part = text.decode(charset_, 'ignore')
    return part


def decode_header(text, msg_id):
    if not text:
        return ''

    parts = []
    for text, charset in email.header.decode_header(text):
        if isinstance(text, str):
            part = text
        else:
            part = decode_str(text, charset, msg_id=msg_id)
        parts += [part]

    header = ''.join(parts)
    header = re.sub('\s+', ' ', header)
    return header


def decode_addresses(text, msg_id):
    text = decode_header(text, msg_id)
    return [(name, addr) for name, addr in email.utils.getaddresses([text])]


def decode_date(text, *args):
    tm_array = email.utils.parsedate_tz(text)
    tm = dt.datetime(*tm_array[:6]) - dt.timedelta(seconds=tm_array[-1])
    return tm


def parse_part(part, msg_id, attachments_dir, inner=False):
    content = OrderedDict([
        ('files', []),
        ('attachments', []),
        ('embedded', {}),
        ('html', '')
    ])

    ctype = part.get_content_type()
    mtype = part.get_content_maintype()
    stype = part.get_content_subtype()
    if part.is_multipart():
        for m in part.get_payload():
            child = parse_part(m, msg_id, attachments_dir, True)
            child_html = child.pop('html', '')
            content.setdefault('html', '')
            if stype != 'alternative':
                content['html'] += child_html
            elif child_html:
                content['html'] = child_html
            content['files'] += child.pop('files')
            content.update(child)
    elif mtype == 'multipart':
        text = part.get_payload(decode=True)
        text = decode_str(text, part.get_content_charset(), msg_id=msg_id)
        content['html'] = text
    elif ctype in ['text/html', 'text/plain']:
        text = part.get_payload(decode=True)
        text = decode_str(text, part.get_content_charset(), msg_id=msg_id)
        if ctype == 'text/plain':
            text = text2html(text)
        content['html'] = text
    else:
        payload = part.get_payload(decode=True)
        filename = part.get_filename()
        filename = decode_header(filename, msg_id) if filename else ctype
        attachment = {
            'maintype': mtype,
            'type': ctype,
            'id': part.get('Content-ID'),
            'filename': filename,
            'payload': payload,
            'size': len(payload) if payload else None
        }
        content['files'] += [attachment]
        if not part.get_filename() and mtype != 'image':
            log.warn('UnknownType(%s) -- %s', ctype, msg_id)

    if inner:
        return content

    content.update(attachments=[], embedded={})
    for index, item in enumerate(content['files']):
        if item['payload']:
            name = slugify(item['filename'] or item['id'])
            url = '/'.join([slugify(msg_id), str(index), name])
            obj = {
                'url': url,
                'name': item['filename'],
                'type': item['maintype']
            }
            if item['id']:
                content['embedded'][item['id']] = obj
            elif item['filename']:
                content['attachments'].append(obj)
            else:
                log.warn('UnknownAttachment(%s)', msg_id)
                continue
            path = os.path.join(attachments_dir, url)
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'bw') as f:
                    f.write(item['payload'])

    if content['html']:
        htm = re.sub(r'^\s*<\?xml.*?\?>', '', content['html']).strip()
        htm = re.sub(r'<(/?)body([^>]*)>', r'<\1div\2>', htm)
        if not htm:
            content['html'] = ''
            return content

        cleaner = Cleaner(
            links=False,
            safe_attrs_only=False,
            kill_tags=['head', 'style'],
            remove_tags=['html', 'base']
        )
        htm = lhtml.fromstring(htm)
        htm = cleaner.clean_html(htm)

        # Fix img[@src]
        for img in htm.xpath('//img[@src]'):
            src = img.attrib.get('src')

            cid = re.match('^cid:(.*)', src)
            obj = cid and content['embedded'].get('<%s>' % cid.group(1))
            if obj:
                cid = cid.group(1)
                img.attrib['src'] = obj['url']
            elif not re.match('^(https?://|/|data:image/).*', src):
                del img.attrib['src']

        content['html'] = lhtml.tostring(htm, encoding='utf-8').decode()
        if 'text' not in content or not content['text']:
            htm = Cleaner(links=False, style=True).clean_html(htm)
            text = '\n'.join(htm.xpath('//text()'))
            content['text'] = text.strip()

    content['text'] = content.get('text') or ''
    return content


def parse(text, msg_id=None, attachments_dir=None):
    attachments_dir = attachments_dir or '/tmp/mailur'

    msg = email.message_from_bytes(text)
    charset = [c for c in msg.get_charsets() if c]
    charset = charset[0] if charset else None
    decode_str.guess_charsets = lambda: guess_charsets(text[:4096], charset)

    decoders = {
        'subject': decode_header,
        'from': decode_addresses,
        'to': decode_addresses,
        'cc': decode_addresses,
        'bcc': decode_addresses,
        'reply-to': decode_addresses,
        'sender': decode_addresses,
        'date': decode_date,
        'message-id': lambda t, *a: str(t),
        'in-reply-to': lambda t, *a: str(t),
        'references': lambda t, *a: str(t),
    }
    data = {}
    for key, decode in decoders.items():
        value = msg.get(key)
        data[key] = decode(value, msg_id) if value else None

    msg_id = str(msg_id or data['message-id'])
    files = parse_part(msg, msg_id, attachments_dir)
    data['attachments'] = files['attachments']
    data['embedded'] = files['embedded']
    data['html'] = files.get('html', None)
    data['text'] = files.get('text', None)
    return data


link_regexes = [
    r'(https?://|www\.)[^\s]+',
    r'mailto:([a-z0-9._-]+@[a-z0-9_._]+[a-z])',
]
link_re = re.compile('(?i)(%s)' % '|'.join(link_regexes))


def text2html(txt):
    txt = txt.strip()
    if not txt:
        return ''

    def fill_link(match):
        return '<a href="{0}" target_="_blank">{0}</a>'.format(match.group())

    htm = html_escape(txt)
    htm = link_re.sub(fill_link, htm)
    htm = '<pre class="email-text2html">%s</pre>' % htm
    return htm
