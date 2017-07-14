#!/usr/bin/env python3
import datetime as dt
import hashlib
import imaplib
import json
import os
import re
import sys
from concurrent import futures
from contextlib import contextmanager
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
GM_USER = os.environ.get('GM_USER')
GM_PASS = os.environ.get('GM_PASS')
IMAP_DEBUG = int(os.environ.get('IMAP_DEBUG', 1))


def binary_msg(txt, mimetype='text/plain'):
    msg = MIMEPart(SMTPUTF8)
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def connect():
    from imaplib import CRLF

    con = imaplib.IMAP4('localhost', 143)
    con.login('%s*root' % USER, 'root')
    # con.enable('UTF8=ACCEPT')
    con.debug = IMAP_DEBUG

    @contextmanager
    def cmd(name):
        tag = con._new_tag()
        con.send(b'%s %s ' % (tag, name.encode()))

        yield tag, lambda: con._command_complete(name, tag)

    def multiappend(box, msgs):
        print('## append messages to %s' % box)
        with cmd('APPEND') as (tag, complete):
            con.send(box)
            for time, msg in msgs:
                args = (' () %s %s' % (time, '{%s}' % len(msg))).encode()
                con.send(args + CRLF)
                while con._get_response():
                    if con.tagged_commands[tag]:   # BAD/NO?
                        return tag
                con.send(msg)
            con.send(CRLF)
            return complete()

    def get_key(key):
        if not key.startswith('/private'):
            key = '/private/%s' % key
        return key

    def setmetadata(key, value):
        key = get_key(key)
        with cmd('SETMETADATA') as (tag, complete):
            args = '%s (%s %s)' % (BOX_ALL, key, value)
            con.send(args.encode() + CRLF)
            return complete()

    def getmetadata(key):
        key = get_key(key)
        with cmd('GETMETADATA') as (tag, complete):
            args = '%s (%s)' % (BOX_ALL, key)
            con.send(args.encode() + CRLF)
            typ, data = complete()
            return con._untagged_response(typ, data, 'METADATA')

    con.multiappend = multiappend
    con.getmetadata = getmetadata
    con.setmetadata = setmetadata
    return con


def login_gmail():
    con = imaplib.IMAP4_SSL('imap.gmail.com')
    con.login(GM_USER, GM_PASS)
    return con


def connect_gmail(tag=b'\\All'):
    if isinstance(tag, str):
        tag = tag.encode()
    con = login_gmail()
    con.debug = IMAP_DEBUG
    ok, folders = con.list()
    for f in folders:
        if not re.search(br'^\([^)]*?%s' % re.escape(tag), f):
            continue
        folder = f.rsplit(b' "/" ', 1)[1]
        break
    con.select(folder)
    con.current_folder = folder
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


def parse_batch(uids):
    con = connect()
    con.select(BOX_ALL, readonly=True)
    ok, res = con.fetch(b','.join(uids), '(UID INTERNALDATE BINARY.PEEK[])')

    def iter_msgs(res):
        for i in range(0, len(res), 2):
            m = res[i]
            uid, time = re.search(
                r'UID (\d+) INTERNALDATE ("[^"]+")', m[0].decode()
            ).groups()
            msg = create_msg(m[1], uid, time)
            yield time, msg.as_bytes()

    return con.multiappend(BOX_PARSED.encode(), iter_msgs(res))


def parse_folder(criteria=None):
    con = connect()
    con.select(BOX_ALL, readonly=True)
    uidnext = 1
    if criteria is None:
        ok, res = con.getmetadata('mlr/uidnext')
        if ok == 'OK' and len(res) > 1:
            uidnext = int(res[0][1].decode())
            print('## saved: uidnext=%s' % uidnext)
        criteria = 'UID %s:*' % uidnext

    ok, res = con.uid('SEARCH', None, criteria)
    uids = [i for i in res[0].split(b' ') if i and int(i) >= uidnext]
    if not uids:
        print('## all parsed already')
        return

    ok, res = con.status(BOX_ALL, '(UIDNEXT)')
    uidnext = re.search(r'UIDNEXT (?P<next>\d+)', res[0].decode()).group(1)
    print('## new: uidnext: %s' % uidnext)

    print('## criteria: %r; %s uids' % (criteria, len(uids)))
    ok, count = con.select(BOX_PARSED)
    if count[0] != b'0':
        if criteria.lower() != 'all':
            puids = list(parsed_uids(con, uids))
        else:
            ok, res = con.uid('SEARCH', None, criteria)
            puids = res[0].split(b' ')
        if puids:
            print('## delete %s parsed messages' % len(puids))
            con.uid('STORE', b','.join(puids), '+FLAGS.SILENT', '\Deleted')
            con.expunge()

    process_batches(parse_batch, uids)
    con.setmetadata('mlr/uidnext', str(uidnext))


def process_batches(func, uids, *args, size=1000):
    if len(uids) < size:
        return func(uids, *args)

    jobs = {}
    with futures.ProcessPoolExecutor(os.cpu_count() * 2) as pool:
        jobs = {
            pool.submit(func, uids[i:i+size], *args): i
            for i in range(0, len(uids), size)
        }
    for f in futures.as_completed(jobs):
        print('##', f.result())


def fetch_batch(uids, folder):
    if not uids:
        return
    gm = connect_gmail(folder)
    fields = '(UID INTERNALDATE FLAGS X-GM-LABELS X-GM-MSGID BODY.PEEK[])'
    ok, res = gm.uid('FETCH', b','.join(uids), fields)

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

    con = connect()
    return con.multiappend(BOX_ALL.encode(), iter_msgs(res))



def fetch_folder(folder='\\All'):
    print('## process %s' % folder)
    con = connect()
    metakey = 'gmail/uidnext/%s' % folder.strip('\\').lower()
    ok, res = con.getmetadata(metakey)
    if ok == 'OK' and len(res) != 1:
        uidvalidity, uidnext = res[0][1].decode().split(',')
        uidnext = int(uidnext)
    else:
        uidvalidity = uidnext = None
    print('## saved: uidvalidity=%s uidnext=%s' % (uidvalidity, uidnext))
    gm = connect_gmail(folder)
    ok, res = gm.status(gm.current_folder, '(UIDNEXT UIDVALIDITY)')
    gmfolder = re.search(
        r'(UIDNEXT (?P<uidnext>\d+) ?|UIDVALIDITY (?P<uid>\d+)){2}',
        res[0].decode()
    ).groupdict()
    print('## gmail: uidvalidity=%(uid)s uidnext=%(uidnext)s' % gmfolder)
    if gmfolder['uid'] != uidvalidity:
        uidvalidity = gmfolder['uid']
        uidnext = 1
    ok, res = gm.uid('SEARCH', None, 'UID %s:*' % uidnext)
    gm.logout()
    uids = [i for i in res[0].split() if int(i) >= uidnext]
    uidnext = gmfolder['uidnext']
    print('## folder(%r): %s new uids' % (gm.current_folder, len(uids)))
    process_batches(fetch_batch, uids, folder)
    con.setmetadata(metakey, '%s,%s' % (uidvalidity, uidnext))
    return uids


if __name__ == '__main__':
    try:
        fetch_folder()
        fetch_folder('\\Junk')
        fetch_folder('\\Trash')
        parse_folder(sys.argv[-1] if len(sys.argv) > 1 else None)
    except KeyboardInterrupt:
        raise SystemExit('^C')
