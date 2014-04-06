from collections import OrderedDict, defaultdict
from itertools import groupby

from sqlalchemy import func

from . import log, Timer, imap, parser, async_tasks, with_lock
from .db import Email, Label, Task, session

BODY_MAXSIZE = 50 * 1024 * 1024


@with_lock
def sync_gmail(with_bodies=True):
    im = imap.client()

    opts = {
        'INBOX': (-100, False, Label.A_INBOX),
        '\\Flagged': (-90, True, Label.A_STARRED),
        '\\Sent': (-80, True, Label.A_SENT),
        '\\Drafts': (-70, True, Label.A_DRAFTS),
        '\\All': (-60, True, Label.A_ALL),
        '\\Junk': (-50, True, Label.A_SPAM),
        '\\Trash': (-40, True, Label.A_TRASH),
        '\\Important': (-30, True, Label.A_IMPORTANT)
    }
    session.query(Email).update({Email.updated_at: None})
    folders_ = imap.list_(im)
    for index, value in enumerate(folders_):
        attrs, delim, name = value
        lookup = lambda k: name == k if k == 'INBOX' else k in attrs
        folder = [v for k, v in opts.items() if lookup(k)]
        weight, hidden, alias = (
            folder[0] if folder else (0, Label.NOSELECT in attrs, None)
        )
        label = session.query(Label).filter(Label.name == name).first()
        if not label:
            label = Label(attrs=attrs, delim=delim, name=name)
            session.add(label)

        session.query(Label).filter(Label.name == name).update({
            Label.hidden: hidden,
            Label.index: index,
            Label.weight: weight,
            Label.alias: alias
        })

        if Label.NOSELECT in attrs:
            continue
        fetch_emails(im, label, with_bodies)

    # Cleanup labels
    for label in session.query(Label).filter(Label.updated_at == None):
        updated = (
            session.query(Email.id)
            .filter(Email.labels.has_key(str(label.id)))
            .update(
                {Email.labels: Email.labels.delete(str(label.id))},
                synchronize_session=False
            )
        )
        log.info('Cleanup %s emails from label %s', updated, label.id)
        session.delete(label)

    # Restore state
    tasks = (
        session.query(Task)
        .filter(Task.is_new)
        .filter(Task.name.like('mark_%'))
    )
    log.info('Restore state from %s tasks', tasks.count())
    for task in tasks:
        async_tasks.mark(task.name[5:], task.uids)


def fetch_emails(im, label, with_bodies=True):
    timer = Timer()
    msgids, flags = OrderedDict(), defaultdict(list)
    uids = imap.search(im, label.name)
    data = imap.fetch_all(im, uids, 'X-GM-MSGID FLAGS', 1000, quiet=True)
    for k, v in data.items():
        msgid = v['X-GM-MSGID']
        msgids[msgid] = k
        for f in v['FLAGS']:
            flags[f].append(msgid)
    uids_map = {v: k for k, v in msgids.items()}
    flags = OrderedDict(sorted(flags.items()))

    log.info('%s|%d uids|%.2fs', label.name, len(msgids), timer.time())
    if not msgids:
        updated = (
            session.query(Email.id)
            .filter(Email.labels.has_key(str(label.id)))
            .update(
                {Email.labels: Email.labels.delete(str(label.id))},
                synchronize_session=False
            )
        )
        log.info('  * Clean %s label', label.name)
        update_label(label)
        return

    # Fetch properties
    emails = session.query(Email.uid).filter(Email.uid.in_(msgids.keys()))

    # Cleanup flags
    emails.update({Email.flags: {}}, synchronize_session=False)

    msgids_ = sum([[r.uid] for r in emails.all()], [])
    msgids_ = list(set(msgids.keys()) - set(msgids_))
    uids = [v for k, v in msgids.items() if k in msgids_]
    if uids:
        query = OrderedDict([
            ('internaldate', 'INTERNALDATE'),
            ('flags', 'FLAGS'),
            ('size', 'RFC822.SIZE'),
            ('uid', 'X-GM-MSGID'),
            ('gm_msgid', 'X-GM-MSGID'),
            ('gm_thrid', 'X-GM-THRID'),
            ('header', 'BODY[HEADER]'),
        ])
        q = list(query.values())
        for data in imap.fetch(im, uids, q, 1000, 'add emails'):
            emails = []
            for row in data.values():
                header = row.pop(query['header'])
                fields = {k: row[v] for k, v in query.items() if v in row}
                fields['labels'] = {str(label.id): ''}
                fields['flags'] = {str(r): '' for r in fields['flags']}
                if not with_bodies:
                    fields.update(parser.parse(header, fields['uid']))
                emails.append(fields)
            session.execute(Email.__table__.insert(), emails)

    # Update labels
    uids = [k for k, v in msgids.items() if k not in msgids_]
    log.info('  * Update labels for %d emails...', len(uids))
    timer, updated = Timer(), 0
    emails = session.query(Email)
    updated += (
        emails.filter(Email.uid.in_(msgids.keys()))
        .filter(~Email.labels.has_key(str(label.id)))
        .update(
            {Email.labels: Email.labels + {str(label.id): ''}},
            synchronize_session=False
        )
    )
    updated += (
        emails.filter(~Email.uid.in_(msgids.keys()))
        .filter(Email.labels.has_key(str(label.id)))
        .update(
            {Email.labels: Email.labels.delete(str(label.id))},
            synchronize_session=False
        )
    )
    log.info('  - %d ones for %.2fs', updated, timer.time())

    # Update flags
    uids = [k for k, v in msgids.items() if k not in msgids_]
    if uids:
        log.info('  * Update flags for %d emails...', len(uids))
        timer, updated = Timer(), 0
        emails = session.query(Email)
        for flag, uids_ in flags.items():
            updated += (
                emails.filter(Email.uid.in_(uids_))
                .update(
                    {Email.flags: Email.flags + {flag: ''}},
                    synchronize_session=False
                )
            )
        log.info('  - %d ones for %.2fs', updated, timer.time())

    update_label(label)
    if not with_bodies:
        return

    # Fetch bodies
    emails = (
        session.query(Email.uid, Email.size)
        .filter(Email.body == None)
        .filter(Email.uid.in_(msgids.keys()))
        .order_by(Email.uid.desc())
    )
    uids = {msgids[r.uid]: r.size for r in emails.all()}
    if uids:
        step_size, group_size = 0, BODY_MAXSIZE
        step_uids, group_uids = [], []
        for uid, size in uids.items():
            if step_uids and step_size + size > group_size:
                group_uids.append(step_uids)
                step_uids, step_size = [], 0
            else:
                step_uids.append(uid)
                step_size += size
        if step_uids:
            group_uids.append(step_uids)

        for uids_ in group_uids:
            q = 'RFC822'
            data = imap.fetch_all(im, uids_, q, len(uids_), 'update bodies')
            with session.begin(subtransactions=True):
                for uid, row in data.items():
                    update_email(uids_map[uid], row['RFC822'])


def update_label(label):
    emails = (
        session.query(Email.gm_thrid.distinct())
        .filter(Email.labels.has_key(str(label.id)))
    )
    session.query(Label).filter(Label.id == label.id).update({
        'unread': emails.filter(~Email.flags.has_key(Email.SEEN)).count(),
        'exists': emails.count(),
    })


def update_email(uid, raw):
    fields = parser.parse(raw, uid)
    fields['body'] = raw

    fields.pop('files', None)

    session.query(Email).filter(Email.uid == uid)\
        .update(fields, synchronize_session=False)


def mark_emails(name, uids):
    label_all = Label.get_by_alias(Label.A_ALL)
    store = {
        'starred': ('+FLAGS', Email.STARRED),
        'unstarred': ('-FLAGS', Email.STARRED),
        'read': ('+FLAGS', Email.SEEN),
        'unread': ('-FLAGS', Email.SEEN),
    }
    if name in store:
        key, value = store[name]
        im = imap.client()
        im.select('"%s"' % label_all.name, readonly=False)
        imap.store(im, uids, key, value)
        return

    label_in = Label.get_by_alias(Label.A_INBOX)
    label_trash = Label.get_by_alias(Label.A_TRASH)
    emails = session.query(Email.uid, Email.labels).filter(Email.uid.in_(uids))
    emails = {m.uid: m for m in emails}
    if name == 'inboxed':
        im = imap.client()
        for label in [label_all, label_trash]:
            im.select('"%s"' % label.name, readonly=False)
            for uid in uids:
                _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
                if not data[0]:
                    continue
                uid_ = data[0].decode().split(' ')[0]
                res = im.uid('COPY', uid_, '"%s"' % label_in.name)
                log.info(
                    'Copy(%s from %s to %s): %s',
                    uid, label.name, label_in.name, res
                )

    elif name == 'archived':
        im = imap.client()
        im.select('"%s"' % label_in.name, readonly=False)
        for uid in uids:
            _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
            if not data[0]:
                continue
            uid_ = data[0].decode().split(' ')[0]
            res = im.uid('STORE', uid_, '+FLAGS', '\\Deleted')
            log.info('Archive(%s): %s', uid, res)

        im.select('"%s"' % label_trash.name, readonly=False)
        for uid in uids:
            _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
            if not data[0]:
                continue
            uid_ = data[0].decode().split(' ')[0]
            res = im.uid('COPY', uid_, '"%s"' % label_all.name)
            log.info('Archive(%s): %s', uid, res)

    elif name == 'deleted':
        im = imap.client()
        im.select('"%s"' % label_all.name, readonly=False)
        for uid in uids:
            _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
            if not data[0]:
                continue
            uid_ = data[0].decode().split(' ')[0]
            res = im.uid('COPY', uid_, '"%s"' % label_trash.name)
            log.info('Delete(%s): %s', uid, res)

    else:
        raise ValueError('Wrong name for "mark" task: %s' % name)


@with_lock
def process_tasks():
    tasks = (
        session.query(Task)
        .with_for_update(nowait=True, of=Task)
        .filter(Task.is_new)
        .order_by(Task.created_at)
    )
    groups = [(k, list(v)) for k, v in groupby(tasks, lambda v: v.name)]
    sync = [(k, v) for k, v in groups if k == Task.N_SYNC]
    other = [(k, v) for k, v in groups if k != Task.N_SYNC]
    if sync:
        with session.begin(subtransactions=True):
            process_task(*sync[0])

    if not other:
        return

    for task in other:
        with session.begin(subtransactions=True):
            process_task(*task)

        sync_gmail()


def process_task(name, group):
    timer = Timer()
    log.info('### Process %s tasks %r...' % (name, [t.id for t in group]))
    if name == Task.N_SYNC:
        sync_gmail()
    elif name.startswith('mark_'):
        uids = set(sum([t.uids for t in group], []))
        mark_emails(name[5:], uids)

    duration = timer.time()
    for task in group:
        task.is_new = False
        task.duration = duration
        session.merge(task)
        log.info('# Task %s is done for %.2f', task.id, duration)


def parse_emails(new=True, limit=500, last=None):
    emails = session.query(Email)
    if new:
        emails = emails.filter(Email.text == None).filter(Email.html == None)

    if not last:
        last = session.query(func.max(Email.updated_at)).scalar()

    emails = emails.filter(Email.updated_at <= last)
    log.info('* Parse %s emails (%s)...', emails.count(), last)
    i = 0
    timer = Timer()
    while emails.count():
        for email in emails.limit(limit):
            update_email(email.uid, email.body)
            i += 1
        log.info('  - parsed %s ones for %.2f', i, timer.time(reset=False))
