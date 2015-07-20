import re
from collections import OrderedDict
from contextlib import contextmanager
from multiprocessing.dummy import Pool
from uuid import uuid5, NAMESPACE_URL

import requests
import valideer as v

from . import imap_utf7, parser, log
from .helpers import Timer, with_lock
from .imap import Client

# Only these folders contain unique emails
FOLDERS = ('\\All', '\\Junk', '\\Trash')


def locked_sync_gmail(env, *args, **kwargs):
    func = sync_gmail

    with with_lock('%s:%s' % (func.__name__, env.email), timeout=30):
        return Timer(func.__name__)(func)(env, *args, **kwargs)


def sync_gmail(env, bodies=False, only_labels=None, labels=None):
    imap = Client(env)
    folders = imap.folders()
    if not only_labels:
        only_labels = FOLDERS

    labels_ = labels or {}
    for attrs, delim, name in folders:
        label = set(only_labels) & set(attrs + (name,))
        label = label and label.pop()
        if not label:
            continue

        imap.select(name, env('imap_readonly'))
        if not labels:
            labels_[name] = get_label_uids(imap, name)
        else:
            imap.status(name)
            log.info('"%s"' % imap_utf7.decode(name))

        uids = labels_[name]
        if not uids:
            continue
        elif bodies:
            fetch_bodies(env, imap, uids)
        else:
            fetch_headers(env, imap, uids)
            fetch_labels(env, imap, uids, label, only_labels == FOLDERS)
            if label in FOLDERS:
                sync_marks(env, imap, uids)
    return labels_


def get_label_uids(imap, name):
    uids = imap.search(name)
    log.info('"%s" has %i messages' % (imap_utf7.decode(name), len(uids)))
    if not uids:
        return None

    q = 'BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]'
    data = imap.fetch(uids, [q])
    uids = OrderedDict(
        (k, parser.parse(v[q])['message-id']) for k, v in data
    )
    return uids


def get_gids(env, gids, where=None):
    sql = 'SELECT msgid FROM emails WHERE msgid = ANY(%(gids)s)'
    if where:
        sql += ' AND %s' % where

    return [r[0] for r in env.sql(sql, {'gids': list(gids)})]


def get_ids(env, msgids):
    sql = 'SELECT msgid, id FROM emails WHERE msgid = ANY(%(msgids)s)'
    return dict(r for r in env.sql(sql, {'msgids': list(msgids)}))


def get_parsed(env, data, msgid=None):
    def format_addr(v):
        if not v[0]:
            v = (v[1].split('@')[0], v[1])
        return '"{}" <{}>'.format(*v)

    def clean(key, value):
        if not value:
            return value
        elif key in ('to', 'fr', 'cc', 'bcc', 'reply_to', 'sender'):
            return [format_addr(v) for v in value]
        else:
            return value

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
    msg = parser.parse(data, msgid, env('path_attachments'))
    return ((field, clean(field, msg[key])) for key, field in pairs)


def fetch_headers(env, imap, map_uids):
    gids = get_gids(env, map_uids.values())
    uids = [uid for uid, gid in map_uids.items() if gid not in gids]
    if not uids:
        log.info('  * No headers to fetch')
        return

    q = ['INTERNALDATE', 'RFC822.SIZE', 'RFC822.HEADER', 'X-GM-MSGID']
    for data in imap.fetch_batch(uids, q, 'add emails with headers'):
        emails = []
        for uid, row in data:
            gm_uid = '%s\r%s' % (env.email, row['X-GM-MSGID'])
            fields = {
                'id': uuid5(NAMESPACE_URL, gm_uid),
                'header': row['RFC822.HEADER'],
                'size': row['RFC822.SIZE'],
                'time': row['INTERNALDATE'],
                'extra': {'X-GM-MSGID': row['X-GM-MSGID']},
            }
            fields.update(get_parsed(env, fields['header'], str(fields['id'])))
            emails.append(fields)
        env.emails.insert(emails)
        env.db.commit()


@contextmanager
def async_runner(count=0):
    if count:
        pool = Pool(count)
        results = []

        def run(func, *a, **kw):
            results.append(pool.apply_async(func, a, kw))

        yield run

        pool.close()
        pool.join()

        [r.get() for r in results]
    else:
        def run(func, *a, **kw):
            func(*a, **kw)

        yield run


def fetch_bodies(env, imap, map_uids):
    i = env.sql('''
    SELECT msgid, size FROM emails
    WHERE msgid = ANY(%(ids)s) AND raw IS NULL
    ''', {'ids': list(map_uids.values())})
    pairs = dict(i)

    uids = [(uid, pairs[mid]) for uid, mid in map_uids.items() if mid in pairs]
    if not uids:
        log.info('  * No bodies to fetch')
        return

    results = []

    def update(env, items):
        map_ids = get_ids(env, [v[1] for v in items])

        ids = []
        for data, msgid in items:
            data_ = dict(get_parsed(env, data, map_ids[msgid]), raw=data)
            ids += env.emails.update(data_, 'msgid=%s', [msgid])
        env.db.commit()
        notify(env, ids)
        results.append(len(ids))

    q = 'BODY.PEEK[]'
    with async_runner(env('async_pool')) as run:
        for data in imap.fetch_batch(uids, q, 'add bodies'):
            items = [(row[q], map_uids[uid]) for uid, row in data]
            run(update, env, items)

    log.info('  * Done %s bodies', sum(results))
    if results:
        refresh_search(env)


def refresh_search(env):
    log.info('Refresh search index')
    env.sql('REFRESH MATERIALIZED VIEW emails_search')
    env.db.commit()


def fetch_labels(env, imap, map_uids, folder, clean=True):
    updated = []
    folder = '\\Inbox' if folder == 'INBOX' else folder

    gids = get_gids(env, map_uids.values())
    updated += update_label(env, gids, folder)
    if folder not in FOLDERS:
        updated += update_label(env, gids, '\\All', folder)

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
        updated += update_label(env, gids, label, folder)

    if clean:
        updated += clean_emails(env, glabels, folder)
    updated += process_tasks(env)

    env.db.commit()
    notify(env, updated)


def clean_emails(env, labels, folder):
    # Sorted array intersection
    new_labels = env.mogrify('''
    SELECT ARRAY(
      SELECT i FROM (
        SELECT unnest(labels)
        INTERSECT
        SELECT unnest(%s)
      ) as dt(i)
      ORDER BY 1
    )
    ''', [list(labels | {'\\Answered', '\\Unread', folder})])
    sql = '''
    UPDATE emails SET labels=({0})
    WHERE (SELECT ARRAY(SELECT unnest(labels) ORDER BY 1)) != ({0})
    AND %s = ANY(labels)
    RETURNING id
    '''.format(new_labels)
    i = env.sql(sql, [folder])
    log.info('  * Clean %d emails', i.rowcount)
    return tuple(r[0] for r in i)


def process_tasks(env):
    updated = []
    tasks = env.sql('SELECT data FROM tasks ORDER BY created').fetchall()
    log.info('  * Process %s tasks', len(tasks))
    for row in tasks:
        data = row['data']
        updated += mark(env, data)
        log.info('  - done %s', data)
    return updated


def mark(env, data, new=False, inner=False):
    def name(value):
        if isinstance(value, str):
            value = [value]
        return list(value)

    schema = v.parse({
        '+action': v.Enum(('+', '-', '=')),
        '+name': v.AdaptBy(name),
        '+ids': [str],
        'old_name': v.AdaptBy(name),
        'thread': v.Nullable(bool, False)
    })
    data = schema.validate(data)
    if not data['ids']:
        return []

    ids = tuple(data['ids'])
    if data['thread']:
        i = env.sql('SELECT id FROM emails WHERE thrid IN %s', [ids])
        ids = tuple(r[0] for r in i)

    if data['action'] == '=':
        if data.get('old_name') is None:
            raise ValueError('Missing parameter "old_name" for %r' % data)
        if data['old_name'] == data['name']:
            return []

        def do(action, name):
            if not name:
                return []
            data = {'action': action, 'ids': ids, 'name': name}
            return mark(env, data, new=True)

        return (
            do('-', set(data['old_name']) - set(data['name'])) +
            do('+', set(data['name']) - set(data['old_name']))
        )

    actions = {
        '-': (
            '''
            UPDATE emails SET labels = array_remove(labels, %(name)s)
            WHERE id IN %(ids)s AND %(name)s=ANY(labels)
            RETURNING id
            '''
        ),
        '+': (
            '''
            UPDATE emails SET labels = (labels || %(name)s::varchar)
            WHERE id IN %(ids)s AND NOT(%(name)s=ANY(labels))
            RETURNING id
            '''
        ),
    }
    updated, tasks = [], []

    clean = {
        ('+', '\\Trash'): [('-', ['\\All', '\\Inbox', '\\Junk'])],
        ('-', '\\Trash'): [('+', ['\\All', '\\Inbox'])],
        ('+', '\\Junk'): [('-', ['\\All', '\\Inbox', '\\Trash'])],
        ('-', '\\Junk'): [('+', ['\\All', '\\Inbox'])],
        ('+', '\\Inbox'): [
            ('-', ['\\Trash', '\\Junk']),
            ('+', '\\All')
        ],
    }

    for label in data['name']:
        extra = [] if inner else clean.get((data['action'], label), [])
        for action, name in extra:
            params = {'action': action, 'name': name, 'ids': ids}
            mark(env, params, inner=True)

        i = env.sql(actions[data['action']], {'name': label, 'ids': ids})
        updated += [r[0] for r in i]

        tasks.append({'data': {
            'action': data['action'],
            'name': label,
            'ids': ids
        }})

    if new:
        env.tasks.insert(tasks)
        env.db.commit()
        notify(env, updated)
    return updated


def sync_marks(env, imap, map_uids):
    log.info('  * Sync marks')
    store = {
        ('+', '\\Unread'): ('-FLAGS', '\\Seen'),
        ('-', '\\Unread'): ('+FLAGS', '\\Seen'),
        '\\Starred': ('FLAGS', '\\Flagged'),
        '\\Junk': ('X-GM-LABELS', '\\Spam'),
    }
    tasks = env.sql('SELECT id, data FROM tasks ORDER BY created').fetchall()
    msgids = tuple(map_uids.values())
    for task_id, t in tasks:
        emails = env.sql('''
        SELECT id, msgid FROM emails WHERE msgid IN %s AND id IN %s
        ''', [msgids, tuple(t['ids'])]).fetchall()
        msgids_ = [r['msgid'] for r in emails]
        uids = [uid for uid, gid in map_uids.items() if gid in msgids_]
        if not uids:
            return

        default = ('X-GM-LABELS', t['name'])
        key, value = store.get(t['name'], default)
        key = t['action'] + key
        key, value = store.get((t['action'], t['name']), (key, value))
        value = [value] if isinstance(value, str) else value
        value = (imap_utf7.decode(v) for v in value)
        value = (
            '"%s"' % v.replace('\\', '\\\\').replace('"', '\\"')
            for v in value
        )
        value = ' '.join(value)
        log.info('  - store (%s %s) for %s ones', key, value, len(uids))
        try:
            imap.uid('STORE', ','.join(uids), key, value)
        except imap.Error as e:
            log.warn('  ! %r', e)
            return

        env.sql('DELETE FROM tasks WHERE id = %s', [task_id])


def notify(env, ids):
    if not ids:
        return

    url = 'http://localhost:9000/notify/'
    data = {'ids': set(ids)}
    try:
        requests.post(url, data=data, timeout=5, auth=(env('token'), ''))
    except IOError as e:
        log.error(e)


def update_label(env, gids, label, folder=None):
    def step(action, sql):
        t = Timer()
        sql += (
            ('  AND %(folder)s = ANY(labels)' if folder else '') +
            'RETURNING id'
        )
        i = env.sql(sql, {'label': label, 'gids': gids, 'folder': folder})
        log.info('  - %s %d emails for %.2fs', action, i.rowcount, t.time())
        step.ids += tuple(r[0] for r in i)
    step.ids = ()

    log.info('  * Process %r...', label)
    step('remove from', '''
    UPDATE emails SET labels=array_remove(labels, %(label)s)
    WHERE NOT (msgid = ANY(%(gids)s)) AND %(label)s = ANY(labels)
    ''')

    step('add to', '''
    UPDATE emails SET labels=(labels || %(label)s::varchar)
    WHERE msgid = ANY(%(gids)s) AND NOT (%(label)s = ANY(labels))
    ''')
    return step.ids


def update_thrids(env):
    log.info('Update thread ids')

    def step(label, sql, args=None, log_ids=False):
        i = env.sql(sql, args)
        log.info('  - for %s emails (%s)', i.rowcount, label)
        env.db.commit()

        ids = tuple(r[0] for r in i)
        notify(env, ids)
        if log_ids and ids:
            log.info('  - ids: %s', ids)
        return ids

    # step('clear', 'UPDATE emails SET thrid = NULL RETURNING id')
    step('no "in_reply_to" and "references"', '''
    UPDATE emails SET thrid = id
    WHERE thrid IS NULL
      AND (in_reply_to IS NULL OR in_reply_to != ALL(SELECT msgid FROM emails))
      AND (refs IS NULL OR NOT (refs && (SELECT array_agg(msgid) FROM emails)))
    RETURNING id
    ''')

    step('flat query by "in_reply_to" and "references"', '''
    UPDATE emails e SET thrid=t.thrid
      FROM emails t
      WHERE (e.in_reply_to = t.msgid OR t.msgid = ANY(e.refs))
        AND e.thrid IS NULL AND t.thrid IS NOT NULL
      RETURNING e.id;
    ''')

    step('reqursive query by "in_reply_to" and "references"', '''
    WITH RECURSIVE thrids(id, msgid, thrid) AS (
      SELECT id, msgid, thrid
      FROM emails WHERE thrid IS NOT NULL
    UNION
      SELECT e.id, e.msgid, t.thrid
      FROM emails e, thrids t
      WHERE (e.in_reply_to = t.msgid OR t.msgid = ANY(e.refs))
        AND e.thrid IS NULL AND t.thrid IS NOT NULL
    )
    UPDATE emails e SET thrid=t.thrid
    FROM thrids t WHERE e.id = t.id AND e.thrid IS NULL
    RETURNING e.id
    ''')

    step('other: thrid=id', '''
    UPDATE emails SET thrid = id
    WHERE thrid IS NULL
    RETURNING id
    ''', log_ids=True)

    step('clear deleted: thrid=id and labels={}', '''
    UPDATE emails set thrid = id, labels='{}'
    WHERE NOT (labels && %s::varchar[]) AND thrid != id AND labels != '{}'
    RETURNING id
    ''', [list(FOLDERS)])

    failed_delivery(env)


def failed_delivery(env):
    emails = env.sql('''
    SELECT id, text FROM emails
    WHERE fr[1] LIKE '%<mailer-daemon@googlemail.com>'
    ORDER BY time
    ''')
    ids = []
    for msg in emails:
        msgid = re.search('(?m)^Message-ID:(.*)$', msg['text'])
        if not msgid:
            continue

        msgid = msgid.group(1).strip()
        thrid = env.sql('''
        SELECT thrid FROM emails WHERE msgid=%s
        ''', [msgid]).fetchall()
        if not thrid:
            continue

        i = env.sql('''
        UPDATE emails SET thrid=%(thrid)s
        WHERE (id=%(id)s OR thrid=%(id)s) AND thrid!=%(thrid)s
        RETURNING id
        ''', {'thrid': thrid[0][0], 'id': msg['id']})
        ids += [r['id'] for r in i]

    if ids:
        env.db.commit()
        notify(env, ids)
        log.info('  - merge threads by failed delivery: %s', ids)
