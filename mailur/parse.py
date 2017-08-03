import datetime as dt
import hashlib
import json
import re
import sys
from concurrent import futures
from email.message import MIMEPart
from email.parser import BytesParser
from email.policy import SMTPUTF8
from email.utils import parsedate_to_datetime

from . import imap

GM_FLAGS = {
    '\\Answered': '\\Answered',
    '\\Flagged': '\\Flagged',
    '\\Deleted': '\\Deleted',
    '\\Seen': '\\Seen',
    '\\Draft': '\\Draft',
}
GM_LABELS = {
    '\\Drafts': '\\Draft',
    '\\Junk': '#spam',
    '\\Trash': '#trash',
    '\\Inbox': '#inbox',
    '\\Sent': '#sent',
    '\\Important': '#important'
}


def binary_msg(txt, mimetype='text/plain'):
    msg = MIMEPart(SMTPUTF8)
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def parsed_uids(con, uids=None):
    if uids is None:
        return fetch_parsed_uids(con)
    uids = list(i if isinstance(i, bytes) else i.encode() for i in uids)
    return {k: v for k, v in fetch_parsed_uids(con).items() if v in uids}


def fetch_parsed_uids(con, *, force=False):
    if not hasattr(fetch_parsed_uids, 'cache') or force:
        con.select(con.PARSED)
        res = con.fetch('1:*', 'BINARY.PEEK[1]')
        uids = {
            res[i][0].split()[2]: res[i][1]
            for i in range(0, len(res), 2)
        }
        fetch_parsed_uids.cache = uids
    return fetch_parsed_uids.cache


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
    headers = 'from to date message-id cc bcc in-reply-to references'.split()
    for n in headers:
        v = orig.get(n)
        if not v:
            continue
        msg.add_header(n, v)

    msg.add_header('X-UID', '<%s>' % uid)
    msg.make_mixed()

    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary_msg(uid, 'application/json'))
    msg.attach(binary_msg(meta_txt, 'application/json'))
    msg.attach(binary_msg(body))
    return msg


def parse_batch(uids):
    con = imap.Local()
    res = con.fetch(b','.join(uids), '(UID INTERNALDATE FLAGS BINARY.PEEK[])')

    def iter_msgs(res):
        for i in range(0, len(res), 2):
            m = res[i]
            uid, time, flags = re.search(
                r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)',
                m[0].decode()
            ).groups()
            msg = create_msg(m[1], uid, time)
            flags = flags.replace('\\Recent', '').strip()
            yield time, flags, msg.as_bytes()
    return con.multiappend(iter_msgs(res), box=con.PARSED)


def update_thrids(uids):
    con = imap.Local(None)
    con.select(con.PARSED)
    processed = set()
    threads = {}
    pids_map = parsed_uids(con)
    pids = parsed_uids(con, uids)
    res = con.thread(b'REFS UTF-8 INTHREAD REFS UID %s' % b','.join(pids))
    for thrids in imap.parse_thread(res[0].decode()):
        processed.update(thrids)
        if len(thrids) == 1:
            latest = thrids[0].encode()
        else:
            res = con.sort('(DATE)', 'UTF-8', 'UID %s' % ','.join(thrids))
            latest = res[0].rsplit(b' ', 1)[-1]
        threads[pids_map[latest]] = thrids

    con.select(con.PARSED, readonly=False)
    res = con.fetch(processed, 'FLAGS')
    flags = set()
    for i in res:
        flag = re.search(r'FLAGS \(.*(T:\d+).*\)', i.decode())
        if not flag:
            continue
        flags.add(flag.group(1))
    if flags:
        con.store(','.join(processed), '-FLAGS.SILENT', ' '.join(flags))
    for thrid, ids in threads.items():
        con.store(','.join(ids), '+FLAGS.SILENT', b'T:%s' % thrid)
    print('## updated %s threads' % len(threads))


def parse_folder(criteria=None):
    con = imap.Local()
    uidnext = 1
    if criteria is None:
        res = con.getmetadata(con.PARSED, 'uidnext')
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
    count = con.select(con.PARSED, readonly=False)
    if count[0] != b'0':
        count = None
        if criteria.lower() == 'all':
            puids = '1:*'
            count = 'all'
        else:
            puids = b','.join(parsed_uids(con, uids))
        if puids:
            count = count or puids.count(b',') + 1
            print('## delete %s messages from %r' % (count, con.PARSED))
            con.store(puids, '+FLAGS.SILENT', '\Deleted')
            con.expunge()

    process_batches(parse_batch, uids, pool=futures.ProcessPoolExecutor())
    con = imap.Local(None)
    con.setmetadata(con.PARSED, 'uidnext', str(uidnext))
    fetch_parsed_uids(con, force=True)
    update_thrids(uids)


def fetch_batch(uids, folder):
    gm = imap.Gmail(folder)
    fields = (
        '('
        'UID INTERNALDATE FLAGS X-GM-LABELS X-GM-MSGID X-GM-THRID BODY.PEEK[]'
        ')'
    )
    res = gm.fetch(b','.join(uids), fields)

    def flag(m):
        flag = m.group()
        if flag:
            return GM_FLAGS.get(flag, '')
        return ''

    def label(m):
        label = m.group()
        if label:
            label = label.strip('"').replace('\\\\', '\\')
            return GM_LABELS.get(label, '')
        return ''

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
                r' ?|'
                r'X-GM-THRID (?P<thrid>\d+)'
                r' ?){6}',
                m[0].decode()
            ).groupdict()
            raw = m[1]
            headers = '\r\n'.join([
                'X-SHA256: <%s>' % hashlib.sha256(raw).hexdigest(),
                'X-GM-MSGID: <%s>' % parts['msgid'],
                'X-GM-THRID: <%s>' % parts['thrid'],
                'X-GM-UID: <%s>' % parts['uid'],
                # line break should be in the end, so an empty string here
                ''
            ])
            raw = headers.encode() + raw

            flags = re.sub(r'([^ ])*', flag, parts['flags'])
            flags = ' '.join([
                flags,
                re.sub(r'("[^"]*"|[^" ]*)', label, parts['labels']),
                dict({'\\All': ''}, **GM_LABELS).get(folder),
            ]).strip()
            yield parts['time'], flags, raw

    con = imap.Local(box=None)
    return con.multiappend(iter_msgs(res))


def fetch_folder(folder='\\All'):
    print('## process "%s"' % folder)
    con = imap.Local()
    metakey = 'gmail/uidnext/%s' % folder.strip('\\').lower()
    res = con.getmetadata(con.ALL, metakey)
    if len(res) != 1:
        uidvalidity, uidnext = res[0][1].decode().split(',')
        uidnext = int(uidnext)
    else:
        uidvalidity = uidnext = None
    print('## saved: uidvalidity=%s uidnext=%s' % (uidvalidity, uidnext))
    gm = imap.Gmail(folder)
    res = gm.status(None, '(UIDNEXT UIDVALIDITY)')
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
    print('## folder(%s): %s new uids' % (folder, len(uids)))
    process_batches(fetch_batch, uids, folder)
    con = imap.Local()
    res = con.setmetadata(con.ALL, metakey, '%s,%s' % (uidvalidity, uidnext))
    return uids


def process_batch(num, func, uids, *args):
    res = func(uids, *args)
    print('## %s#%s: %s' % (func.__name__, num, res))
    return res


def process_batches(func, uids, *args, size=1000, pool=None):
    if not uids:
        return
    elif len(uids) < size:
        print('##', func(uids, *args))
        return

    if pool is None:
        pool = futures.ThreadPoolExecutor()

    jobs = []
    with pool as pool:
        for i in range(0, len(uids), size):
            num = '%02d' % (i // size + 1)
            few = uids[i:i+size]
            jobs.append(pool.submit(process_batch, num, func, few, *args))
            print('## %s#%s: %s uids' % (func.__name__, num, len(few)))
    return [f.result() for f in futures.as_completed(jobs)]


if __name__ == '__main__':
    try:
        if imap.GM_USER:
            fetch_folder()
            fetch_folder('\\Junk')
            fetch_folder('\\Trash')
            fetch_folder('\\Drafts')

        parse_folder(sys.argv[-1] if len(sys.argv) > 1 else None)
    except KeyboardInterrupt:
        raise SystemExit('^C')
