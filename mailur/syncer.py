from uuid import uuid4

from . import imap, parser, log
from .db import connect, Email


@connect()
def sync_gmail(cur, with_bodies=False):
    im = imap.client()
    for attrs, delim, name in imap.list_(im):
        if not {'\\All', '\\Junk', '\\Trash'} & set(attrs):
            continue

        fetch_emails(im, name, with_bodies)


@connect()
def fetch_emails(cur, im, label, with_bodies=False):
    cur.execute("SELECT extra#>'{X-GM-MSGID}' FROM emails")
    db_uids = [r[0] for r in cur.fetchall()]

    uids = imap.search(im, label)
    log.info('"%s" has %i messages' % (label, len(uids)))
    for data in imap.fetch(im, uids, 'X-GM-MSGID'):
        for uid, row in data.items():
            if row['X-GM-MSGID'] in db_uids:
                uids.remove(uid)

    if uids:
        query = dict([
            ('time', 'INTERNALDATE'),
            ('size', 'RFC822.SIZE'),
            ('header', 'BODY[HEADER]'),
            ('gm_msgid', 'X-GM-MSGID'),
        ])
        q = list(query.values())
        for data in imap.fetch(im, uids, q, 'add emails'):
            emails = []
            for row in data.values():
                header = row.pop(query['header'])
                gm_msgid = row.pop(query['gm_msgid'])
                fields = {k: row[v] for k, v in query.items() if v in row}
                fields['id'] = uuid4()
                fields['thrid'] = fields['id']
                fields['extra'] = {'X-GM-MSGID': gm_msgid}
                if not with_bodies:
                    fields.update(parser.parse(header, fields['id']))
                emails.append(fields)
            Email.insert(emails)
