from collections import OrderedDict

from imapclient import IMAPClient
from sqlalchemy.exc import IntegrityError

from . import log, Timer, parser
from .db import Email, Label, session


def sync_gmail(username, password, with_bodies=True):
    im = IMAPClient('imap.gmail.com', use_uid=True, ssl=True)
    im.login(username, password)

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


def fetch_emails(im, label, with_bodies=True):
    res = im.select_folder(label.name, readonly=True)

    timer = Timer()
    uids, step = [], 5000
    for i in range(1, uid_next, step):
        uids += im.search('UID %d:%d' % (i, i + step - 1))

    msgids, flags, step = [], [], 500
    for i in range(0, len(uids), step):
        uids_ = uids[i: i + step]
        data = im.fetch(uids_, 'X-GM-MSGID FLAGS')
        msgids += [(v['X-GM-MSGID'], k) for k, v in data.items()]
        flags += [(k, v['FLAGS']) for k, v in data.items()]
    msgids = OrderedDict(msgids)
    uids_map = {v: k for k, v in msgids.items()}
    flags = {uids_map[k]: v for k, v in flags}

    session.query(Label).filter_by(id=label.id)\
        .update({'uids': msgids.keys(), 'recent': recent, 'exists': exists})

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
            'flags': 'FLAGS',
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
                    fields.update(parser.parse_header(fields['header']))
                    session.add(Email(**fields))

            log.info('  - %d headers for %.2fs', i + len(uids_), timer.time())

    # Update flags
    uids = [k for k, v in msgids.items() if k not in msgids_]
    if uids:
        log.info('  * Update flags for %d emails...', len(uids))
        timer, updated = Timer(), 0
        emails = session.query(Email).filter(Email.uid.in_(uids))
        with session.begin():
            for email in emails.all():
                if email.flags != list(flags[email.uid]):
                    email.flags = flags[email.uid]
                    session.merge(email)
                    updated += 1

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
