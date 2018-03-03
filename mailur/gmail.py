import email
import hashlib
import imaplib
import json
import re

from gevent import socket, ssl

from . import imap, imap_utf7, local, log, message, user_lock

MAP_FLAGS = {
    '\\Answered': '\\Answered',
    '\\Flagged': '\\Flagged',
    '\\Deleted': '\\Deleted',
    '\\Seen': '\\Seen',
    '\\Draft': '\\Draft',
}
MAP_LABELS = {
    '\\Drafts': '\\Draft',
    '\\Draft': '\\Draft',
    '\\Starred': '\\Flagged',
    '\\Inbox': '#inbox',
    '\\Junk': '#spam',
    '\\Trash': '#trash',
    '\\Sent': '#sent',
    '\\Chats': '#chats',
    '\\Important': '',
}


class Gmail(imaplib.IMAP4, imap.Conn):
    def __init__(self):
        self.username, self.password = get_credentials()
        self.defaults()
        super().__init__('imap.gmail.com', imaplib.IMAP4_SSL_PORT)

    def _create_socket(self):
        ssl_context = ssl.SSLContext()
        sock = socket.create_connection((self.host, self.port))
        return ssl_context.wrap_socket(sock, server_hostname=self.host)

    def open(self, host='', port=imaplib.IMAP4_SSL_PORT):
        super().open(host, port=imaplib.IMAP4_SSL_PORT)

    def login(self):
        return super().login(self.username, self.password)


def connect():
    con = Gmail()
    imap.check(con.login())
    return con


def client(tag='\\All', box=None):
    ctx = imap.client(connect)
    if box:
        ctx.select(box)
    elif tag:
        ctx.select_tag(tag)
    return ctx


def save_credentials(username, password):
    data = json.dumps([username, password])
    with local.client() as con:
        con.setmetadata(local.SRC, 'gmail/credentials', data)
    email = username if username.count('@') else '%s@gmail.com' % username
    local.save_addrs(message.addresses(email))


def get_credentials():
    with local.client() as con:
        res = con.getmetadata(local.SRC, 'gmail/credentials')
        if len(res) == 1:
            raise ValueError('no credentials for gmail')
    data = res[0][1].decode()
    username, password = json.loads(data)
    return username, password


def fetch_uids(uids, tag, box):
    exists = {}
    with local.client(local.SRC) as con:
        res = con.fetch('1:*', 'BODY.PEEK[HEADER.FIELDS (X-GM-MSGID)]')
        for i in range(0, len(res), 2):
            uid = res[i][0].decode().split()[2]
            line = res[i][1].strip()
            if not line:
                continue
            gid = email.message_from_bytes(line)['X-GM-MSGID'].strip()
            exists[gid.strip('<>')] = uid

    fields = (
        '('
        'UID INTERNALDATE FLAGS BODY.PEEK[] '
        'X-GM-LABELS X-GM-MSGID X-GM-THRID'
        ')'
    )
    with client(tag, box=box) as gm:
        res = gm.fetch(uids.str, fields)
        login = gm.username

    def flag(m):
        flag = m.group()
        if flag:
            return MAP_FLAGS.get(flag, '')
        return ''

    def label(m):
        label = m.group()
        if label:
            label = label.strip('"').replace('\\\\', '\\')
            label = imap_utf7.decode(label)
            flag = MAP_LABELS.get(label, None)
            return local.get_tag(label)['id'] if flag is None else flag
        return ''

    def msgs():
        for i in range(0, len(res), 2):
            line, raw = res[i]
            parts = re.search(
                r'('
                r'UID (?P<uid>\d+)'
                r' ?|'
                r'INTERNALDATE (?P<time>"[^"]+")'
                r' ?|'
                r'FLAGS \((?P<flags>[^)]*)\)'
                r' ?|'
                r'X-GM-LABELS \((?P<labels>.*)\)'
                r' ?|'
                r'X-GM-MSGID (?P<msgid>\d+)'
                r' ?|'
                r'X-GM-THRID (?P<thrid>\d+)'
                r' ?){6}',
                line.decode()
            ).groupdict()
            if not raw or parts['msgid'] in exists:
                # this happens in "[Gmail]/Chats" folder
                continue
            flags = re.sub(r'([^ ])*', flag, parts['flags'])
            flags = ' '.join([
                flags,
                re.sub(r'("[^"]*"|[^" ]*)', label, parts['labels']),
                MAP_LABELS.get(tag, ''),
            ]).strip()

            headers = [
                'X-SHA256: <%s>' % hashlib.sha256(raw).hexdigest(),
                'X-GM-UID: <%s>' % parts['uid'],
                'X-GM-MSGID: <%s>' % parts['msgid'],
                'X-GM-THRID: <%s>' % parts['thrid'],
                'X-GM-Login: <%s>' % login,
            ]
            thrid_re = '(^| )mlr/thrid/\d+'
            thrid = re.search(thrid_re, flags)
            if thrid:
                flags = re.sub(thrid_re, '', flags)
                thrid = thrid.group().strip()
                headers.append('X-Thread-ID: <%s@mailur.link>' % thrid)

            # line break should be in the end, so an empty string here
            headers.append('')
            headers = '\r\n'.join(headers)

            raw = headers.encode() + raw
            yield parts['time'], flags, raw

    msgs = list(msgs())
    if not msgs:
        return None

    with local.client(None) as lm:
        return lm.multiappend(local.SRC, msgs)


@user_lock('gmail-fetch')
def fetch_folder(tag='\\All', *, box=None, **opts):
    log.info('## process %r', tag)
    metakey = 'gmail/uidnext/%s' % tag.strip('\\').lower()
    with local.client(None) as con:
        res = con.getmetadata(local.SRC, metakey)
    if len(res) != 1:
        uidvalidity, uidnext = res[0][1].decode().split(',')
        uidnext = int(uidnext)
    else:
        uidvalidity = uidnext = None
    log.info('## saved: uidvalidity=%s uidnext=%s', uidvalidity, uidnext)
    gm = client(tag, box=box)
    res = gm.status(None, '(UIDNEXT UIDVALIDITY)')
    folder = re.search(
        r'(UIDNEXT (?P<uidnext>\d+) ?|UIDVALIDITY (?P<uid>\d+)){2}',
        res[0].decode()
    ).groupdict()
    log.info('## gmail: uidvalidity=%(uid)s uidnext=%(uidnext)s', folder)
    if folder['uid'] != uidvalidity:
        uidvalidity = folder['uid']
        uidnext = 1
    res = gm.search('UID %s:*' % uidnext)
    uids = [i for i in res[0].decode().split() if int(i) >= uidnext]
    uidnext = folder['uidnext']
    log.info('## box(%s): %s new uids', gm.box, len(uids))
    gm.logout()
    if len(uids):
        uids = imap.Uids(uids, **opts)
        uids.call_async(fetch_uids, uids, tag, box)

    with local.client(None) as lm:
        lm.setmetadata(local.SRC, metakey, '%s,%s' % (uidvalidity, uidnext))
    local.save_msgids()


def fetch(**kw):
    if kw.get('tag') or kw.get('box'):
        fetch_folder(**kw)
        return

    fetch_folder(**kw)
    fetch_folder('\\Junk', **kw)
    fetch_folder('\\Trash', **kw)
