import copy
import datetime as dt
import email
import re
from collections import OrderedDict

import chardet
import lxml.html as html

from . import log


def decode_str(text, charset, msg_id=None):
    try:
        part = text.decode(charset)
    except LookupError:
        charset_ = chardet.detect(text)['encoding']
        part = text.decode(charset_, 'ignore')
    except UnicodeDecodeError:
        log.warn('DecodeError(%s) -- %s', charset, msg_id or text[:200])
        part = text.decode(charset, 'ignore')
    return part


def decode_header(text, default='utf-8'):
    if not text:
        return None

    parts_ = email.header.decode_header(text)
    parts = []
    for text, charset in parts_:
        if isinstance(text, str):
            part = text
        else:
            part = decode_str(text, charset or default)
        parts += [part]

    header = ''.join(parts)
    header = re.sub('\s+', ' ', header)
    return header


def decode_addresses(text):
    if not isinstance(text, str):
        text = str(text)
    res = []
    for name, addr in email.utils.getaddresses([text]):
        res += ['"%s" <%s>' % (decode_header(name), addr) if name else addr]
    return res


def decode_date(text):
    tm_array = email.utils.parsedate_tz(text)
    tm = dt.datetime(*tm_array[:6]) - dt.timedelta(seconds=tm_array[-1])
    return tm


key_map = {
    'date': ('date', decode_date),
    'subject': ('subject', decode_header),
    'from': ('from', decode_addresses),
    'sender': ('sender', decode_addresses),
    'reply-to': ('reply_to', decode_addresses),
    'to': ('to', decode_addresses),
    'cc': ('cc', decode_addresses),
    'bcc': ('bcc', decode_addresses),
    'in-reply-to': ('in_reply_to', str),
    'message-id': ('message_id', str)
}


def parse_part(parts, msg_id):
    content = OrderedDict()
    for part in parts:
        if part.get_filename() or part.get_content_maintype() == 'image':
            payload = part.get_payload(decode=True)
            content.setdefault('attachments', [])
            content['attachments'] += [{
                'content_type': part.get_content_type(),
                'content_id': part.get('Content-ID'),
                'filename': part.get_filename(),
                'payload': payload,
                'size': len(payload) if payload else None
            }]
        elif part.get_content_type() in ['text/html', 'text/plain']:
            text = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            text = decode_str(text, charset, msg_id)
            content[part.get_content_type()] = text
        elif not part.get_content_maintype() == 'multipart':
            log.warn('UnknownType(%s) -- %s', part.get_content_type(), msg_id)
    return content


def parse(text):
    msg = email.message_from_bytes(text)

    data = {}
    for key in key_map:
        field, decode = key_map[key]
        value = msg.get(key)
        data[field] = decode(value) if value else None

    data.update(parse_part(msg.walk(), data['message_id']))
    return data


def hide_quote(mail1, mail0, class_):
    if not mail0 or not mail1:
        return mail1

    def clean(v):
        v = html.tostring(v, pretty_print=True, encoding='utf8').decode()
        v = re.sub('<[^>]*?>', ' ', v)
        v = re.sub('[\s]+', ' ', v).strip()
        v = re.sub('[\s(&#13;)]+$', '', v)  # TODO
        return v.rstrip()

    html0 = clean(html.fromstring(mail0.strip()))
    m1 = html.fromstring(mail1.strip())
    for block in m1.xpath('//blockquote'):
        text = clean(block)
        if html0 == text or (text and html0.endswith(text)):
            parent = block.getparent()
            new = html.fromstring(
                '<div class="{0}-switch"/><div class="{0}"/>'
                .format(class_)
            )
            new.find_class(class_)[0].append(copy.deepcopy(block))
            parent.replace(block, new)
            return html.tostring(m1, encoding='utf8').decode()
    return mail1
