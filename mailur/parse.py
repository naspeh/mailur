#!/usr/bin/env python3
import datetime as dt
import hashlib
import imaplib
import json
import os
import re
import sys
from email import policy
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

HEADERS = (
    'from to date message-id in-reply-to references cc bcc'
    .split()
)
BOX_ALL = 'All'
BOX_PARSED = 'Parsed'
USER = os.environ.get('MLR_USER', 'user')


def binary_msg(txt):
    msg = MIMEText('')
    msg.replace_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt.encode(), 'utf-8')
    return msg


def connect():
    con = imaplib.IMAP4('localhost', 143)
    con.login('%s*root' % USER, 'root')
    con.enable('UTF8=ACCEPT')
    return con


def parsed_uids(con, uids):
    ok, res = con.uid('FETCH', '1:*', 'FLAGS')
    for i in res:
        puid, uid = re.search(b'UID (\d+) FLAGS \([^)]*?(\d+)', i).groups()
        if uid in uids:
            yield puid


def parse_msg(b, uid, time):
    orig = BytesParser(policy=policy.SMTPUTF8).parsebytes(b)
    msg = {k.replace('-', '_'): orig[k] for k in HEADERS}

    msg['subject'] = orig['subject']
    msg['uid'] = uid

    date = msg['date']
    msg['date'] = date and parsedate_to_datetime(date).isoformat()

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    msg['arrived'] = arrived.isoformat()

    txt = orig.get_body(preferencelist=('plain', 'html'))
    msg['body'] = txt.get_content()
    return msg, orig


def parse_folder(criteria):
    src = connect()
    src.select(BOX_ALL)

    ok, res = src.search(None, criteria)
    uids = res[0].split(b' ')
    if not uids:
        print('All parsed already')
        return

    print('criteria: %r; uids: %s' % (criteria, res[0]))
    ok, count = src.select(BOX_PARSED)
    if count[0] != b'0':
        if criteria.lower() != 'all':
            puids = b','.join(parsed_uids(src, uids))
        else:
            ok, res = src.uid('SEARCH', None, criteria)
            puids = res[0].replace(b' ', b',')
        print('Delete: %s' % puids)
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
        parsed, orig = parse_msg(orig_raw, uid, time)
        msg = binary_msg(json.dumps(
            parsed, sort_keys=True, ensure_ascii=False, indent=2
        ))
        msg.add_header('X-UID', '<%s>' % uid)
        msg.add_header('X-SHA1', hashlib.sha1(orig_raw).hexdigest())
        for n, v in orig.items():
            if n.lower() not in HEADERS:
                continue
            msg.add_header(n, v)
        ok, res = src.append('Parsed', '(%s)' % uid, time, msg.as_bytes())
        print(ok, res)


if __name__ == '__main__':
    parse_folder(sys.argv[1] if len(sys.argv) > 1 else None)
