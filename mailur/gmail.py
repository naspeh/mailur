import hashlib
import imaplib
import os
import re

from . import log, imap, local

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
    '\\Junk': '#spam',
    '\\Trash': '#trash',
    '\\Inbox': '#inbox',
    '\\Sent': '#sent',
    '\\Important': '#important'
}


USER = os.environ.get('GM_USER')
PASS = os.environ.get('GM_PASS')


def connect():
    con = imaplib.IMAP4_SSL('imap.gmail.com')
    imap.check(con.login(USER, PASS))
    return con


def client(tag='\\All'):
    class Gmail:
        def __repr__(self):
            return self.str()

        def __str__(self):
            return self.str()

    ctx = Gmail()
    imap.client_readonly(ctx, connect)

    if tag:
        ctx.select_tag(tag)
    return ctx


def fetch_uids(uids, tag):
    gm = client(tag)
    fields = (
        '('
        'UID INTERNALDATE FLAGS X-GM-LABELS X-GM-MSGID X-GM-THRID BODY.PEEK[]'
        ')'
    )
    res = gm.fetch(uids, fields)
    gm.logout()

    def flag(m):
        flag = m.group()
        if flag:
            return MAP_FLAGS.get(flag, '')
        return ''

    def label(m):
        label = m.group()
        if label:
            label = label.strip('"').replace('\\\\', '\\')
            return MAP_LABELS.get(label, None) or local.get_tag(lm, label)
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
                dict({'\\All': ''}, **MAP_LABELS).get(tag),
            ]).strip()
            yield parts['time'], flags, raw

    lm = local.client(local.ALL)
    msgs = list(iter_msgs(res))
    res = lm.multiappend(local.ALL, msgs)
    lm.logout()
    return res


def fetch_folder(tag='\\All'):
    log.info('## process %r', tag)
    con = local.client()
    metakey = 'gmail/uidnext/%s' % tag.strip('\\').lower()
    res = con.getmetadata(local.ALL, metakey)
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
    log.info('## box(%s): %s new uids', gm.box(), len(uids))
    gm.logout()
    con.logout()
    delayed = imap.delayed_uids(fetch_uids, uids, tag)
    imap.partial_uids(delayed, size=1000, threads=8)
    con = local.client(None)
    res = con.setmetadata(local.ALL, metakey, '%s,%s' % (uidvalidity, uidnext))
    return uids


def fetch():
    fetch_folder()
    fetch_folder('\\Junk')
    fetch_folder('\\Trash')
    fetch_folder('\\Drafts')
