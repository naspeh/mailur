#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import os
import re
import sys
from concurrent import futures
from email.message import MIMEPart
from email.parser import BytesParser
from email.policy import SMTPUTF8
from email.utils import parsedate_to_datetime

from . import imap

HEADERS = (
    'from to date message-id in-reply-to references cc bcc'
    .split()
)


def binary_msg(txt, mimetype='text/plain'):
    msg = MIMEPart(SMTPUTF8)
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def parsed_uids(con, uids):
    res = con.fetch('1:*', 'BINARY.PEEK[1]')
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


def parse_batch(uids):
    con = imap.Local()
    res = con.fetch(b','.join(uids), '(UID INTERNALDATE BINARY.PEEK[])')

    def iter_msgs(res):
        for i in range(0, len(res), 2):
            m = res[i]
            uid, time = re.search(
                r'UID (\d+) INTERNALDATE ("[^"]+")', m[0].decode()
            ).groups()
            msg = create_msg(m[1], uid, time)
            yield time, msg.as_bytes()

    return con.multiappend(iter_msgs(res), box=con.PARSED)


def parse_folder(criteria=None):
    con = imap.Local()
    uidnext = 1
    if criteria is None:
        res = con.getmetadata('mlr/uidnext')
        if len(res) > 1:
            uidnext = int(res[0][1].decode())
            print('## saved: uidnext=%s' % uidnext)
        criteria = 'UID %s:*' % uidnext

    res = con.search(criteria)
    uids = [i for i in res[0].split(b' ') if i and int(i) >= uidnext]
    if not uids:
        print('## all parsed already')
        return

    res = con.status(con.ALL, '(UIDNEXT)')
    uidnext = re.search(r'UIDNEXT (?P<next>\d+)', res[0].decode()).group(1)
    print('## new: uidnext: %s' % uidnext)

    print('## criteria: %r; %s uids' % (criteria, len(uids)))
    count = con.select(con.PARSED)
    if count[0] != b'0':
        if criteria.lower() != 'all':
            puids = list(parsed_uids(con, uids))
        else:
            res = con.search(criteria)
            puids = res[0].split(b' ')
        if puids:
            print('## delete %s parsed messages' % len(puids))
            con.uid('STORE', b','.join(puids), '+FLAGS.SILENT', '\Deleted')
            con.expunge()

    process_batches(parse_batch, uids)
    con.setmetadata('mlr/uidnext', str(uidnext))


def fetch_batch(uids, folder):
    if not uids:
        return
    gm = imap.Gmail(folder)
    fields = '(UID INTERNALDATE FLAGS X-GM-LABELS X-GM-MSGID BODY.PEEK[])'
    res = gm.fetch(b','.join(uids), fields)

    def iter_msgs(res):
        for i in range(0, len(res), 2):
            m = res[i]
            parts = re.search(
                r'('
                r'UID (?P<uid>\d+)'
                r' ?|'
                r'INTERNALDATE (?P<time>"[^"]+")'
                r' ?|'
                r'FLAGS \((?P<flags>[^)]*)\)'
                r' ?|'
                r'X-GM-LABELS \((?P<labels>[^)]*)\)'
                r' ?|'
                r'X-GM-MSGID (?P<msgid>\d+)'
                r' ?){5}',
                m[0].decode()
            ).groupdict()
            yield parts['time'], m[1]

    con = imap.Local(box=None)
    return con.multiappend(iter_msgs(res))


def fetch_folder(folder='\\All'):
    print('## process "%s"' % folder)
    con = imap.Local()
    metakey = 'gmail/uidnext/%s' % folder.strip('\\').lower()
    res = con.getmetadata(metakey)
    if len(res) != 1:
        uidvalidity, uidnext = res[0][1].decode().split(',')
        uidnext = int(uidnext)
    else:
        uidvalidity = uidnext = None
    print('## saved: uidvalidity=%s uidnext=%s' % (uidvalidity, uidnext))
    gm = imap.Gmail(folder)
    res = gm.status(gm.current_folder, '(UIDNEXT UIDVALIDITY)')
    gmfolder = re.search(
        r'(UIDNEXT (?P<uidnext>\d+) ?|UIDVALIDITY (?P<uid>\d+)){2}',
        res[0].decode()
    ).groupdict()
    print('## gmail: uidvalidity=%(uid)s uidnext=%(uidnext)s' % gmfolder)
    if gmfolder['uid'] != uidvalidity:
        uidvalidity = gmfolder['uid']
        uidnext = 1
    res = gm.search('UID %s:*' % uidnext)
    gm.logout()
    uids = [i for i in res[0].split() if int(i) >= uidnext]
    uidnext = gmfolder['uidnext']
    print('## folder(%s): %s new uids' % (gm.current_folder, len(uids)))
    process_batches(fetch_batch, uids, folder)
    con.setmetadata(metakey, '%s,%s' % (uidvalidity, uidnext))
    return uids


def process_batches(func, uids, *args, size=1000):
    if len(uids) < size:
        print('##', func(uids, *args))
        return

    jobs = {}
    with futures.ProcessPoolExecutor(os.cpu_count() * 2) as pool:
        jobs = {
            pool.submit(func, uids[i:i+size], *args): i
            for i in range(0, len(uids), size)
        }
    for f in futures.as_completed(jobs):
        print('##', f.result())


if __name__ == '__main__':
    try:
        fetch_folder()
        fetch_folder('\\Junk')
        fetch_folder('\\Trash')
        parse_folder(sys.argv[-1] if len(sys.argv) > 1 else None)
    except KeyboardInterrupt:
        raise SystemExit('^C')
