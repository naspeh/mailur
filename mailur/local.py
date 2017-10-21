import datetime as dt
import email.policy
import functools as ft
import imaplib
import json
import os
import re
from email.message import MIMEPart
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from . import log, imap

USER = os.environ.get('MLR_USER', 'user')

SRC = 'Src'
ALL = 'All'
TRASH = 'Trash'
SPAM = 'Spam'
TAGS = 'Tags'


def connect(user=None):
    user = user or USER
    # disable ACL for getting full access
    cmd = 'doveadm exec imap -u %s -o plugin/acl=vfile:/dev/null' % user
    return imaplib.IMAP4_stream(cmd)


def client(box=ALL):
    ctx = imap.client('Local', connect, dovecot=True, writable=True)
    if box:
        ctx.select(box)
    return ctx


def binary_msg(txt, mimetype='text/plain'):
    msg = MIMEPart()
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


@ft.lru_cache(maxsize=None)
def get_tags(con, reverse=False):
    count = con.select(TAGS)
    if count == [b'0']:
        return {}
    res = con.fetch('1:*', 'BODY.PEEK[1]')
    tags = (
        ('#t%s' % res[i][0].split()[2].decode(), res[i][1].decode())
        for i in range(0, len(res), 2)
    )
    return {v: k for k, v in tags} if reverse else dict(tags)


def get_tag(con, name):
    tag = get_tags(con, reverse=True).get(name)
    if tag is not None:
        return tag
    msg = binary_msg(name)
    msg.add_header('Subject', name)
    res = con.append(TAGS, '', None, msg.as_bytes())
    get_tags.cache_clear()
    tag = re.search(r'\[APPENDUID \d+ (\d+)\]', res[0].decode()).group(1)
    return '#t' + tag


def parsed_uids(con, uids=None):
    if uids is None:
        return fetch_parsed_uids(con)
    return {k: v for k, v in fetch_parsed_uids(con).items() if v in uids}


@ft.lru_cache(maxsize=None)
def fetch_parsed_uids(con):
    con.select(ALL)
    res = con.fetch('1:*', 'BODY.PEEK[1]')
    return {
        res[i][0].split()[2].decode(): res[i][1].decode()
        for i in range(0, len(res), 2)
    }


def create_msg(raw, uid, time):
    # TODO: there is a bug with folding mechanism,
    # like this one https://bugs.python.org/issue30788,
    # so use `max_line_length=None` by now, not sure if it's needed at all
    policy = email.policy.SMTPUTF8.clone(max_line_length=None)
    orig = BytesParser(policy=policy).parsebytes(raw)
    meta = {k.replace('-', '_'): orig[k] for k in ('message-id',)}

    subj = orig['subject']
    meta['subject'] = str(subj) if subj else subj
    meta['uid'] = uid

    date = orig['date']
    meta['date'] = date and parsedate_to_datetime(date).isoformat()

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    meta['arrived'] = arrived.isoformat()

    txt = orig.get_body(preferencelist=('plain', 'html'))
    body = txt.get_content()

    msg = MIMEPart(policy)
    headers = 'from to date message-id cc bcc in-reply-to references'.split()
    for n, v in orig.items():
        if n.lower() not in headers or n.lower() in msg:
            continue
        msg.add_header(n, v)

    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('X-Subject', meta['subject'])
    msg.make_mixed()

    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary_msg(uid, 'application/json'))
    msg.attach(binary_msg(meta_txt, 'application/json'))
    msg.attach(binary_msg(body))
    return msg


def parse_uids(uids):
    con = client(SRC)
    res = con.fetch(uids, '(UID INTERNALDATE FLAGS BODY.PEEK[])')

    def iter_msgs(res):
        for i in range(0, len(res), 2):
            m = res[i]
            uid, time, flags = re.search(
                r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)',
                m[0].decode()
            ).groups()
            flags = flags.replace('\\Recent', '').strip()
            try:
                msg_obj = create_msg(m[1], uid, time)
                msg = msg_obj.as_bytes()
            except Exception as e:
                msgid = re.findall(b'^(?im)message-id:.*', m[1])
                log.exception('## %r uid=%s %s', e, uid, msgid)
                continue
            yield time, flags, msg

    msgs = list(iter_msgs(res))
    try:
        return con.multiappend(ALL, msgs)
    finally:
        con.logout()


def parse(criteria=None, *, batch=1000, threads=4):
    con = client(SRC)
    uidnext = 1
    if criteria is None:
        res = con.getmetadata(ALL, 'uidnext')
        if len(res) > 1:
            uidnext = int(res[0][1].decode())
            log.info('## saved: uidnext=%s', uidnext)
        criteria = 'UID %s:*' % uidnext

    res = con.search(criteria)
    uids = [i for i in res[0].decode().split(' ') if i and int(i) >= uidnext]
    if not uids:
        log.info('## all parsed already')
        return

    res = con.status(SRC, '(UIDNEXT)')
    uidnext = re.search(r'UIDNEXT (?P<next>\d+)', res[0].decode()).group(1)
    log.info('## new: uidnext: %s', uidnext)

    log.info('## criteria: %r; %s uids', criteria, len(uids))
    count = con.select(ALL, readonly=False)
    if count[0] != b'0':
        count = None
        if criteria.lower() == 'all':
            puids = '1:*'
            count = 'all'
        else:
            puids = ','.join(parsed_uids(con, uids))
        if puids:
            count = count or puids.count(',') + 1
            log.info('## delete %s messages from %r', count, ALL)
            con.store(puids, '+FLAGS.SILENT', '\Deleted')
            con.expunge()

    con.logout()
    delayed = imap.delayed_uids(parse_uids, uids)
    imap.partial_uids(delayed, size=batch, threads=threads)

    con = client(None)
    con.setmetadata(ALL, 'uidnext', str(uidnext))

    fetch_parsed_uids.cache_clear()
    update_threads(parsed_uids(con, uids))


def update_threads(uids=None, criteria=None):
    con = client()
    if uids is None:
        uids = con.search(criteria or 'all')[0].decode().split()

    msgs = set()
    thrs = {}
    res = con.thread('REFS UTF-8 INTHREAD REFS ALL')
    for thrids in res:
        if not set(thrids).intersection(uids):
            continue
        msgs.update(thrids)
        if len(thrids) == 1:
            latest = thrids[0]
        else:
            res = con.sort('(DATE)', 'UID %s' % ','.join(thrids))
            latest = res[0].decode().rsplit(' ', 1)[-1]
        thrs[latest] = thrids

    con.select(ALL, readonly=False)
    res = con.search('KEYWORD #latest')
    clean = set(res[0].decode().split()).intersection(msgs) - set(thrs)
    if clean:
        con.store(clean, '-FLAGS.SILENT', '#latest')
    con.store(list(thrs), '+FLAGS.SILENT', '#latest')
    log.info('## updated %s threads', len(thrs))
