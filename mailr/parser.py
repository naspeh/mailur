import copy
import datetime as dt
import email
import os
import re
from collections import OrderedDict

import chardet
from lxml import html
from werkzeug.utils import secure_filename

from . import log, attachments_dir


def decode_str(text, charset=None, msg_id=None):
    charset = charset if charset else 'utf8'
    try:
        part = text.decode(charset)
    except LookupError:
        charset_ = chardet.detect(text)['encoding']
        part = text.decode(charset_, 'ignore')
    except UnicodeDecodeError:
        log.warn('DecodeError(%s) -- %s', charset, msg_id or text[:200])
        part = text.decode(charset, 'ignore')
    return part


def decode_header(text, default='utf-8', msg_id=None):
    if not text:
        return None

    parts_ = email.header.decode_header(text)
    parts = []
    for text, charset in parts_:
        if isinstance(text, str):
            part = text
        else:
            part = decode_str(text, charset or default, msg_id)
        parts += [part]

    header = ''.join(parts)
    header = re.sub('\s+', ' ', header)
    return header


def decode_addresses(text):
    if not isinstance(text, str):
        text = str(text)
    res = []
    for name, addr in email.utils.getaddresses([text]):
        res += [addr]
        #name, addr = [decode_header(r) for r in [name, addr]]
        #res += ['"%s" <%s>' % (name, addr) if name else addr]
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


def parse_part(part, msg_id, inner=False):
    content = OrderedDict([
        ('files', []),
        ('attachments', []),
        ('embedded', {}),
    ])

    def update_content(c):
        content.setdefault('html', '')
        if part.get_content_subtype() != 'alternative':
            content['html'] += c.pop('html', '')
        content['files'] += c.pop('files')
        content.update(c)

    if part.get_content_maintype() == 'multipart':
        for m in part.get_payload():
            update_content(parse_part(m, msg_id, inner=True))
    elif part.get_filename() or part.get_content_maintype() == 'image':
        payload = part.get_payload(decode=True)
        attachment = {
            'maintype': part.get_content_maintype(),
            'type': part.get_content_type(),
            'id': part.get('Content-ID'),
            'filename': decode_header(part.get_filename(), msg_id=msg_id),
            'payload': payload,
            'size': len(payload) if payload else None
        }
        content['files'] += [attachment]
    elif part.get_content_type() in ['text/html', 'text/plain']:
        text = part.get_payload(decode=True)
        text = decode_str(text, part.get_content_charset(), msg_id)
        content[part.get_content_type()] = text
        content['html'] = prepare_html(content)
    else:
        log.warn('UnknownType(%s) -- %s', part.get_content_type(), msg_id)

    if inner:
        return content

    content.update(attachments=[], embedded={})
    for index, item in enumerate(content['files']):
        if item['payload']:
            name = secure_filename(item['filename'] or item['id'])
            url = '/'.join([secure_filename(msg_id), str(index), name])
            if item['id'] and item['maintype'] == 'image':
                content['embedded'][item['id']] = url
            elif item['filename']:
                content['attachments'] += [url]
            else:
                log.warn('UnknownAttachment(%s)', msg_id)
                continue
            path = os.path.join(attachments_dir, url)
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'bw') as f:
                    f.write(item['payload'])
    return content


def parse(text, msg_id=None):
    msg = email.message_from_bytes(text)

    data = {}
    for key in key_map:
        field, decode = key_map[key]
        value = msg.get(key)
        data[field] = decode(value) if value else None

    data.update(parse_part(msg, msg_id or data['message_id']))
    return data


def prepare_html(content):
    from lxml.html.clean import Cleaner
    from mistune import markdown

    embedded = content.get('embedded')
    htm = content.get('text/html')
    txt = content.get('text/plain')
    if htm:
        cleaner = Cleaner(links=False, safe_attrs_only=False)
        htm = cleaner.clean_html(htm)
        if embedded:
            root = html.fromstring(htm)
            for img in root.findall('.//img'):
                if not img.attrib.get('src').startswith('cid:'):
                    continue
                cid = '<%s>' % img.attrib.get('src')[4:]
                img.attrib['src'] = '/attachments/' + embedded[cid]
            htm = html.tostring(root, encoding='utf8').decode()
    elif txt:
        htm = markdown(txt)
        htm = re.sub(r'(?m)(\n|\r|\r\n)', '<br/>', htm)
    else:
        htm = ''
    return htm


def hide_quote(mail1, mail0, class_):
    if not mail0 or not mail1:
        return mail1

    def clean(v):
        v = html.tostring(v, pretty_print=True, encoding='utf8').decode()
        v = re.sub('<[^>]*?>', ' ', v)
        v = re.sub('[\s]+', ' ', v).strip()
        v = re.sub('[\s(&#13;)]+$', '', v)  # TODO
        return v.rstrip()

    t0 = clean(html.fromstring(mail0))
    root1 = html.fromstring(mail1)
    for block in root1.xpath('//blockquote'):
        t1 = clean(block)
        if t0.startswith(t1) or t0.endswith(t1) or t0 in t1:
            parent = block.getparent()
            new = html.fromstring(
                '<div class="{0}-switch"/><div class="{0}"/>'
                .format(class_)
            )
            new.find_class(class_)[0].append(copy.deepcopy(block))
            parent.replace(block, new)
            return html.tostring(root1, encoding='utf8').decode()
    return mail1
