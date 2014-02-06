#!/usr/bin/env python
import argparse
import email.header
import logging
import time

import chardet
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psa
from imapclient import IMAPClient

logging.basicConfig(
    format='%(levelname)s %(filename)s|%(lineno)d %(asctime)s # %(message)s',
    datefmt='%H:%M:%S', level=logging.DEBUG
)
log = logging.getLogger(__name__)

engine = sa.create_engine('postgresql+psycopg2://test:test@/mail')
metadata = sa.MetaData()

labels = sa.Table('labels', metadata, *(
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('created_at', sa.DateTime, default=sa.func.now()),
    sa.Column('updated_at', sa.DateTime, onupdate=sa.func.now()),

    sa.Column('attrs', psa.ARRAY(sa.String)),
    sa.Column('delim', sa.String),
    sa.Column('name', sa.String, unique=True),

    sa.Column('uids', psa.ARRAY(sa.BigInteger)),
    sa.Column('recent', sa.Integer),
    sa.Column('exists', sa.Integer),
))

emails = sa.Table('emails', metadata, *(
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('created_at', sa.DateTime, default=sa.func.now()),
    sa.Column('updated_at', sa.DateTime, onupdate=sa.func.now()),

    sa.Column('uid', sa.BigInteger, unique=True),
    sa.Column('flags', psa.ARRAY(sa.String)),
    sa.Column('internaldate', sa.DateTime),
    sa.Column('size', sa.Integer, index=True),
    sa.Column('header', sa.String),
    sa.Column('body', sa.String),

    sa.Column('date', sa.DateTime),
    sa.Column('subject', sa.String),
    sa.Column('from', psa.ARRAY(sa.String), key='from_'),
    sa.Column('sender', psa.ARRAY(sa.String)),
    sa.Column('reply_to', psa.ARRAY(sa.String)),
    sa.Column('to', psa.ARRAY(sa.String)),
    sa.Column('cc', psa.ARRAY(sa.String)),
    sa.Column('bcc', psa.ARRAY(sa.String)),
    sa.Column('in_reply_to', sa.String),
    sa.Column('message_id', sa.String),

    sa.Column('text', sa.String),
    sa.Column('html', sa.String),
))

metadata.create_all(engine)
conn = engine.connect()
run_sql = conn.execute


def decode_header(data, default='utf-8'):
    if not data:
        return None

    parts_ = email.header.decode_header(data)
    parts = []
    for text, charset in parts_:
        if isinstance(text, str):
            part = text
        else:
            try:
                part = text.decode(charset or default)
            except (LookupError, UnicodeDecodeError):
                charset = chardet.detect(text)['encoding']
                part = text.decode(charset or default)
        parts += [part]
    return ''.join(parts)


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


def parse_args():
    parser = argparse.ArgumentParser('mail')
    cmds = parser.add_subparsers(help='commands')

    def cmd(name, **kw):
        p = cmds.add_parser(name, **kw)
        p.set_defaults(cmd=name)
        p.arg = lambda *a, **kw: p.add_argument(*a, **kw) and p
        p.exe = lambda f: p.set_defaults(exe=f) and p
        return p

    cmd('sync')\
        .arg('-b', '--with-bodies', action='store_true')\
        .exe(lambda a: sync_gmail(a.with_bodies))

    cmd('db-clear').exe(lambda a: metadata.drop_all(engine))

    args = parser.parse_args()
    if not hasattr(args, 'exe'):
        parser.print_usage()
    else:
        args.exe(args)

if __name__ == '__main__':
    try:
        parse_args()
    except KeyboardInterrupt:
        raise SystemExit(1)
