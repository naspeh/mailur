import re
import time
import uuid
from contextlib import contextmanager
from multiprocessing import Pool
from multiprocessing.dummy import Pool as ThreadPool

import psycopg2
import rapidjson as json
import requests

from . import imap_utf7, parser, log
from .helpers import Timer, with_lock
from .imap import Client

# Only these folders contain unique emails
FOLDERS = ('\\All', '\\Spam', '\\Trash')
ALIASES = {
    'INBOX': '\\Inbox',
    '\\Junk': '\\Spam',
    '\\Starred': '\\Pinned'
}
THRID = 'mlr/thrid'


def sync_gmail(env, email, force=False, **kw):
    func = _sync_gmail
    target = ':'.join([func.__name__, email, 'fast:%s' % bool(kw.get('fast'))])

    with with_lock(target, timeout=30, force=force):
        return Timer(target)(func)(env, email, **kw)


def _sync_gmail(env, email, fast=True, only=None):
    imap = Client(env, email)
    folders = imap.folders()
    if not only:
        only = FOLDERS

    for attrs, delim, name in folders:
        label = set(only) & set(ALIASES.get(l, l) for l in (attrs + (name,)))
        label = label and label.pop()
        if not label:
            continue

        imap.select(name, env('readonly'))
        folder_id = imap.status(name, 'UIDVALIDITY')
        uid_start = env.storage('folder', uid=folder_id)
        uid_end = imap.status(name, 'UIDNEXT')
        uids = imap.search(name, uid_start.get() if fast else None)
        uid_start.set(uid_end)

        id2uid, new = map_ids(env, imap, uids)
        log.info('"{name}" has {count} {new}messages'.format(
            name=imap_utf7.decode(name),
            count=len(new),
            new='new ' if fast else ''
        ))
        if new or id2uid:
            id2uid.update(fetch_headers(env, imap, new))
            with_clean = label in FOLDERS and not fast
            fetch_labels(env, imap, id2uid, label, with_clean)
            if label in FOLDERS:
                sync_marks(env, imap, id2uid)
            update_thrids(env, label)
            fetch_bodies(env, imap, id2uid)

    env.storage.set('last_sync', time.time())
    notify(env, [], True)
    return uids


def search(env, email, query):
    imap = Client(env, email)
    folder = [n for a, d, n in imap.folders() if '\\All' in a][0]
    imap.select(folder, True)

    # http://stackoverflow.com/questions/9997928
    query = '"%s"' % query.replace('"', '\\"')
    imap.im.literal = query.encode()
    _, data = imap.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW')
    if not data[0]:
        return []

    uids = data[0].decode().split(' ')
    ids, _ = map_ids(env, imap, uids)
    return list(ids.values())


def map_ids(env, imap, uids):
    if not uids:
        return {}, []

    q = 'X-GM-MSGID'
    data = imap.fetch(uids, [q])
    gid2uid = dict((str(v[q]), k) for k, v in data)

    i = env.sql('''
    SELECT extid, id, duplicate FROM emails WHERE extid = ANY(%s::varchar[])
    ''', [list(gid2uid.keys())])
    exists, new = {}, list(uids)
    for row in i:
        new.remove(gid2uid[row['extid']])
        if not row['duplicate']:
            exists[gid2uid[row['extid']]] = row['id']

    return exists, new


def get_parsed(env, data, msgid=None):
    def format_addr(v):
        if not v[0]:
            v = (v[1].split('@')[0], v[1])
        return '"{}" <{}>'.format(*v)

    def clean(key, value):
        if not value:
            if key in ('to', 'fr', 'cc', 'bcc', 'reply_to', 'sender', 'refs'):
                return []
            return value
        elif key in ('to', 'fr', 'cc', 'bcc', 'reply_to', 'sender'):
            return [format_addr(v) for v in value]
        elif key in ('msgid', 'in_reply_to'):
            return value.strip()
        elif key in ('attachments',):
            return json.dumps(value)
        elif key in ('refs',):
            return ['<%s>' % v for v in re.split('[<>\s]+', value) if v]
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
    msg = parser.parse(env, data, msgid)
    return ((field, clean(field, msg[key])) for key, field in pairs)


def fetch_headers(env, imap, uids):
    if not uids:
        log.info('  * No headers to fetch')
        return {}

    q = ['INTERNALDATE', 'RFC822.SIZE', 'RFC822.HEADER', 'X-GM-MSGID']
    for data in imap.fetch_batch(uids, q, 'add emails with headers'):
        ids = []
        for uid, row in data:
            extid = row['X-GM-MSGID']
            id = env.sql("SELECT nextval('seq_emails_id')").fetchone()[0]
            fields = {
                'id': id,
                'header': row['RFC822.HEADER'],
                'size': row['RFC822.SIZE'],
                'time': row['INTERNALDATE'],
                'extid': extid,
                'delid': uuid.uuid5(
                    uuid.NAMESPACE_URL, '%s\r%s' % (imap.email, extid)
                ),
            }
            fields.update(get_parsed(env, fields['header'], id))
            try:
                id = env.emails.insert(fields)
            except psycopg2.IntegrityError:
                env.db.rollback()
                ref = env.sql('''
                SELECT id FROM emails WHERE msgid=%s
                ''', [fields['msgid']]).fetchone()[0]
                del fields['msgid']
                fields['duplicate'] = ref
                id = env.emails.insert(fields)
                env.db.commit()
            else:
                env.db.commit()
                ids.append((uid, id[0]))
    return ids


@contextmanager
def async_runner(count=0, threads=True):
    if count:
        pool = ThreadPool(count) if threads else Pool(count)
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


def fetch_bodies(env, imap, uid2id):
    i = env.sql('''
    SELECT id, size FROM emails
    WHERE id = ANY(%(ids)s) AND raw IS NULL
    ''', {'ids': list(uid2id.values())})
    pairs = dict(i)

    uids = [(uid, pairs[id]) for uid, id in uid2id.items() if id in pairs]
    if not uids:
        log.info('  * No bodies to fetch')
        return

    results = []

    def update(env, items):
        ids = []
        for data, id in items:
            data_ = dict(get_parsed(env, data, id), raw=data)
            ids += update_email(env, data_, 'id=%s', [id])

        env.db.commit()
        notify(env, ids)
        results.append(len(ids))

    q = 'BODY.PEEK[]'
    with async_runner(env('async_pool')) as run:
        for data in imap.fetch_batch(uids, q, 'add bodies'):
            items = [(row[q], uid2id[uid]) for uid, row in data]
            run(update, env, items)

    log.info('  * Done %s bodies', sum(results))


def update_email(env, row, where, params):
    doc = []
    for lang in env('search_lang'):
        people = sum((row[key] for key in ['fr', 'to', 'cc', 'bcc']), [])
        msgids = [row['msgid'], row['in_reply_to']] + row['refs']
        msgids = [i for i in msgids if i]
        doc.append(
            env.mogrify('''
            setweight(to_tsvector(%(lang)s, %(subj)s), 'A') ||
            setweight(to_tsvector(%(lang)s, %(text)s), 'C') ||
            setweight(to_tsvector(%(lang)s, %(people)s), 'D') ||
            setweight(to_tsvector(%(lang)s, %(msgids)s), 'D') ||
            setweight(to_tsvector(%(lang)s, %(files)s), 'D')
            ''', {
                'lang': lang,
                'subj': row['subj'],
                'text': row['text'],
                'people': '\\n'.join(people),
                'msgids': '\\n'.join(msgids),
                'files': json.dumps(row['attachments'])
            })
        )

    doc = ' || '.join(doc)
    where = env.mogrify(where, params)
    env.sql('UPDATE emails SET search=({}) WHERE {}'.format(doc, where))
    return env.emails.update(row, where)


def fetch_labels(env, imap, uid2id, folder, clean=True):
    updated, glabels = [], set()

    ids = list(uid2id.values())
    updated += update_label(env, ids, folder, None, clean)
    if folder not in FOLDERS:
        updated += update_label(env, ids, '\\All', folder, clean)

    uids = list(uid2id.keys())
    if uids:
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
            ids = [uid2id[uid] for uid, row in data if func(row, *args)]
            label = ALIASES.get(label, label)
            updated += update_label(env, ids, label, folder, clean)

    if clean:
        glabels_ = {ALIASES.get(l, l) for l in glabels}
        updated += clean_labels(env, glabels_, folder)

    # Process saved task without notification
    process_tasks(env)

    env.db.commit()
    notify(env, updated)


def clean_labels(env, labels, folder):
    labels |= {'\\Answered', '\\Unread', folder}
    labels = [imap_utf7.decode(l) for l in labels]

    # Sorted array intersection
    new_labels = env.mogrify('''
    SELECT ARRAY(
      SELECT i FROM (
        SELECT unnest(labels)
        INTERSECT
        SELECT unnest(%s)
      ) AS dt(i)
      ORDER BY 1
    )
    ''', [labels])
    sql = '''
    UPDATE emails SET labels=({0}), thrid=NULL
    WHERE (SELECT ARRAY(SELECT unnest(labels) ORDER BY 1)) != ({0})
    AND %s = ANY(labels)
    RETURNING id
    '''.format(new_labels)
    i = env.sql(sql, [folder])
    log.info('  * Clean %d emails', i.rowcount)
    return tuple(r[0] for r in i)


def process_tasks(env):
    updated = []
    tasks = env.sql('''
    SELECT value FROM storage
    WHERE key LIKE 'task:mark:%'
    ORDER BY created
    ''').fetchall()
    log.info('  * Process %s tasks', len(tasks))
    for row in tasks:
        data = row[0]
        updated += mark(env, data['action'], data['name'], data['ids'])
        log.info('  - done %s', data)
    return updated


def mark(env, action, name, ids, new=False, inner=False):
    if not name or not ids:
        return []
    if not isinstance(name, str):
        return sum((mark(env, action, n, ids, new, inner) for n in name), [])

    ids = tuple(ids)
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
    clean = {
        ('+', '\\Trash'): [('-', ['\\All', '\\Inbox', '\\Spam'])],
        ('+', '\\Spam'): [('-', ['\\All', '\\Inbox', '\\Trash'])],
        ('+', '\\Inbox'): [
            ('-', ['\\Trash', '\\Spam']),
            ('+', '\\All')
        ],
        ('-', THRID): [clean_thrid]
    }
    instead = {
        ('-', '\\Trash'): ('+', '\\Inbox'),
        ('-', '\\Spam'): ('+', '\\Inbox'),
    }

    if not inner:
        action, name = instead.get((action, name), (action, name))
        extra = clean.get((action, name), [])
        for row in extra:
            if callable(row):
                row(env, ids)
                continue
            mark(env, *row, ids=ids, inner=True)

    i = env.sql(actions[action], {'name': name, 'ids': ids})
    updated = [r[0] for r in i]
    if new:
        env.emails.update({'thrid': None}, 'id IN %s', [ids])
        updated += update_thrids(env, commit=False)

        env.add_tasks([{'action': action, 'name': name, 'ids': ids}])
        env.db.commit()
        notify(env, updated)
    return updated


def sync_marks(env, imap, uid2id):
    if not uid2id:
        return

    log.info('  * Sync marks')
    store = {
        ('+', '\\Unread'): ('-FLAGS', '\\Seen'),
        ('-', '\\Unread'): ('+FLAGS', '\\Seen'),
        '\\Pinned': ('FLAGS', '\\Flagged'),
        '\\Spam': ('X-GM-LABELS', '\\Spam'),
    }
    tasks = env.sql('''
    SELECT key, value FROM storage
    WHERE key LIKE 'task:mark:%'
    ORDER BY created
    ''').fetchall()
    ids = tuple(uid2id.values())
    for task_id, t in tasks:
        emails = env.sql('''
        SELECT id FROM emails WHERE id IN %s AND id IN %s
        ''', [ids, tuple(t['ids'])]).fetchall()
        ids_ = [r['id'] for r in emails]
        uids = [uid for uid, id in uid2id.items() if id in ids_]
        if not uids:
            return

        default = ('X-GM-LABELS', t['name'])
        key, value = store.get(t['name'], default)
        key = t['action'] + key
        key, value = store.get((t['action'], t['name']), (key, value))
        value = [value] if isinstance(value, str) else value
        value = (imap_utf7.encode(v) for v in value)
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

        env.sql('DELETE FROM storage WHERE key = %s', [task_id])


def notify(env, ids, last_sync=False):
    if (not ids and not last_sync):
        return

    url = 'http://localhost:9000/notify/'
    d = json.dumps({
        'notify': True,
        'ids': list(set(ids)),
        'last_sync': last_sync
    })
    try:
        requests.post(url, data=d, timeout=5, auth=(env.username, env.token))
    except IOError as e:
        log.error(e)


def update_label(env, gids, label, folder=None, clean=True):
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
    if clean:
        step('remove from', '''
        UPDATE emails SET thrid=NULL, labels=array_remove(labels, %(label)s)
        WHERE NOT (id = ANY(%(gids)s)) AND %(label)s = ANY(labels)
        ''')

    step('add to', '''
    UPDATE emails SET thrid=NULL, labels=(labels || %(label)s::varchar)
    WHERE id = ANY(%(gids)s) AND NOT (%(label)s = ANY(labels))
    ''')
    return step.ids


def update_thrids(env, folder=None, manual=True, commit=True):
    where = (
        env.mogrify('%s = ANY(labels)', [folder])
        if folder else
        env.mogrify('labels && %s::varchar[]', [list(FOLDERS)])
    )
    emails = env.sql('''
    SELECT id, fr, labels, array_prepend(in_reply_to, refs) AS refs
    FROM emails WHERE thrid IS NULL AND {where} ORDER BY time
    '''.format(where=where)).fetchall()
    log.info('  * Update thread ids for %s emails', len(emails))

    t, updated = Timer(), []
    for row in emails:
        refs = [r for r in row['refs'] if r]
        thrid = None
        if not folder:
            folder = (set(FOLDERS) & set(row['labels'])).pop()

        m_label = [l for l in row['labels'] if l.startswith('%s/' % THRID)]
        if manual and m_label:
            # Manual thread
            extid = m_label.pop().replace('%s/' % THRID, '')
            i = env.sql('SELECT id FROM emails WHERE extid=%s', [extid])
            thrid = i.fetchone()[0]
        elif row['fr'][0].endswith('<mailer-daemon@googlemail.com>'):
            # Failed delivery
            text = env.sql('SELECT text FROM emails WHERE id=%s', [row['id']])
            text = text.fetchone()[0]
            msgid = re.search('(?m)^Message-ID:(.*)$', text)
            if msgid:
                msgid = msgid.group(1).strip()
                parent = env.sql('''
                SELECT thrid FROM emails
                WHERE msgid=%(msgid)s AND %(folder)s = ANY(labels)
                LIMIT 1
                ''', {'msgid': msgid, 'folder': folder}).fetchall()
                thrid = parent[0][0] if parent else None
        elif not refs:
            pass
        else:
            parent = env.sql('''
            SELECT thrid FROM emails
            WHERE msgid = %(ref)s AND %(folder)s = ANY(labels)
            LIMIT 1
            ''', {'ref': refs[0], 'folder': folder}).fetchall()
            if not parent:
                parent = env.sql('''
                SELECT thrid FROM emails
                WHERE
                    msgid = ANY(%(refs)s::varchar[])
                    AND %(folder)s = ANY(labels)
                ORDER BY time DESC
                LIMIT 1
                ''', {'refs': refs, 'folder': folder}).fetchall()
            thrid = parent[0][0] if parent else None

        if thrid is None:
            thrid = row['id']
        env.emails.update({'thrid': thrid}, 'id=%s', [row['id']])
        updated.append(row['id'])

    if updated:
        env.db.commit()
        log.info('  - for %.2fs', t.time())
    return updated


def failed_delivery(env, folder):
    emails = env.sql('''
    SELECT id, text FROM emails
    WHERE fr[1] LIKE '%%<mailer-daemon@googlemail.com>' AND %s = ANY(labels)
    ORDER BY time
    ''', [folder])
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

    log.info('  - merge threads by failed delivery: %s', ids)
    return ids


def clean_thrid(env, ids):
    i = env.sql('''
    SELECT unnest(labels), array_agg(id)::text[] FROM emails
    WHERE id = ANY(%s)
    GROUP BY 1
    ''', [list(ids)])

    for row in i:
        label = row[0]
        if not label.startswith('%s/' % THRID):
            continue
        mark(env, '-', label, row[1], new=True)


def mark_thread(env, thrid, ids):
    clean_thrid(env, ids)
    mark(env, '+', [THRID, '%s/%s' % (THRID, thrid)], ids, new=True)


def new_thread(env, id):
    thrid, extid = env.sql('''
    SELECT thrid, extid FROM emails WHERE id=%s LIMIT 1
    ''', [id]).fetchone()

    parent_ids = env.emails.update({'thrid': None}, 'thrid = %s', [thrid])
    env.emails.update({'thrid': id}, 'id = %s', [id])
    update_thrids(env, manual=False, commit=False)

    i = env.sql('SELECT id FROM emails WHERE thrid=%s', [id])
    ids = [r[0] for r in i]
    mark_thread(env, extid, ids)

    parent_ids = tuple(set(parent_ids) - set(ids))
    env.emails.update({'thrid': None}, 'thrid IN %s', [parent_ids])
    update_thrids(env, manual=True, commit=True)


def merge_threads(env, ids):
    thrid, extid = env.sql('''
    SELECT thrid, extid FROM emails WHERE thrid = ANY(%s)
    ORDER BY time LIMIT 1
    ''', [ids]).fetchone()

    i = env.sql('SELECT id FROM emails WHERE thrid = ANY(%s)', [ids])
    ids = [r[0] for r in i]

    mark_thread(env, extid, ids)
    return thrid
