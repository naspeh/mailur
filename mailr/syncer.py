from collections import OrderedDict, defaultdict

from imapclient import IMAPClient
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import array

from . import log, Timer, parser
from .db import Email, Label, session


def sync_gmail(username, password, with_bodies=True):
    im = IMAPClient('imap.gmail.com', use_uid=True, ssl=True)
    im.login(username, password)

    # Cleaunp t_flags and t_labels
    session.query(Email).update({Email.t_flags: [], Email.t_labels: []})

    weights = {
        'INBOX': 100,
        '\\Flagged': 95,
        '\\Sent': 90,
        '\\Drafts': 85,
        '\\All': 80,
        '\\Junk': 75,
        '\\Trash': 70
    }
    folders_ = im.list_folders()
    for attrs, delim, name in folders_:
        lookup = list(attrs) + [name]
        weight = [v for k, v in weights.items() if k in lookup]
        weight = weight[0] if weight else 0
        label = Label(attrs=attrs, delim=delim, name=name, weight=weight)
        try:
            session.add(label)
            session.flush()
        except IntegrityError:
            pass
        label = session.query(Label).filter_by(name=name).first()
        if '\\Noselect' in attrs:
            continue
        fetch_emails(im, label, with_bodies)

    # Update flags and labels
    timer = Timer()
    updated = (
        session.query(Email)
        .filter(Email.flags != Email.t_flags)
        .update({Email.flags: Email.t_flags})
    )
    updated += (
        session.query(Email)
        .filter(Email.labels != Email.t_labels)
        .update({Email.labels: Email.t_labels})
    )
    log.info(' %d updated labels or flags for %.2f', updated, timer.time())


def fetch_emails(im, label, with_bodies=True):
    uid_next = im.select_folder(label.name, readonly=True)['UIDNEXT']

    timer = Timer()
    uids, step = [], 5000
    for i in range(1, uid_next, step):
        uids += im.search('UID %d:%d' % (i, i + step - 1))

    flags = defaultdict(list)
    msgids, step = OrderedDict(), 500
    for i in range(0, len(uids), step):
        uids_ = uids[i: i + step]
        data = im.fetch(uids_, 'X-GM-MSGID FLAGS')
        for k, v in data.items():
            msgid = v['X-GM-MSGID']
            msgids[msgid] = k
            for f in v['FLAGS']:
                flags[f].append(msgid)
    uids_map = {v: k for k, v in msgids.items()}
    flags = OrderedDict(sorted(flags.items()))

    session.query(Label).filter_by(id=label.id).update({
        'exists': len(msgids.keys()),
        'unread': len(msgids.keys()) - len(flags.get(Email.SEEN, []))
    })

    log.info('%s|%d uids|%.2fs', label.name, len(msgids), timer.time())
    if not msgids:
        return

    # Fetch properties
    emails = session.query(Email.uid).filter(Email.uid.in_(msgids.keys()))
    msgids_ = sum([[r.uid] for r in emails.all()], [])
    msgids_ = list(set(msgids.keys()) - set(msgids_))
    uids = [v for k, v in msgids.items() if k in msgids_]
    if uids:
        log.info('  * Fetch %d headers...', len(uids))
        query = {
            'header': 'RFC822.HEADER',
            'internaldate': 'INTERNALDATE',
            't_flags': 'FLAGS',
            'size': 'RFC822.SIZE',
            'uid': 'X-GM-MSGID',
            'gm_msgid': 'X-GM-MSGID',
            'gm_thrid': 'X-GM-THRID'
        }
        timer, step = Timer(), 1000
        for i in range(0, len(uids), step):
            uids_ = uids[i: i + step]
            data = im.fetch(uids_, query.values())
            with session.begin():
                for row in data.values():
                    fields = {k: row[v] for k, v in query.items()}
                    fields['t_labels'] = [label.id]
                    fields.update(parser.parse_header(fields['header']))
                    session.add(Email(**fields))

            log.info('  - %d headers for %.2fs', i + len(uids_), timer.time())

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
    log.info('  - %d updated for %.2fs', updated, timer.time())

    # Update flags
    uids = [k for k, v in msgids.items() if k not in msgids_]
    if uids:
        log.info('  * Update flags for %d emails...', len(uids))
        timer, updated = Timer(), 0
        emails = session.query(Email)
        for flag, uids_ in flags.items():
            updated += (
                emails.filter(Email.uid.in_(uids_))
                .filter(~Email.t_flags.any(flag))
                .update(
                    {Email.t_flags: func.array_append(Email.t_flags, flag)},
                    synchronize_session=False
                )
            )
        log.info('  - %d updated for %.2fs', updated, timer.time())

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
        log.info('  * Fetch %d bodies...', len(uids))
        timer, step = Timer(), 500
        for i in range(0, len(uids), step):
            uids_ = uids[i: i + step]
            data = im.fetch(uids_, 'RFC822')

            with session.begin():
                for uid, row in data.items():
                    session.query(Email)\
                        .filter_by(uid=uids_map[uid])\
                        .update({'body': row['RFC822']})

            log.info('  - %d bodies for %.2fs', i + len(uids_), timer.time())
