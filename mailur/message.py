import datetime as dt
import email
import email.policy
import encodings
import hashlib
import json
import re
from email.message import MIMEPart
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from . import log
from .local import gen_msgid, msgids

encodings.aliases.aliases.update({
    # Seems Google used gb2312 in some subjects, so there is another symbol
    # instead of dash, because of next bug:
    # https://bugs.python.org/issue24036
    'gb2312': 'gbk',
    # @naspeh got such encoding in my own mailbox
    'cp-1251': 'cp1251',
})


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


def clean_html(htm):
    from lxml import html as lhtml
    from lxml.html.clean import Cleaner

    htm = re.sub(r'^\s*<\?xml.*?\?>', '', htm).strip()
    if not htm:
        return '', ''

    cleaner = Cleaner(
        links=False,
        style=True,
        kill_tags=['head', 'img', 'figure', 'picture'],
        remove_tags=['html', 'base'],
        safe_attrs=set(Cleaner.safe_attrs) - {'class'},
    )
    htm = lhtml.fromstring(htm)
    htm = cleaner.clean_html(htm)

    txt = '\n'.join(i.rstrip() for i in htm.xpath('//text()') if i.rstrip())
    htm = lhtml.tostring(htm, encoding='utf-8').decode().strip()
    return txt, htm


def binary(txt, mimetype='text/plain'):
    msg = MIMEPart()
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def parsed(raw, uid, time):
    if isinstance(raw, bytes):
        # TODO: there is a bug with folding mechanism,
        # like this one https://bugs.python.org/issue30788,
        # so use `max_line_length=None` by now, not sure if it's needed at all
        policy = email.policy.SMTPUTF8.clone(max_line_length=None)
        orig = BytesParser(policy=policy).parsebytes(raw)
    else:
        orig = raw

    meta = {'origin_uid': uid}
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

    mids = msgids()
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

    txt = orig.get_body(preferencelist=('html', 'plain'))
    if txt:
        try:
            body = txt.get_content()
            if txt.get_content_subtype() == 'plain':
                body = '<pre>%s</pre>' % body
            txt, body = clean_html(body)
        except Exception as e:
            txt = 'ERROR(mlr): %s' % e
            body = txt
            more = raw[:300].decode()
            log.error('## UID=%s error on body: %r\n%s', uid, e, more)
    meta['preview'] = re.sub('[\s ]+', ' ', txt[:200])

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
    msg.attach(binary(body))
    return msg
