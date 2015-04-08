from collections import OrderedDict
from uuid import uuid4

from . import imap, parser, log
from .db import connect, Email


@connect()
def sync_gmail(cur, with_bodies=False):
    im = imap.client()
    for attrs, delim, name in imap.list_(im):
        if not {'\\All', '\\Junk', '\\Trash'} & set(attrs):
            continue

        uids = imap.search(im, name)
        log.info('"%s" has %i messages' % (name, len(uids)))
        data = imap.fetch_all(im, uids, 'X-GM-MSGID')
        uids = OrderedDict((k, v['X-GM-MSGID']) for k, v in data.items())

        fetch_headers(im, uids)


@connect()
def fetch_headers(cur, im, map_uids):
    cur.execute("SELECT extra#>'{X-GM-MSGID}' msgid FROM emails")
    msgids = [r[0] for r in cur.fetchall()]

    uids = [uid for uid, msgid in map_uids.items() if msgid not in msgids]
    if uids:
        query = {
            'time': 'INTERNALDATE',
            'size': 'RFC822.SIZE',
            'header': 'BODY[HEADER]',
        }
        q = list(query.values())
        for data in imap.fetch(im, uids, q, 'add emails'):
            emails = []
            for uid, row in data.items():
                header = row.pop(query['header'])
                fields = {k: row[v] for k, v in query.items() if v in row}
                fields['id'] = uuid4()
                fields['thrid'] = fields['id']
                fields['extra'] = {'X-GM-MSGID': map_uids[uid]}
                fields.update(parser.parse(header, fields['id']))
                emails.append(fields)
            Email.insert(emails)
