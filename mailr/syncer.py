import os
from collections import OrderedDict, defaultdict

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from . import log, attachments_dir, Timer, imap, parser
from .db import Email, Label, session


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
    folders_ = imap.list_(im)
    for index, value in enumerate(folders_):
        attrs, delim, name = value
        lookup = lambda k: name == k if k == 'INBOX' else k in attrs
        folder = [v for k, v in opts.items() if lookup(k)]
        weight, hidden, alias = (
            folder[0] if folder else (0, Label.NOSELECT in attrs, None)
        )
        label = Label(attrs=attrs, delim=delim, name=name)
        try:
            session.add(label)
            session.flush()
        except IntegrityError:
            pass

        label = session.query(Label).filter(Label.name == name).one()
        label.hidden = hidden
        label.index = index
        label.weight = weight
        label.alias = alias
        session.merge(label)

        if Label.NOSELECT in attrs:
            continue
        fetch_emails(im, label, with_bodies)


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
                fields['labels'] = {str(label.id): ''}
                if not with_bodies:
                    fields.update(parser.parse(header))
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
                    {Email.flags: func.array_append(Email.flags, flag)},
                    synchronize_session=False
                )
            )
        log.info('  - %d ones for %.2fs', updated, timer.time())

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
        step_size, group_size = 0, 100 * 1024 * 1024
        step_uids, group_uids = [], []
        for uid, size in uids.items():
            if step_uids and step_size + size > group_size:
                group_uids.append(step_uids)
                step_uids, step_size = [], 0
            else:
                step_uids.append(uid)
                step_size += size
        for uids_ in group_uids:
            q = 'RFC822'
            data = imap.fetch_all(im, uids_, q, len(uids_), 'update bodies')
            with session.begin():
                for uid, row in data.items():
                    update_email(uids_map[uid], row['RFC822'])


def update_email(uid, raw):
    fields = parser.parse(raw)
    fields['body'] = raw
    fields['text'] = fields.pop('text/plain', None)
    fields['html'] = fields.pop('text/html', None)

    attachments = fields.pop('attachments', None)
    if attachments:
        fields.update(attachments=[], embedded={})
        for index, item in enumerate(attachments):
            if item['payload']:
                name = secure_filename(item['filename'] or item['id'])
                url = '/'.join([str(uid), str(index), name])
                if item['id'] and item['maintype'] == 'image':
                    fields['embedded'][item['id']] = url
                elif item['filename']:
                    fields['attachments'] += [url]
                else:
                    log.warn('UnknownAttachment(%s)', uid)
                    continue
                path = os.path.join(attachments_dir, url)
                if not os.path.exists(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, 'bw') as f:
                        f.write(item['payload'])

    session.query(Email).filter(Email.uid == uid)\
        .update(fields, synchronize_session=False)


def parse_emails(new=True):
    emails = session.query(Email)
    if new:
        emails = emails.filter(Email.text == None).filter(Email.html == None)

    for email in emails:
        update_email(email.uid, email.body)
