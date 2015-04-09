from collections import OrderedDict
from uuid import uuid4

from . import imap, imap_utf7, parser, log, Timer, with_lock
from .db import connect, Email


@with_lock
@connect()
def sync_gmail(cur, with_bodies=False, only_labels=None):
    im = imap.client()
    folders = imap.list_(im)
    if not only_labels:
        only_labels = ('\\All', '\\Junk', '\\Trash')
    for attrs, delim, name in folders:
        label = set(only_labels) & set(attrs)
        label = label and label.pop()
        if not label:
            continue

        uids = imap.search(im, name)
        log.info('"%s" has %i messages' % (imap_utf7.decode(name), len(uids)))
        if not uids:
            continue

        data = imap.fetch_all(im, uids, 'X-GM-MSGID')
        uids = OrderedDict((k, v['X-GM-MSGID']) for k, v in data.items())

        fetch_headers(im, uids)
        fetch_labels(im, uids, label)
        if with_bodies:
            fetch_bodies(im, uids)


def get_gids(cur, gids, where=None):
    sql = '''
    SELECT extra->'X-GM-MSGID' msgid FROM emails
      WHERE %(gids)s @> ARRAY[(extra->>'X-GM-MSGID')::bigint]
    '''
    if where:
        sql += ' AND %s' % where
    cur.execute(sql, {'gids': list(gids)})
    gids = [r[0] for r in cur.fetchall()]
    return gids


@connect()
def fetch_headers(cur, im, map_uids):
    gids = get_gids(cur, map_uids.values())
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
    gids = get_gids(cur, map_uids.values(), where='raw IS NULL')
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
def fetch_labels(cur, im, map_uids, folder):
    gids = get_gids(cur, map_uids.values())
    update_label(cur, gids, folder)

    # TODO: should find faster way
    uids = [uid for uid, gid in map_uids.items() if gid in gids]
    if not uids:
        return

    data = imap.fetch_all(im, uids, 'X-GM-LABELS FLAGS')
    glabels, gflags = set(), set()
    for row in data.values():
        glabels |= set(row['X-GM-LABELS'])
        gflags |= set(row['FLAGS'])
    log.info('  * Unique labels %r', glabels)
    log.info('  * Unique flags %r', gflags)

    labels = [
        (imap_utf7.decode(l), [l], lambda row, l: l in row['X-GM-LABELS'])
        for l in glabels
    ] + [
        ('\\Answered', [], (lambda row: '\\Answered' in row['FLAGS'])),
        ('\\Unread', [], (lambda row: '\\Seen' not in row['FLAGS'])),
    ]
    for label, args, func in labels:
        gids = [map_uids[uid] for uid, row in data.items() if func(row, *args)]
        update_label(cur, gids, label, folder)


def update_label(cur, gids, label, folder=None):
    def step(action, sql):
        t = Timer()
        sql += ('AND labels @> ARRAY[%(folder)s::varchar]' if folder else '')
        cur.execute(sql, {'label': label, 'gids': gids, 'folder': folder})
        log.info('  - %s %d emails for %.2fs', action, cur.rowcount, t.time())

    log.info('  * Process %r...', label)
    step('remove from', '''
    UPDATE emails SET labels=array_remove(labels, %(label)s)
      WHERE NOT (%(gids)s @> ARRAY[(extra->>'X-GM-MSGID')::bigint])
      AND labels @> ARRAY[%(label)s::varchar]
    ''')

    step('add to', '''
    UPDATE emails SET labels=(labels || %(label)s::varchar)
      WHERE %(gids)s @> ARRAY[(extra->>'X-GM-MSGID')::bigint]
      AND NOT (labels @> ARRAY[%(label)s::varchar])
    ''')
