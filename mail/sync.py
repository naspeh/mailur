import logging
import time

from imapclient import IMAPClient

from .db import labels, emails, run_sql, sa

log = logging.getLogger(__name__)


def sync_gmail(with_bodies=True):
    conf = __import__('conf')
    im = IMAPClient('imap.gmail.com', use_uid=True, ssl=True)
    im.login(conf.username, conf.password)

    folders_ = im.list_folders()
    for attrs, delim, name in folders_:
        try:
            run_sql(labels.insert(), attrs=attrs, delim=delim, name=name)
        except sa.exc.IntegrityError:
            pass
        label = run_sql(labels.select().where(labels.c.name == name)).first()
        if '\\Noselect' in attrs:
            continue
        fetch_emails(im, label, with_bodies)


def fetch_emails(im, label, with_bodies=True):
    res = im.select_folder(label.name, readonly=True)
    uid_next, recent, exists = res['UIDNEXT'], res['RECENT'], res['EXISTS']

    start = time.time()
    uids, step = [], 5000
    for i in range(1, uid_next, step):
        uids += im.search('UID %d:%d' % (i, i + step - 1))

    msgids, step = [], 500
    for i in range(0, len(uids), step):
        uids_ = uids[i: i + step]
        data = im.fetch(uids_, 'X-GM-MSGID')
        msgids += [(v['X-GM-MSGID'], k) for k, v in data.items()]
    msgids = dict(msgids)

    run_sql(
        labels.update()
        .where(labels.c.id == label.id)
        .values(uids=msgids.keys(), recent=recent, exists=exists)
    )

    log.info('%s|%d uids|%.2f', label.name, len(msgids), time.time() - start)
    if not msgids:
        return

    # Fetch properties
    sql = sa.select([emails.c.uid]).where(emails.c.uid.in_(msgids.keys()))
    msgids_ = sum([[r.uid] for r in run_sql(sql).fetchall()], [])
    msgids_ = list(set(msgids.keys()) - set(msgids_))
    uids = [msgids[k] for k in msgids_]
    if uids:
        log.info('Fetch %d headers...', len(uids))
        start = time.time()
        step = 1000
        for i in range(0, len(uids), step):
            uids_ = uids[i: i + step]
            query = {
                'header': 'BODY[HEADER]',
                'internaldate': 'INTERNALDATE',
                'flags': 'FLAGS',
                'size': 'RFC822.SIZE',
                'uid': 'X-GM-MSGID'
            }
            data = im.fetch(uids_, query.values())
            items = [
                {k: row[v] for k, v in query.items()}
                for row in data.values()
            ]
            run_sql(emails.insert(), items)
            count = step * i + len(uids_)
            log.info('* %d headers for %.2fs', count, time.time() - start)

    if not with_bodies:
        return

    # Fetch bodies
    sql = (
        sa.select([emails.c.uid])
        .where(emails.c.body == sa.null())
        .where(emails.c.uid.in_(msgids.keys()))
        .order_by(emails.c.size)
    )
    uids = [msgids[r.uid] for r in run_sql(sql).fetchall()]
    uids_map = {v: k for k, v in msgids.items()}
    if uids:
        log.info('Fetch %d bodies...', len(uids))
        start = time.time()
        step = 500
        for i in range(0, len(uids), step):
            uids_ = uids[i: i + step]
            data = im.fetch(uids_, 'RFC822')
            items = [
                dict(_uid=uids_map[u], _body=r['RFC822'])
                for u, r in data.items()
            ]
            run_sql(
                emails.update()
                .where(emails.c.uid == sa.bindparam('_uid'))
                .values(body=sa.bindparam('_body')),
                items
            )
            count = step * i + len(uids_)
            log.info('* %d bodies for %.2fs', count, time.time() - start)
