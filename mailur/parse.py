#!/usr/bin/env python3
import datetime as dt
import hashlib
import imaplib
import json
import os
import re
import sys
from email.message import MIMEPart
from email.parser import BytesParser
from email.policy import SMTPUTF8
from email.utils import parsedate_to_datetime

HEADERS = (
    'from to date message-id in-reply-to references cc bcc'
    .split()
)
BOX_ALL = 'All'
BOX_PARSED = 'Parsed'
USER = os.environ.get('MLR_USER', 'user')


def binary_msg(txt, mimetype='text/plain'):
    msg = MIMEPart(SMTPUTF8)
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt.encode(), 'utf-8')
    return msg


def connect():
    con = imaplib.IMAP4('localhost', 143)
    con.login('%s*root' % USER, 'root')
    con.enable('UTF8=ACCEPT')
    return con


def parsed_uids(con, uids):
    ok, res = con.uid('FETCH', '1:*', 'BINARY.PEEK[1]')
    for i in range(0, len(res), 2):
        m = res[i]
        uid = m[1]
        puid = m[0].split()[2]
        if uid in uids:
            yield puid


def create_msg(raw, uid, time):
    orig = BytesParser(policy=SMTPUTF8).parsebytes(raw)
    meta = {k.replace('-', '_'): orig[k] for k in ('message-id',)}

    meta['subject'] = orig['subject']
    meta['uid'] = uid

    date = orig['date']
    meta['date'] = date and parsedate_to_datetime(date).isoformat()

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    meta['arrived'] = arrived.isoformat()

    txt = orig.get_body(preferencelist=('plain', 'html'))
    body = txt.get_content()

    msg = MIMEPart()
    for n, v in orig.items():
        if n.lower() not in HEADERS:
            continue
        msg.add_header(n, v)
    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('X-SHA1', hashlib.sha1(raw).hexdigest())
    msg.make_mixed()

    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary_msg(uid, 'application/json'))
    msg.attach(binary_msg(meta_txt, 'application/json'))
    msg.attach(binary_msg(body))
    return msg


def parse_folder(criteria):
    src = connect()
    src.select(BOX_ALL)

    ok, res = src.search(None, criteria)
    uids = res[0].split(b' ')
    if not uids:
        print(' - all parsed already')
        return

    print(' * criteria: %r; uids: %s' % (criteria, res[0]))
    ok, count = src.select(BOX_PARSED)
    if count[0] != b'0':
        if criteria.lower() != 'all':
            puids = b','.join(parsed_uids(src, uids))
        else:
            ok, res = src.uid('SEARCH', None, criteria)
            puids = res[0].replace(b' ', b',')
        if puids:
            print(' * delete: %s' % puids)
            src.uid('STORE', puids, '+FLAGS.SILENT', '\Deleted')
            src.expunge()

    src.select(BOX_ALL, readonly=True)
    ok, res = src.fetch(b','.join(uids), '(UID INTERNALDATE BINARY.PEEK[])')
    msgs = [res[i] for i in range(0, len(res), 2)]
    for m in msgs:
        uid, time = re.search(
            r'UID (\d+) INTERNALDATE ("[^"]+")', m[0].decode()
        ).groups()
        orig_raw = m[1].strip()
        msg = create_msg(orig_raw, uid, time)
        ok, res = src.append('Parsed', '', time, msg.as_bytes())
        print(ok, res)


if __name__ == '__main__':
    parse_folder(sys.argv[-1] if len(sys.argv) > 1 else None)
