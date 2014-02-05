#!/usr/bin/env python
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

engine = sa.create_engine(
    'postgresql+psycopg2://test:test@/mail', strategy='threadlocal'
)
metadata = sa.MetaData()

folders = sa.Table('folders', metadata, *(
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('created_at', sa.DateTime, default=sa.func.now()),
    sa.Column('updated_at', sa.DateTime, onupdate=sa.func.now()),

    sa.Column('attrs', psa.ARRAY(sa.String)),
    sa.Column('delim', sa.String),
    sa.Column('name', sa.String, unique=True),
    sa.Column('uids', psa.ARRAY(sa.Integer)),
    sa.Column('uid_next', sa.Integer)
))

emails = sa.Table('emails', metadata, *(
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('created_at', sa.DateTime, default=sa.func.now()),
    sa.Column('updated_at', sa.DateTime, onupdate=sa.func.now()),

    sa.Column('uid', sa.Integer, unique=True),
    sa.Column('flags', psa.ARRAY(sa.String)),
    sa.Column('internaldate', sa.DateTime),
    sa.Column('size', sa.Integer, index=True),
    sa.Column('header', sa.String),
    sa.Column('body', sa.String),
    sa.Column('gm_labels', psa.ARRAY(sa.String)),

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
db = engine.connect()
sql = db.execute


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


def sync_gmail():
    conf = __import__('conf')
    im = IMAPClient('imap.gmail.com', use_uid=True, ssl=True)
    im.login(conf.username, conf.password)

    def fetch_uids(uid_next, last_uid=0):
        # Fetch all uids
        start = time.time()
        uids, step = [], 5000
        for i in range(last_uid + 1, uid_next, step):
            uids += im.search('UID %d:%d' % (i, i + step - 1))
        log.info('Fetched uids: %.2f', time.time() - start)
        return uids

    start = time.time()
    folders_ = im.list_folders()
    for attrs, delim, name in folders_:
        if not sql(folders.select().where(folders.c.name == name)).first():
            sql(folders.insert().values(attrs=attrs, delim=delim, name=name))
        if '\\Noselect' not in attrs:
            uid_next = im.select_folder(name, readonly=True)['UIDNEXT']
            sql(
                folders.update()
                .where(folders.c.name == name)
                .values(uids=fetch_uids(uid_next), uid_next=uid_next)
            )
    log.info('Fetched uids for all folders: %.2f', time.time() - start)

    f_all = sql(folders.select().where(folders.c.attrs.any('\\All'))).first()
    last_uid = sql(sa.select([sa.func.max(emails.c.uid)])).scalar()
    uids = f_all.uids
    if last_uid:
        uids = f_all.uids[f_all.uids.index(last_uid) + 1:]
    uid_next = im.select_folder(f_all.name, readonly=True)

    # Fetch headers and email properties
    start = time.time()
    step = 3000
    for i in range(0, len(uids), step):
        uids_ = uids[i: i + step]
        log.info('Process headers: %s', uids_)
        data = im.fetch(uids_, (
            'BODY[HEADER] INTERNALDATE FLAGS RFC822.SIZE X-GM-LABELS'
        ))

        items = []
        for uid, row in data.items():
            items.append(dict(
                uid=uid,
                internaldate=row['INTERNALDATE'],
                flags=row['FLAGS'],
                size=row['RFC822.SIZE'],
                header=row['BODY[HEADER]'],
                gm_labels=row['X-GM-LABELS']
            ))
        sql(emails.insert().values(items))
    log.info('Fetched headers and properties: %.2f', time.time() - start)

    return
    # Loads bodies
    stmt = (
        sa.select([emails.c.uid])
        .where(emails.c.body == sa.null())
        .order_by(emails.c.size)
    )
    uids = sum([[r.uid] for r in sql(stmt).fetchall()], [])
    step = 500
    for i in range(0, len(uids), step):
        uids_ = uids[i: i + step]
        log.info('Process bodies: %s', uids_)
        data = im.fetch(uids_, 'RFC822')

        items = [dict(_uid=u, _body=r['RFC822']) for u, r in data.items()]
        stmt = (
            emails.update()
            .where(emails.c.uid == sa.bindparam('_uid'))
            .values(body=sa.bindparam('_body'))
        )
        sql(stmt, items)


if __name__ == '__main__':
    sync_gmail()
