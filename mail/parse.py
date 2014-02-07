import email

import chardet


def decode_header(data, default='utf-8'):
    if not data:
        return None

    parts_ = email.header.decode_header(data)
    parts = []
    for text, charset in parts_:
        if isinstance(text, str):
            part = text
        else:
            try:
                part = text.decode(charset or default)
            except (LookupError, UnicodeDecodeError):
                charset = chardet.detect(text)['encoding']
                part = text.decode(charset or default, 'replace')
        parts += [part]
    return ''.join(parts)


def decode_addresses(value):
    addrs = []
    for name, addr in email.utils.getaddresses([value]):
        addrs.append(
            '"%s" <%s>' % (decode_header(name), addr) if name else addr
        )
    return addrs


key_map = {
    #'Date': ('date', str),
    'Subject': ('subject', decode_header),
    'From': ('from_', decode_addresses),
    'Sender': ('sender', decode_addresses),
    'Reply-To': ('reply_to', decode_addresses),
    'To': ('to', decode_addresses),
    'CC': ('cc', decode_addresses),
    'BCC': ('bcc', decode_addresses),
    #'In-Reply-To': ('in_reply_to', str),
    #'Message-ID': ('message_id', str)
}


def parse_header(header):
    msg = email.message_from_string(header)
    data = {}
    for key in key_map:
        field, decode = key_map[key]
        value = msg.get(key)
        data[field] = decode(value) if value else None
    return data
