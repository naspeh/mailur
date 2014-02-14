import datetime as dt
import email.header
import email.utils

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
            except UnicodeDecodeError:
                log.warn('%s -- (%s)', text, charset)
                part = text.decode(charset, 'ignore')
        parts += [part]
    return ''.join(parts)


def decode_addresses(text):
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
    'from': ('from_', decode_addresses),
    'sender': ('sender', decode_addresses),
    'reply-to': ('reply_to', decode_addresses),
    'to': ('to', decode_addresses),
    'cc': ('cc', decode_addresses),
    'bcc': ('bcc', decode_addresses),
    'in-reply-to': ('in_reply_to', str),
    'message-id': ('message_id', str)
}


def parse_header(header):
    msg = email.message_from_string(header)
    data = {}
    for key in key_map:
        field, decode = key_map[key]
        value = msg.get(key)
        data[field] = decode(value) if value else None
    return data
