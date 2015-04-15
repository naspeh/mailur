from collections import OrderedDict
from contextlib import contextmanager
from multiprocessing.dummy import Pool
from uuid import uuid4

from . import imap, imap_utf7, parser, log, Timer, with_lock
from .db import cursor, Email


@with_lock
def sync_gmail(bodies=False, only_labels=None):
    folders = imap.list_()
    if not only_labels:
        # Only these folders exist unique emails
        only_labels = ('\\All', '\\Junk', '\\Trash')
    for attrs, delim, name in folders:
        label = set(only_labels) & set(attrs)
        label = label and label.pop()
        if not label:
            continue

        uids = imap.search(name)
        log.info('"%s" has %i messages' % (imap_utf7.decode(name), len(uids)))
        if not uids:
            continue

        q = 'BODY[HEADER.FIELDS (MESSAGE-ID)]'
        data = imap.fetch(uids, [q])
        uids = OrderedDict(
            (k, parser.parse(v[q])['message-id']) for k, v in data
        )

        if bodies:
            fetch_bodies(uids)
        else:
            fetch_headers(uids)
            fetch_labels(uids, label)


def get_gids(cur, gids, where=None):
    sql = 'SELECT msgid FROM emails WHERE msgid = ANY(%(gids)s)'
    if where:
        sql += ' AND %s' % where

    cur.execute(sql, {'gids': list(gids)})
    gids = [r[0] for r in cur.fetchall()]
    return gids


def get_parsed(data, msgid=None):
    pairs = (
        ('subject', 'subj'),
        ('from', 'fr'),
        ('to', 'to'),
        ('cc', 'cc'),
        ('bcc', 'bcc'),
        ('reply-to', 'reply_to'),
        ('sender', 'sender'),
        ('date', 'sender_time'),
        ('message-id', 'msgid'),
        ('in-reply-to', 'in_reply_to'),
        ('references', 'refs'),
        ('html', 'html'),
        ('text', 'text'),
        ('attachments', 'attachments'),
        ('embedded', 'embedded'),
    )
    msg = parser.parse(data, msgid)
    return ((field, msg[key]) for key, field in pairs)


@cursor()
def fetch_headers(cur, map_uids):
    gids = get_gids(cur, map_uids.values())
    uids = [uid for uid, gid in map_uids.items() if gid not in gids]
    if not uids:
        log.info('  - no headers to fetch')
        return

    q = ['INTERNALDATE', 'RFC822.SIZE', 'BODY[HEADER]', 'X-GM-MSGID']
    for data in imap.fetch_batch(uids, q, 'add emails with headers'):
        emails = []
        for uid, row in data:
            fields = {
                'id': uuid4(),
                'header': row['BODY[HEADER]'],
                'size': row['RFC822.SIZE'],
                'time': row['INTERNALDATE'],
                'extra': {'X-GM-MSGID': row['X-GM-MSGID']},
            }
            fields.update(get_parsed(row['BODY[HEADER]'], fields['id']))
            emails.append(fields)
        Email.insert(cur, emails)
        cur.connection.commit()


@contextmanager
def async_runner():
    pool = Pool(4)
    results = []

    def run(func, *a, **kw):
        results.append(pool.apply_async(func, a, kw))

    yield run

    [r.get() for r in results]
    pool.close()
    pool.join()


@cursor()
def fetch_bodies(cur, map_uids):
    sql = '''
    SELECT msgid, size FROM emails
      WHERE msgid = ANY(%(ids)s)
      AND raw IS NULL
    '''
    cur.execute(sql, {'ids': list(map_uids.values())})
    pairs = dict(cur.fetchall())

    uids = [(uid, pairs[mid]) for uid, mid in map_uids.items() if mid in pairs]
    if not uids:
        log.info('  - no bodies to fetch')
        return

    @cursor()
    def update(cur, items):
        cur.executemany("UPDATE emails SET raw=%s WHERE msgid=%s", items)

    with async_runner() as run:
        for data in imap.fetch_batch(uids, 'RFC822', 'add bodies'):
            items = ((row['RFC822'], map_uids[uid]) for uid, row in data)
            run(update, items)


@cursor()
def fetch_labels(cur, map_uids, folder):
    gids = get_gids(cur, map_uids.values())
    update_label(cur, gids, folder)

    uids = [uid for uid, gid in map_uids.items() if gid in gids]
    if not uids:
        log.info('  - no labels to update')
        return

    data = tuple(imap.fetch(uids, 'X-GM-LABELS FLAGS'))
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
