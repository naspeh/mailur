import datetime as dt
import email
from collections import OrderedDict

import chardet

from . import log


def decode_header(text, default='utf-8'):
    if not text:
        return None

    parts_ = email.header.decode_header(text)
    parts = []
    for text, charset in parts_:
        if isinstance(text, str):
            part = text
        else:
            charset = charset or default
            try:
                part = text.decode(charset)
            except LookupError:
                charset_ = chardet.detect(text)['encoding']
                part = text.decode(charset_, 'ignore')
            except UnicodeDecodeError:
                log.warn('%s -- (%s)', text, charset)
                part = text.decode(charset, 'ignore')
        parts += [part]
    return ''.join(parts)


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


def parse_header(header):
    msg = email.message_from_bytes(header)
    data = {}
    for key in key_map:
        field, decode = key_map[key]
        value = msg.get(key)
        data[field] = decode(value) if value else None
    return data


def get_payload(part, default='utf-8'):
    charset = part.get_content_charset() or default
    text = part.get_payload(decode=True).decode(charset)
    return text


def parse_part(parts):
    content = OrderedDict()
    for part in parts:
        mtype = part.get_content_maintype()
        if mtype == 'text':
            content[part.get_content_type()] = get_payload(part)
        elif part.get_filename():
            content.setdefault('attachments', [])
            content['attachments'] += [{
                'content_type': part.get_content_type(),
                'filename': part.get_filename(),
                'payload': part.get_payload(decode=True)
            }]
    return content


def parse(text):
    msg = email.message_from_bytes(text)

    parts = parse_part(msg.walk())
    return parts
