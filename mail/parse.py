import datetime as dt
import email

import pytz


def decode_header(data, default='utf-8'):
    if not data:
        return None

    parts_ = email.header.decode_header(data)
    parts = []
    for text, charset in parts_:
        if isinstance(text, str):
            part = text
        else:
            part = text.decode(charset or default, 'replace')
        parts += [part]
    return ''.join(parts)


def decode_addresses(value):
    res = []
    for name, addr in email.utils.getaddresses([value]):
        res += ['"%s" <%s>' % (decode_header(name), addr) if name else addr]
    return res


def decode_date(text):
    tm_array = email.utils.parsedate_tz(text)
    tm = dt.datetime(*tm_array[:6]) - dt.timedelta(seconds=tm_array[-1])
    tm = pytz.utc.localize(tm)
    return tm


key_map = {
    'Date': ('date', decode_date),
    'Subject': ('subject', decode_header),
    'From': ('from_', decode_addresses),
    'Sender': ('sender', decode_addresses),
    'Reply-To': ('reply_to', decode_addresses),
    'To': ('to', decode_addresses),
    'CC': ('cc', decode_addresses),
    'BCC': ('bcc', decode_addresses),
    'In-Reply-To': ('in_reply_to', str),
    'Message-ID': ('message_id', str)
}


def parse_header(header):
    msg = email.message_from_string(header)
    data = {}
    for key in key_map:
        field, decode = key_map[key]
        value = msg.get(key)
        data[field] = decode(value) if value else None
    return data
