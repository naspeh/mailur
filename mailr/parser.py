import datetime as dt
import email

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


def get_payload(msg, part, default='utf-8'):
    charset = part.get_content_charset() or msg.get_content_charset()
    text = part.get_payload(decode=True).decode(charset or default)
    return text


def parse(text):
    msg = email.message_from_bytes(text)
    body = html = None
    if msg.get_content_maintype() == "multipart":
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = get_payload(msg, part)
                elif part.get_content_type() == "text/html":
                    html = get_payload(msg, part)
    elif msg.get_content_maintype() == "text":
        body = get_payload(msg, msg)
    return {'body': body, 'html': html}
