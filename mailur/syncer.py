from collections import OrderedDict
from multiprocessing.dummy import Pool
from uuid import uuid4

from . import imap, imap_utf7, parser, log, Timer, with_lock
from .db import cursor, Email


@with_lock
def sync_gmail(bodies=False, only_labels=None):
    im = imap.client()
    folders = imap.list_(im)
    if not only_labels:
        # Only these folders exist unique emails
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

        q = 'BODY[HEADER.FIELDS (MESSAGE-ID)]'
        data = imap.fetch(im, uids, [q])
        uids = OrderedDict((k, parser.parse(v[q])['msgid']) for k, v in data)

        if bodies:
            fetch_bodies(im, uids)
        else:
            fetch_headers(im, uids)
            fetch_labels(im, uids, label)


def get_gids(cur, gids, where=None):
    sql = 'SELECT msgid FROM emails WHERE msgid = ANY(%(gids)s)'
    if where:
        sql += ' AND %s' % where

    cur.execute(sql, {'gids': list(gids)})
    gids = [r[0] for r in cur.fetchall()]
    return gids


@cursor()
def fetch_headers(cur, im, map_uids):
    gids = get_gids(cur, map_uids.values())
    uids = [uid for uid, gid in map_uids.items() if gid not in gids]
    if not uids:
        log.info('  - no headers to fetch')
        return

    q = ['INTERNALDATE', 'RFC822.SIZE', 'BODY[HEADER]', 'X-GM-MSGID']
    for data in imap.fetch_batch(im, uids, q, 'add emails with headers'):
        emails = []
        for uid, row in data:
            fields = {
                'id': uuid4(),
                'size': row['RFC822.SIZE'],
                'time': row['INTERNALDATE'],
                'extra': {'X-GM-MSGID': row['X-GM-MSGID']}
            }
            fields['thrid'] = fields['id']
            fields.update(parser.parse(row['BODY[HEADER]'], fields['id']))
            emails.append(fields)
        Email.insert(cur, emails)
        cur.connection.commit()


@cursor()
def fetch_bodies(cur, im, map_uids):
    gids = get_gids(cur, map_uids.values(), where='raw IS NULL')
    uids = [uid for uid, gid in map_uids.items() if gid in gids]
    if not uids:
        log.info('  - no bodies to fetch')
        return

    @cursor()
    def update(cur, items):
        cur.executemany("UPDATE emails SET raw=%s WHERE msgid=%s", items)

    pool = Pool(4)
    results = []
    for data in imap.fetch_batch(im, uids, 'RFC822', 'add bodies'):
        items = ((row['RFC822'], map_uids[uid]) for uid, row in data)
        results.append(pool.apply_async(update, (items,)))
    [r.get() for r in results]
    pool.close()
    pool.join()


@cursor()
def fetch_labels(cur, im, map_uids, folder):
    gids = get_gids(cur, map_uids.values())
    update_label(cur, gids, folder)

    uids = [uid for uid, gid in map_uids.items() if gid in gids]
    if not uids:
        log.info('  - no labels to update')
        return

    data = tuple(imap.fetch(im, uids, 'X-GM-LABELS FLAGS'))
    glabels, gflags = set(), set()
    for _, row in data:
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
        gids = [map_uids[uid] for uid, row in data if func(row, *args)]
        update_label(cur, gids, label, folder)


def update_label(cur, gids, label, folder=None):
    def step(action, sql):
        t = Timer()
        sql += (' AND %(folder)s = ANY(labels)' if folder else '')
        cur.execute(sql, {'label': label, 'gids': gids, 'folder': folder})
        log.info('  - %s %d emails for %.2fs', action, cur.rowcount, t.time())

    log.info('  * Process %r...', label)
    step('remove from', '''
    UPDATE emails SET labels=array_remove(labels, %(label)s)
      WHERE NOT (msgid = ANY(%(gids)s))
      AND %(label)s = ANY(labels)
    ''')

    step('add to', '''
    UPDATE emails SET labels=(labels || %(label)s::varchar)
      WHERE msgid = ANY(%(gids)s)
      AND NOT (%(label)s = ANY(labels))
    ''')
