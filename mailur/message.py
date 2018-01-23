import datetime as dt
import email.policy
import encodings
import hashlib
import html
import json
import re
import urllib.parse
import uuid
from email.message import MIMEPart
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, parsedate_to_datetime

from . import log

encodings.aliases.aliases.update({
    # Seems Google used gb2312 in some subjects, so there is another symbol
    # instead of dash, because of next bug:
    # https://bugs.python.org/issue24036
    'gb2312': 'gbk',
    # @naspeh got such encoding in my own mailbox
    'cp-1251': 'cp1251',
})


def binary(txt, mimetype='text/plain'):
    msg = MIMEPart()
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def link(msgids):
    msgid = gen_msgid('link')
    msg = MIMEPart(email.policy.SMTPUTF8)
    msg.add_header('Subject', 'Dummy: linking threads')
    msg.add_header('References', ' '.join(msgids))
    msg.add_header('Message-Id', msgid)
    msg.add_header('From', 'mailur@link')
    msg.add_header('Date', formatdate())
    return msg


def parsed(raw, uid, time, mids):
    # TODO: there is a bug with folding mechanism,
    # like this one https://bugs.python.org/issue30788,
    # so use `max_line_length=None` by now, not sure if it's needed at all
    policy = email.policy.SMTPUTF8.clone(max_line_length=None)
    if isinstance(raw, bytes):
        orig = BytesParser(policy=policy).parsebytes(raw)
    else:
        orig = raw

    meta = {'origin_uid': uid, 'files': []}
    msg = MIMEPart(policy)

    fields = (('from', 1), ('sender', 1), ('to', 0), ('cc', 0), ('bcc', 0))
    for n, one in fields:
        try:
            v = orig[n]
        except Exception as e:
            more = raw[:300].decode()
            log.error('## UID=%s error on header %r: %r\n%s', uid, n, e, more)
            continue
        if not v:
            continue
        v = addresses(v)
        meta[n] = v[0] if one else v

    subj = orig['subject']
    meta['subject'] = str(subj).strip() if subj else subj

    refs = orig['references']
    refs = refs.split() if refs else []
    if not refs:
        in_reply_to = orig['in-reply-to']
        refs = [in_reply_to] if in_reply_to else []
    meta['parent'] = refs[0] if refs else None
    refs = [r for r in refs if r in mids]

    mid = orig['message-id']
    if mid is None:
        log.info('## UID=%s has no "Message-Id" header', uid)
        mid = '<mailur@noid>'
    else:
        mid = mid.strip()
    meta['msgid'] = mid
    if mids[mid][0] != uid:
        log.info('## UID=%s is a duplicate {%r: %r}', uid, mid, mids[mid])
        msg.add_header('X-Dpulicate', mid)
        mid = gen_msgid('dup')

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    meta['arrived'] = int(arrived.timestamp())

    date = orig['date']
    meta['date'] = date and int(parsedate_to_datetime(date).timestamp())

    txt, htm, files = parse_part(orig)
    if txt:
        txt = html.escape(txt)
    if htm:
        embeds = {
            f['content-id']: '/raw/%s/%s' % (uid, f['path'])
            for f in files if 'content-id' in f
        }
        txt, htm, ext_images = clean_html(htm, embeds)
        meta['ext_images'] = ext_images
    elif txt:
        htm = '<pre>%s</pre>' % txt
    meta['preview'] = re.sub('[\s ]+', ' ', txt[:200])
    meta['files'] = files

    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('Message-Id', mid)
    msg.add_header('Subject', meta['subject'])

    headers = ('Date', 'From', 'Sender', 'To', 'CC', 'BCC',)
    for n in headers:
        try:
            v = orig[n]
        except Exception as e:
            more = raw[:300].decode()
            log.error('## UID=%s error on header %r: %r\n%s', uid, n, e, more)
            continue
        if v is None:
            continue
        msg.add_header(n, v)

    if msg['from'] == 'mailur@link':
        msg.add_header('References', orig['references'])
    elif refs:
        msg.add_header('References', ' '.join(refs))

    msg.make_mixed()
    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary(meta_txt, 'application/json'))
    msg.attach(binary(htm))
    return msg


def gen_msgid(label):
    return '<%s@mailur.%s>' % (uuid.uuid4().hex, label)


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
            'addr': a[1],
            'name': address_name(a),
            'title': '{} <{}>'.format(*a) if a[0] else a[1],
            'hash': hashlib.md5(a[1].strip().lower().encode()).hexdigest(),
        } for a in getaddresses([txt])
    ]
    return addrs


def parse_part(part, path=''):
    txt, htm, files = '', '', []
    if part.is_multipart():
        idx = 0
        for m in part.get_payload():
            idx += 1
            path_ = '%s.%s' % (path, idx) if path else str(idx)
            txt_, htm_, files_ = parse_part(m, path=path_)
            txt += txt_
            htm += htm_
            files += files_
        return txt, htm, files

    ctype = part.get_content_type()
    content = part.get_content()
    if ctype == 'text/html':
        htm = content
    elif ctype == 'text/plain':
        txt = content
    else:
        item = {
            'size': len(content),
            'path': path
        }
        item.update({
            k: v for k, v in (
                ('content-id', part.get('Content-ID')),
                ('filename', part.get_filename()),
            ) if v
        })
        files = [item]
    return txt, htm, files


def clean_html(htm, embeds):
    from lxml import html as lhtml
    from lxml.html.clean import Cleaner

    htm = re.sub(r'^\s*<\?xml.*?\?>', '', htm).strip()
    if not htm:
        return '', ''

    cleaner = Cleaner(
        links=False,
        style=True,
        kill_tags=['head'],
        remove_tags=['html', 'base'],
        safe_attrs=set(Cleaner.safe_attrs) - {'class'},
    )
    htm = lhtml.fromstring(htm)
    htm = cleaner.clean_html(htm)

    ext_images = False
    for img in htm.xpath('//img[@src]'):
        # clean data-src attribute if exists
        if img.attrib.get('data-src'):
            del img.attrib['data-src']

        src = img.attrib.get('src')
        cid = re.match('^cid:(.*)', src)
        url = cid and embeds.get('<%s>' % cid.group(1))
        if url:
            img.attrib['src'] = url
        elif re.match('^data:image/.*', src):
            pass
        elif re.match('^(https?://|//).*', src):
            ext_images = True
            proxy_url = '/proxy?' + urllib.parse.urlencode({'url': src})
            img.attrib['data-src'] = proxy_url
            del img.attrib['src']
        else:
            del img.attrib['src']

    txt = '\n'.join(i.rstrip() for i in htm.xpath('//text()') if i.rstrip())
    htm = lhtml.tostring(htm, encoding='utf-8').decode().strip()
    return txt, htm, ext_images
