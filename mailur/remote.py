import email
import hashlib
import imaplib
import re
import smtplib

from gevent import socket, ssl

from . import fn_time, imap, imap_utf7, local, lock, log, message, schema

SKIP_DRAFTS = True


@local.setting('remote/account')
def data_account(value):
    schema.validate(value, {
        'type': 'object',
        'properties': {
            'username': {'type': 'string'},
            'password': {'type': 'string'},
            'imap_host': {'type': 'string'},
            'imap_port': {'type': 'integer', 'default': 993},
            'smtp_host': {'type': 'string'},
            'smtp_port': {'type': 'integer', 'default': 587},
        },
        'required': ['username', 'password', 'imap_host', 'smtp_host']
    })
    value = value.copy()
    if value['imap_host'] == 'imap.gmail.com':
        value['gmail'] = True
    return value


@local.setting('remote/uidnext', lambda: {})
def data_uidnext(key, value):
    setting = data_uidnext.get()
    setting[key] = value
    return setting


class Remote(imaplib.IMAP4, imap.Conn):
    def __init__(self):
        account = data_account.get()
        self.username = account['username']
        self.password = account['password']
        self.defaults()
        super().__init__(account['imap_host'], account['imap_port'])

    def _create_socket(self):
        ssl_context = ssl.SSLContext()
        sock = socket.create_connection((self.host, self.port))
        return ssl_context.wrap_socket(sock, server_hostname=self.host)

    def open(self, host='', port=imaplib.IMAP4_SSL_PORT):
        super().open(host, port=imaplib.IMAP4_SSL_PORT)

    def login(self):
        return super().login(self.username, self.password)


def connect():
    con = Remote()
    imap.check(con.login())
    return con


def client(tag=None, box=None):
    ctx = imap.client(connect)
    if box:
        ctx.select(box)
    elif tag:
        ctx.select_tag(tag)
    return ctx


@local.using(local.SRC)
def fetch_imap(uids, box, tag=None, con=None):
    exists = {}
    res = con.fetch('1:*', 'BODY.PEEK[HEADER.FIELDS (X-SHA256)]')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        line = res[i][1].strip()
        if not line:
            continue
        hash = email.message_from_bytes(line)['X-SHA256'].strip()
        exists[hash.strip('<>')] = uid

    def msgs(con):
        account = data_account.get()
        res = con.fetch(uids, '(INTERNALDATE FLAGS BODY.PEEK[])')
        for i in range(0, len(res), 2):
            line, raw = res[i]
            hash = hashlib.sha256(raw).hexdigest()
            if hash in exists:
                continue
            parts = re.search(
                r'('
                r'UID (?P<uid>\d+)'
                r' ?|'
                r'INTERNALDATE (?P<time>"[^"]+")'
                r' ?|'
                r'FLAGS \((?P<flags>[^)]*)\)'
                r' ?){3}',
                line.decode()
            ).groupdict()

            headers = [
                'X-SHA256: <%s>' % hash,
                'X-Remote-Host: <%s>' % account['imap_host'],
                'X-Remote-Login: <%s>' % account['username'],
            ]

            # line break should be in the end, so an empty string here
            headers.append('')
            headers = '\r\n'.join(headers)

            raw = headers.encode() + raw
            yield parts['time'], parts['flags'], raw

    with client(box=box) as c:
        msgs = list(msgs(c))
    if not msgs:
        return None

    return con.multiappend(local.SRC, msgs)


@local.using(local.SRC)
def fetch_gmail(uids, box, tag, con=None):
    map_flags = {
        '\\Answered': '\\Answered',
        '\\Flagged': '\\Flagged',
        '\\Deleted': '\\Deleted',
        '\\Seen': '\\Seen',
        '\\Draft': '\\Draft',
    }
    map_labels = {
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
            return map_flags.get(flag, '')
        return ''

    def label(m):
        label = m.group()
        if label:
            label = label.strip('"').replace('\\\\', '\\')
            label = imap_utf7.decode(label)
            flag = map_labels.get(label, None)
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
                map_labels.get(tag, ''),
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
@lock.user_scope('remote-fetch')
def fetch_folder(box=None, tag=None, **opts):
    if not box and not tag:
        raise ValueError('"box" or "tag" should be specified')

    account = data_account.get()
    uidnext_key = account['imap_host'], account['username'], tag or box
    uidnext_key = ':'.join(uidnext_key)
    uidvalidity, uidnext = data_uidnext.key(uidnext_key, (None, None))
    log.info('## saved: uidvalidity=%s uidnext=%s', uidvalidity, uidnext)
    con = client(tag=tag, box=box)
    folder = {'uidnext': con.uidnext, 'uidval': con.uidvalidity}
    log.info('## remote: uidvalidity=%(uidval)s uidnext=%(uidnext)s', folder)
    if folder['uidval'] != uidvalidity:
        uidvalidity = folder['uidval']
        uidnext = 1
    uids = con.search('UID %s:*' % uidnext)
    uids = [i for i in uids if int(i) >= uidnext]
    uidnext = folder['uidnext']
    log.info('## box(%s): %s new uids', con.box, len(uids))
    con.logout()
    if len(uids):
        uids = imap.Uids(uids, **opts)
        fetch_uids = fetch_gmail if account.get('gmail') else fetch_imap
        uids.call_async(fetch_uids, uids, box, tag)

    data_uidnext(uidnext_key, (uidvalidity, uidnext))


def fetch(**kw):
    if kw.get('tag') or kw.get('box'):
        fetch_folder(**kw)
        return

    for params in get_folders():
        fetch_folder(**dict(kw, **params))


def get_folders():
    account = data_account.get()
    if not account:
        log.info('## no remote account')
        return []

    if account.get('gmail'):
        return [{'tag': '\\All'}, {'tag': '\\Junk'}, {'tag': '\\Trash'}]
    else:
        with client(None) as c:
            if c.select_tag('\\All', exc=False):
                items = [{'tag': '\\All'}]
            else:
                items = [{'box': 'INBOX'}]
                if c.select_tag('\\Sent', exc=False):
                    items.append({'tag': '\\Sent'})
        return items


def send(msg):
    params = message.sending(msg)

    account = data_account.get()
    con = smtplib.SMTP(account['smtp_host'], account['smtp_port'])
    con.ehlo()
    con.starttls()
    con.login(account['username'], account['password'])
    con.sendmail(*params)

    fetch()
    local.parse()
