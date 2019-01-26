import email
import hashlib
import imaplib
import re

from gevent import socket, ssl

from . import fn_time, imap, imap_utf7, local, log, user_lock

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
SKIP_DRAFTS = True


class Gmail(imaplib.IMAP4, imap.Conn):
    def __init__(self):
        self.username, self.password = data_credentials.get()
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


@local.setting('gmail/credentials', ValueError('no credentials for gmail'))
def data_credentials(username, password):
    return [username, password]


@local.setting('gmail/uidnext', lambda: {})
def data_uidnext(tag, value):
    setting = data_uidnext.get()
    setting[tag] = value
    return setting


@local.using(local.SRC)
@local.using(local.SYS, name=None, parent=True)
def fetch_uids(uids, tag, box, con=None):
    exists = {}
    res = con.fetch('1:*', 'BODY.PEEK[HEADER.FIELDS (X-GM-MSGID)]')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        line = res[i][1].strip()
        if not line:
            continue
        gid = email.message_from_bytes(line)['X-GM-MSGID'].strip()
        exists[gid.strip('<>')] = uid

    new_uids = []
    with client(tag, box=box) as gm:
        res = gm.fetch(uids.str, 'X-GM-MSGID')
        for line in res:
            parts = re.search(
                r'('
                r'UID (?P<uid>\d+)'
                r' ?|'
                r'X-GM-MSGID (?P<msgid>\d+)'
                r' ?){2}',
                line.decode()
            ).groupdict()
            if parts['msgid'] in exists:
                continue
            new_uids.append(parts['uid'])
        if not new_uids:
            log.debug('## %s are alredy imported' % uids)
            return
        fields = (
            '('
            'INTERNALDATE FLAGS BODY.PEEK[] '
            'X-GM-LABELS X-GM-MSGID X-GM-THRID'
            ')'
        )
        res = gm.fetch(new_uids, fields)
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
            if flag is None:
                flag = local.get_tag(label)['id']
            return flag
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
            if SKIP_DRAFTS and '\\Draft' in flags:
                # TODO: skip drafts for now
                continue

            headers = [
                'X-SHA256: <%s>' % hashlib.sha256(raw).hexdigest(),
                'X-GM-UID: <%s>' % parts['uid'],
                'X-GM-MSGID: <%s>' % parts['msgid'],
                'X-GM-THRID: <%s>' % parts['thrid'],
                'X-GM-Login: <%s>' % login,
            ]
            thrid_re = r'(^| )mlr/thrid/\d+'
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

    return con.multiappend(local.SRC, msgs)


@fn_time
@user_lock('gmail-fetch')
def fetch_folder(tag='\\All', *, box=None, **opts):
    uidvalidity, uidnext = data_uidnext.key(tag, (None, None))
    log.info('## saved: uidvalidity=%s uidnext=%s', uidvalidity, uidnext)
    gm = client(tag, box=box)
    folder = {'uidnext': gm.uidnext, 'uidval': gm.uidvalidity}
    log.info('## gmail: uidvalidity=%(uidval)s uidnext=%(uidnext)s', folder)
    if folder['uidval'] != uidvalidity:
        uidvalidity = folder['uidval']
        uidnext = 1
    uids = gm.search('UID %s:*' % uidnext)
    uids = [i for i in uids if int(i) >= uidnext]
    uidnext = folder['uidnext']
    log.info('## box(%s): %s new uids', gm.box, len(uids))
    gm.logout()
    if len(uids):
        uids = imap.Uids(uids, **opts)
        uids.call_async(fetch_uids, uids, tag, box)

    data_uidnext(tag, (uidvalidity, uidnext))


def fetch(**kw):
    if kw.get('tag') or kw.get('box'):
        fetch_folder(**kw)
        return

    fetch_folder(**kw)
    fetch_folder('\\Junk', **kw)
    fetch_folder('\\Trash', **kw)
