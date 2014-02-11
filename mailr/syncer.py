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
    uid_next, recent, exists = res['UIDNEXT'], res['RECENT'], res['EXISTS']

    timer = Timer()
    uids, step = [], 5000
    for i in range(1, uid_next, step):
        uids += im.search('UID %d:%d' % (i, i + step - 1))

    session.query(Label).filter_by(id=label.id)\
        .update({'uids': uids, 'recent': recent, 'exists': exists})

    log.info('%s|%d uids|%.2f', label.name, len(uids), timer.time())
    if not uids:
        return

    # Fetch properties
    emails = session.query(Email.uids).filter(Email.uids.overlap(uids))
    uids_ = sum([r.uids for r in emails.all()], [])
    new_uids = list(set(uids) - set(uids_))
    if new_uids:
        log.info('Fetch %d headers...', len(new_uids))
        query = {
            'header': 'RFC822.HEADER',
            'internaldate': 'INTERNALDATE',
            'flags': 'FLAGS',
            'size': 'RFC822.SIZE',
            'gm_msgid': 'X-GM-MSGID',
            'gm_thrid': 'X-GM-THRID'
        }
        timer, step = Timer(), 1000
        for i in range(0, len(new_uids), step):
            uids_ = uids[i: i + step]
            updated, created = 0, 0
            data = im.fetch(uids_, query.values())
            with session.begin():
                for uid, row in data.items():
                    fields = {k: row[v] for k, v in query.items()}
                    email = (
                        session.query(Email)
                        .filter(Email.gm_msgid == fields['gm_msgid'])
                        .first()
                    )
                    if email:
                        email.uids = set((email.uids or []) + [uid])
                        session.merge(email)
                        updated += 1
                    else:
                        fields.update(parser.parse_header(fields['header']))
                        fields.update(uids=[uid])
                        session.add(Email(**fields))
                        created += 1
            log.info('* %d headers for %.2fs', i + len(uids_), timer.time())
            log.info('- %d created and %d updated entries', created, updated)

    if not with_bodies:
        return

    # Fetch bodies
    emails = (
        session.query(Email.uids)
        .filter(Email.body.__eq__(None))
        .filter(Email.uids.overlap(uids))
    )
    uids_ = sum([r.uids for r in emails.all()], [])
    empty_uids = list(set(uids) & set(uids_))
    if empty_uids:
        log.info('Fetch %d bodies...', len(empty_uids))
        timer, step = Timer(), 500
        for i in range(0, len(empty_uids), step):
            uids_ = empty_uids[i: i + step]
            data = im.fetch(uids_, 'RFC822')

            with session.begin():
                for uid, row in data.items():
                    email = session.query(Email).filter(Email.uids.any(uid))
                    print(email.first().body)
                    email.update(
                        {'body': row['RFC822']}, synchronize_session=False
                    )

            log.info('* %d bodies for %.2fs', i + len(uids_), timer.time())
