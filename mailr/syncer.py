from collections import OrderedDict, defaultdict

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import array

from . import log, Timer, imap
from .parser import parse_header
from .db import Email, Label, session


def sync_gmail(with_bodies=True):
    im = imap.client()

    # Cleaunp t_labels
    session.query(Email).update({Email.t_labels: []})

    weights = {
        'INBOX': 100,
        '\\Flagged': 95,
        '\\Sent': 90,
        '\\Drafts': 85,
        '\\All': 80,
        '\\Junk': 75,
        '\\Trash': 70,
        '\\Important': 0
    }
    folders_ = imap.list_(im)
    for index, value in enumerate(folders_):
        attrs, delim, name = value
        lookup = list(attrs) + [name]
        folder = [v for k, v in weights.items() if k in lookup]
        weight = folder[0] if folder else 0
        label = Label(attrs=attrs, delim=delim, name=name, index=index)
        try:
            session.add(label)
            session.flush()
        except IntegrityError:
            pass

        label = session.query(Label).filter(Label.name == name).one()
        label.is_folder = bool(folder)
        label.weight = weight
        session.merge(label)

        if '\\Noselect' in attrs:
            continue
        fetch_emails(im, label, with_bodies)

    # Update labels
    timer = Timer()
    updated = (
        session.query(Email)
        .filter(Email.labels != Email.t_labels)
        .update({Email.labels: Email.t_labels})
    )
    log.info(' %d updated labels or flags for %.2f', updated, timer.time())


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

    session.query(Label).filter(Label.id == label.id).update({
        'unread': len(msgids.keys()) - len(flags.get(Email.SEEN, [])),
        'exists': len(msgids.keys()),
    })
    log.info('%s|%d uids|%.2fs', label.name, len(msgids), timer.time())
    if not msgids:
        return

    # Fetch properties
    emails = session.query(Email.uid).filter(Email.uid.in_(msgids.keys()))

    # Cleanup flags
    emails.update({Email.flags: []}, synchronize_session=False)

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
                fields['t_labels'] = [label.id]
                fields.update(parse_header(header))
                emails.append(fields)
            session.execute(Email.__table__.insert(), emails)

    # Update labels
    uids = [k for k, v in msgids.items() if k not in msgids_]
    log.info('  * Update labels for %d emails...', len(uids))
    timer, updated = Timer(), 0
    emails = session.query(Email)
    updated += (
        emails.filter(Email.uid.in_(msgids.keys()))
        .filter(~Email.t_labels.any(label.id))
        .update(
            {Email.t_labels: Email.t_labels + array([label.id])},
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
                    {Email.flags: func.array_append(Email.flags, flag)},
                    synchronize_session=False
                )
            )
        log.info('  - %d ones for %.2fs', updated, timer.time())

    if not with_bodies:
        return

    # Fetch bodies
    emails = (
        session.query(Email.uid)
        .filter(Email.body.__eq__(None))
        .filter(Email.uid.in_(msgids.keys()))
        .order_by(Email.size)
    )
    uids = [msgids[r.uid] for r in emails.all()]
    if uids:
        for data in imap.fetch(im, uids, 'RFC822', 500, 'update bodies'):
            with session.begin():
                for uid, row in data.items():
                    fields = {'body': row['RFC822']}
                    fields.update(parse_header(fields['body']))
                    session.query(Email)\
                        .filter(Email.uid == uids_map[uid])\
                        .update(fields)
