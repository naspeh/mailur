import hashlib
import imaplib
import os
import re

from gevent import socket, ssl

from . import log, imap, imap_utf7, local

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
    '\\Sent': '#sent',
    '\\Important': '#important'
}
MAP_FOLDERS = {
    '\\Junk': local.SPAM,
    '\\Trash': local.TRASH,
}


USER = os.environ.get('GM_USER')
PASS = os.environ.get('GM_PASS')


class Gmail(imaplib.IMAP4, imap.Conn):
    def __init__(self):
        self.username = USER
        self.password = PASS
        self.current_box = None
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


def client(tag='\\All'):
    ctx = imap.client(connect)
    if tag:
        ctx.select_tag(tag)
    return ctx


def fetch_uids(uids, tag, gm, lm):
    fields = (
        '('
        'UID INTERNALDATE FLAGS X-GM-LABELS X-GM-MSGID X-GM-THRID BODY.PEEK[]'
        ')'
    )
    res = gm.fetch(uids.str, fields)

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
            return MAP_LABELS.get(label, None) or local.get_tag(label)
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
                MAP_LABELS.get(tag, ''),
            ]).strip()
            yield parts['time'], flags, raw

    res = lm.multiappend(MAP_FOLDERS.get(tag, local.SRC), msgs())
    log.debug('## %s', res[0].decode())


def fetch_folder(tag='\\All', *, batch=1000, threads=10):
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
    gm = client(tag)
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
    lm = local.client(None)
    if len(uids):
        # messages should be inserted in the particular order
        # for THREAD IMAP extension, so no async here
        uids = imap.Uids(uids, size=batch)
        uids.call(fetch_uids, uids, tag, gm, lm)

    gm.logout()
    lm.setmetadata(local.SRC, metakey, '%s,%s' % (uidvalidity, uidnext))
    lm.logout()


def fetch(**kw):
    fetch_folder(**kw)
    fetch_folder('\\Junk', **kw)
    fetch_folder('\\Trash', **kw)
    fetch_folder('\\Drafts', **kw)
