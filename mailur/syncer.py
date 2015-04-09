from collections import OrderedDict
from uuid import uuid4

from . import imap, imap_utf7, parser, log, Timer
from .db import connect, Email


@connect()
def sync_gmail(cur, with_bodies=False):
    im = imap.client()
    folders = imap.list_(im)
    for attrs, delim, name in folders:
        if not {'\\All', '\\Junk', '\\Trash'} & set(attrs):
            continue

        uids = imap.search(im, name)
        log.info('"%s" has %i messages' % (imap_utf7.decode(name), len(uids)))
        if not uids:
            continue

        data = imap.fetch_all(im, uids, 'X-GM-MSGID')
        uids = OrderedDict((k, v['X-GM-MSGID']) for k, v in data.items())

        fetch_headers(im, uids)
        fetch_labels(im, uids)
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
        Email.insert(cur, emails)
        cur.connection.commit()


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


@connect()
def fetch_labels(cur, im, map_uids):
    gids = get_gids(cur)
    uids = [uid for uid, gid in map_uids.items() if gid in gids]
    if not uids:
        return

    data = imap.fetch_all(im, uids, 'X-GM-LABELS FLAGS')
    glabels = set(sum((r['X-GM-LABELS'] for r in data.values()), []))
    gflags = set(sum((r['FLAGS'] for r in data.values()), []))
    log.info('  * Unique labels %r', glabels)
    log.info('  * Unique flags %r', gflags)

    timer = Timer()
    labels = [
        (imap_utf7.decode(l), [l], lambda row, l: l in row['X-GM-LABELS'])
        for l in glabels
    ] + [
        ('\\Answered', [], (lambda row: '\\Answered' in row['FLAGS'])),
        ('\\Unread', [], (lambda row: '\\Seen' not in row['FLAGS'])),
    ]
    for label, args, func in labels:
        gids = [map_uids[uid] for uid, row in data.items() if func(row, *args)]
        update_label(cur, gids, label)
        log.info('  * Updated %r for %2fs', label, timer.time())


def update_label(cur, gids, label):
    cur.execute(
        "UPDATE emails SET labels=array_remove(labels, %(label)s)"
        "  WHERE NOT (%(gids)s @> ARRAY[(extra->>'X-GM-MSGID')::bigint])"
        "  AND labels @> ARRAY[%(label)s::varchar]",
        {'label': label, 'gids': gids}
    )
    log.info('  - remove %r from %d emails', label, cur.rowcount)
    cur.execute(
        "UPDATE emails SET labels=(labels || %(label)s::varchar)"
        "  WHERE %(gids)s @> ARRAY[(extra->>'X-GM-MSGID')::bigint]"
        "  AND NOT (labels @> ARRAY[%(label)s::varchar])",
        {'label': label, 'gids': gids}
    )
    log.info('  - add %r to %d emails', label, cur.rowcount)
