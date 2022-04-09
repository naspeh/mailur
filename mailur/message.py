import datetime as dt
import email
import email.header
import email.policy
import encodings
import hashlib
import json
import mimetypes
import re
import uuid
from email.message import MIMEPart
from email.utils import formatdate, getaddresses, parsedate_to_datetime

import chardet

from . import conf, html, log

aliases = {
    # Seems Google used gb2312 in some subjects, so there is another symbol
    # instead of dash, because of next bug:
    # https://bugs.python.org/issue24036
    'gb2312': 'gbk',
    # @naspeh got such encoding in my own mailbox
    'cp-1251': 'cp1251',
}
encodings.aliases.aliases.update(aliases)


class BinaryPolicy(email.policy.Compat32):
    """+
    Dovecot understands UTF-8 encoding, so let's save parsed messages
    without sanitizing.
    """

    content_manager = email.policy.raw_data_manager

    def _sanitize_header(self, name, value):
        return value

    def _fold(self, name, value, sanitize=None):
        return '%s: %s%s' % (name, value, self.linesep)

    def fold_binary(self, name, value):
        folded = self._fold(name, value)
        return folded.encode('utf8', 'surrogateescape')


policy = BinaryPolicy()


def new():
    return MIMEPart(policy)


def binary(txt, mimetype='text/plain'):
    msg = new()
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def parse_mime(orig, uid):
    def error(e, label):
        return 'error on %r: [%s] %s' % (label, e.__class__.__name__, e)

    def try_decode(raw, charsets, label=''):
        txt = err = None
        charsets = [aliases.get(c, c) for c in charsets if c]
        charset = charsets[0]
        for c in charsets:
            try:
                txt = raw.decode(c)
                charset = c
                break
            except UnicodeDecodeError as e:
                err = error(e, label)
            except LookupError as e:
                err = error(e, label)
                if len(charsets) == 1:
                    charset = 'utf8'
        return txt, charset, err

    def decode_bytes(raw, charset, label):
        if not raw:
            return ''

        txt = None
        charset = charset and charset.lower()
        if charset == 'unknown-8bit' or not charset:
            # first trying to decode with charsets detected in message
            txt = try_decode(raw, charsets)[0] if charsets else None
            if txt:
                return txt

            # trying chardet
            detected = chardet.detect(raw)
            charset = detected['encoding']
            if charset:
                charset = charset.lower()
            else:
                charset = charsets[0] if charsets else 'utf8'

        txt, charset, err = try_decode(raw, [charset], label)
        if txt:
            # if decoded without errors add to potential charsets list
            charsets.append(charset)
        if not txt:
            log.info('UID=%s %s', uid, err)
            errors.append(err)
            txt = raw.decode(charset, 'replace')
        return txt

    def decode_header(raw, label):
        if not raw:
            return None

        parts = []
        for raw, charset in email.header.decode_header(raw):
            if isinstance(raw, str):
                txt = raw
            else:
                txt = decode_bytes(raw, charset, label)
            parts += [txt]
        header = ''.join(parts)
        header = re.sub(r'\s+', ' ', header)
        return header

    def decode_addresses(raw, label):
        if not raw:
            return None

        decoded = False
        if not isinstance(raw, str):
            decoded = True
            raw = decode_header(raw, label)
        parts = []
        for name, addr in getaddresses([raw]):
            if not decoded:
                name, addr = [decode_header(i, label) for i in (name, addr)]
            parts.append(('"%s" <%s>' % (name, addr)) if name else addr)
        return ', '.join(p for p in parts if p)

    def attachment(part, content, path):
        ctype = part.get_content_type()
        label = '%s(%s)' % (ctype, path)
        item = {'size': len(content), 'path': path}
        filename = part.get_filename()
        if filename:
            filename = decode_header(part.get_filename(), label) or ''
            filename = re.sub(r'[^\w.-]', '-', filename)
        else:
            ext = mimetypes.guess_extension(ctype) or 'txt'
            filename = 'unknown-%s%s' % (path, ext)
        end = '/'.join(i for i in (path, filename) if i)
        item['url'] = '/raw/%s/%s' % (uid, end)
        item['filename'] = filename

        content_id = part.get('Content-ID')
        if content_id:
            item['content-id'] = decode_header(content_id, label)
        if ctype.startswith('image/'):
            item['image'] = True
        return item

    def parse_part(part, path=''):
        htm, txt, files = '', '', []
        ctype = part.get_content_type()
        if ctype.startswith('message/'):
            content = part.as_bytes()
            files = [attachment(part, content, path)]
            return htm, txt, files
        elif part.get_filename():
            content = part.get_payload(decode=True)
            files = [attachment(part, content, path)]
            return htm, txt, files
        elif part.is_multipart():
            idx, parts = 0, []
            for m in part.get_payload():
                idx += 1
                path_ = '%s.%s' % (path, idx) if path else str(idx)
                htm_, txt_, files_ = parse_part(m, path_)
                parts.append((htm_, txt_))
                files += files_

            htm = [h for h, t in parts if h]
            txt = [t for h, t in parts if t]
            if part.get_content_subtype() == 'alternative':
                htm = htm[0] if htm else ''
                txt = txt[0] if txt else ''
            else:
                if htm:
                    htm = '<hr>'.join(
                        h if h else html.from_text(t)
                        for h, t in parts if h or t
                    )
                    txt = ''
                elif txt:
                    txt = '\n\n'.join(txt)
                else:
                    htm = txt = ''
            return htm, txt, files

        if ctype.startswith('text/'):
            content = part.get_payload(decode=True)
            charset = part.get_content_charset()
            label = '%s(%s)' % (ctype, path)
            content = decode_bytes(content, charset, label)
            content = content.rstrip()
            if ctype == 'text/html':
                htm = content
            else:
                txt = content
        else:
            content = part.get_payload(decode=True)
            files = [attachment(part, content, path)]
        return htm, txt, files

    charsets = list(set(c.lower() for c in orig.get_charsets() if c))
    errors, headers = [], {}
    htm, txt, files = parse_part(orig)

    for n in ('From', 'Sender', 'Reply-To', 'To', 'CC', 'BCC',):
        v = decode_addresses(orig[n], n)
        if v is None:
            continue
        headers[n] = v

    headers['Subject'] = decode_header(orig['subject'], 'Subject')
    return htm, txt, files, headers, errors


def normalize_msgid(mid):
    return mid.strip().lower()


def preview(htm, files):
    htm = htm.strip()
    preview = html.to_line(htm, 200) if htm else ''
    if len(preview) < 200 and files:
        preview += (' ' if preview else '') + (
            '[%s]' % ', '.join(f['filename'] for f in files)
        )
    return preview


def parsed(raw, uid, time, flags):
    # "email.message_from_bytes" uses "email.policy.compat32" policy
    # and it's by intention, because new policies don't work well
    # with real emails which have no encodings, badly formated addreses, etc.
    orig = email.message_from_bytes(raw)
    htm, txt, files, headers, errors = parse_mime(orig, uid)
    meta = {'origin_uid': uid, 'files': [], 'errors': errors}
    if htm:
        embeds = {
            f['content-id']: f['url']
            for f in files if 'content-id' in f
        }
        htm, extra_meta = html.clean(htm, embeds)
        meta.update(extra_meta)
    elif txt:
        htm = html.from_text(txt)

    meta['preview'] = preview(htm, files)
    meta['files'] = files

    fields = (
        ('From', 1), ('Sender', 1),
        ('Reply-To', 0), ('To', 0), ('CC', 0), ('BCC', 0)
    )
    for n, one in fields:
        v = headers.get(n)
        if not v:
            continue
        v = addresses(v)
        meta[n.lower()] = v[0] if one else v

    subj = headers['Subject']
    meta['subject'] = str(subj).strip() if subj else ''

    refs = orig['references']
    refs = [i.strip().lower() for i in refs.split()] if refs else []
    parent = refs[-1] if refs else None
    in_reply_to = orig['in-reply-to'] and normalize_msgid(orig['in-reply-to'])
    if in_reply_to:
        parent = in_reply_to
        if not refs:
            refs = [in_reply_to]
    meta['parent'] = parent

    mid = orig['message-id']
    if mid is None:
        log.info('UID=%s has no "Message-ID" header', uid)
        mid = '<mailur@noid>'
    else:
        mid = normalize_msgid(mid)
    meta['msgid'] = mid

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    meta['arrived'] = int(arrived.timestamp())

    date = orig['date']
    try:
        date = date and int(parsedate_to_datetime(date).timestamp())
    except Exception as e:
        meta['errors'].append('error on date: val=%r err=%r' % (date, e))
        log.error('UID=%s can\'t parse date: val=%r err=%r', uid, date, e)
        date = None
    meta['date'] = date or meta['arrived']

    msg = new()
    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('Message-ID', mid)
    msg.add_header('Subject', meta['subject'])
    msg.add_header('Date', orig['Date'])

    for n, v in headers.items():
        if n in msg:
            continue
        msg.add_header(n, v)

    is_draft = '\\Draft' in flags
    if is_draft:
        draft_id = orig['X-Draft-ID'] or mid
        msg.add_header('X-Draft-ID', draft_id)
        meta['draft_id'] = draft_id
        txt = parse_draft(orig)[0]
    elif orig['X-Draft-ID']:
        msg.add_header('X-Draft-ID', orig['X-Draft-ID'])

    thrid = None
    if not is_draft:
        addrs = [msg['from'] or msg['sender'], msg['to']]
        addrs = (a for a in addrs if a)
        addrs = ','.join(sorted(
            '"%s" <%s>' % (n, a) if n else a
            for n, a in getaddresses(addrs)
        ))
        addrs_n_subj = ' '.join(i for i in (addrs, subj) if i)
        thrid = hashlib.md5(addrs_n_subj.encode()).hexdigest()
        thrid = '<%s@mailur.link>' % thrid

    thrid = ' '.join(i for i in (thrid, orig['X-Thread-ID']) if i)
    if thrid:
        meta['thrid'] = thrid
        msg.add_header('X-Thread-ID', thrid)
        refs.insert(0, thrid)

    if refs:
        msg.add_header('In-Reply-To', refs[-1])
        msg.add_header('References', ' '.join(refs))

    msg.make_mixed()
    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary(meta_txt, 'application/json'))
    body = new()
    body.make_alternative()
    body.attach(binary(htm, 'text/html'))
    if txt:
        body.attach(binary(txt))
    msg.attach(body)

    flags = []
    if meta['errors']:
        flags.append('#err')
    return msg, flags


def sending(msg, linesep='\r\n', maxlinelen=70):
    def _fold(v, name=None):
        try:
            v.encode('ascii')
        except UnicodeEncodeError:
            v = email.header.Header(v, charset='utf-8', header_name=name)
            v = v.encode(maxlinelen=maxlinelen, linesep=linesep)
        return v

    def fold(name, value):
        return '%s: %s%s' % (name, _fold(value, name), linesep)

    def fold_addrs(name, value):
        addrs = email.utils.getaddresses([value])
        parts = []
        length = 0
        for n, a in addrs:
            part = '%s <%s>' % (_fold(n), a)
            length += len(part)
            if len(part) > maxlinelen:
                part = '%s %s' % (linesep, part)
                length = len(part)
            parts.append(part)
        addrs = ','.join(parts)
        return '%s: %s%s' % (name, addrs, linesep)

    params = [
        [a for n, a in email.utils.getaddresses([msg[name]])]
        for name in ('From', 'To') if msg[name]
    ]
    if len(params) < 2:
        raise ValueError('"From" and "To" shouldn\'t be empty')

    # These new email policies work pretty strange,
    # so this machinery is to encode "Subject", "From" and "To" headers
    # and keep mime body as is
    headers = []
    for n, f in (('Subject', fold), ('From', fold_addrs), ('To', fold_addrs)):
        headers.append(f(n, msg[n]))
        del msg[n]
    msg = b''.join([''.join(headers).encode(), msg.as_bytes()])
    params.append(msg)
    return params


def parse_draft(msg):
    def extract_txt(msg):
        mixed_types = ('multipart/mixed', 'multipart/related')
        ctype = msg.get_content_type()
        if ctype == 'text/plain':
            txt = msg.get_payload(decode=True)
            parts = []
        elif ctype == 'multipart/alternative':
            txt = msg.get_payload()
            txt = txt[0].get_payload(decode=True) if txt else ''
            parts = []
        elif ctype in mixed_types:
            parts = msg.get_payload()
            txt, _ = extract_txt(parts[0])
            parts = parts[1:]
            if len(parts) == 1 and parts[0].get_content_type() in mixed_types:
                parts = parts[0].get_payload()
        else:
            raise ValueError('Wrong content-type: %s' % ctype)
        return txt, parts

    txt, parts = extract_txt(msg)
    if isinstance(txt, bytes):
        txt = txt.decode()
    return txt, parts


def new_draft(draft, related, msgid=None):
    txt = new()
    txt.make_alternative()
    plain = draft.get('txt', '')
    txt.attach(binary(plain))
    htm = html.markdown(plain)
    txt.attach(binary(htm, 'text/html'))
    if related:
        msg = new()
        msg.make_mixed()
        msg.attach(txt)
        msg.attach(related)
    else:
        msg = txt

    msg.add_header('X-Draft-ID', draft['draft_id'])
    msg.add_header('Message-ID', msgid or draft['draft_id'])
    msg.add_header('Date', formatdate(usegmt=True))
    headers = ('From', 'To', 'CC', 'Subject', 'In-Reply-To', 'References')
    for h in headers:
        val = draft.get(h.lower())
        if val:
            msg.add_header(h, val)
    return msg


def gen_msgid():
    return '<%s@%s>' % (uuid.uuid4().hex, conf['DOMAIN'])


def gen_draftid():
    return '<%s>' % uuid.uuid4().hex[:8]


def address_name(a):
    if a[0]:
        return a[0]
    try:
        index = a[1].index('@')
    except ValueError:
        return a[1]
    return a[1][:index]


def addresses(txt):
    addrs = [
        {
            'addr': a[1].lower(),
            'name': address_name(a),
            'title': '"{}" <{}>'.format(*a) if a[0] else a[1],
            'hash': hashlib.md5(a[1].strip().lower().encode()).hexdigest(),
        } for a in getaddresses([txt])
    ]
    return addrs
