from collections import OrderedDict
from uuid import uuid4

from . import imap, parser, log
from .db import connect, Email


@connect()
def sync_gmail(cur, with_bodies=False):
    im = imap.client()
    for attrs, delim, name in imap.list_(im):
        if not {'\\All', '\\Junk', '\\Trash'} & set(attrs):
        # if not {'\\Junk', '\\Trash'} & set(attrs):
            continue

        uids = imap.search(im, name)
        log.info('"%s" has %i messages' % (name, len(uids)))
        if not uids:
            continue

        data = imap.fetch_all(im, uids, 'X-GM-MSGID')
        uids = OrderedDict((k, v['X-GM-MSGID']) for k, v in data.items())

        fetch_headers(im, uids)
        if with_bodies:
            fetch_bodies(im, uids)


def get_gids(cur, where=None):
    sql = "SELECT extra->'X-GM-MSGID' msgid FROM emails"
    if where:
        sql += ' WHERE %s' % where
    cur.execute(sql)
    gids = [r[0] for r in cur.fetchall()]
    return gids


@connect()
def fetch_headers(cur, im, map_uids):
    gids = get_gids(cur)
    uids = [uid for uid, gid in map_uids.items() if gid not in gids]
    if not uids:
        return

    query = {
        'time': 'INTERNALDATE',
        'size': 'RFC822.SIZE',
        'header': 'BODY[HEADER]',
    }
    q = list(query.values())
    for data in imap.fetch(im, uids, q, 'add emails with headers'):
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


@connect()
def fetch_bodies(cur, im, map_uids):
    gids = get_gids(cur, where='raw IS NULL')
    uids = [uid for uid, gid in map_uids.items() if gid in gids]
    if not uids:
        return

    for data in imap.fetch(im, uids, 'RFC822', 'add bodies'):
        conn = cur.connection
        for uid, row in data.items():
            lobj = conn.lobject()
            lobj.write(row['RFC822'])
            cur.execute(
                "UPDATE emails SET raw=%s"
                "  WHERE (extra->>'X-GM-MSGID')::bigint=%s",
                ((lobj.oid, map_uids[uid]))
            )
        conn.commit()
