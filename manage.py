#!/usr/bin/env python
import email.header
import logging

import chardet
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psa
from imapclient import IMAPClient

logging.basicConfig(
    format='%(filename)s|%(lineno)d %(asctime)s %(levelname)s # %(message)s',
    level=logging.DEBUG
)
log = logging.getLogger(__name__)

engine = sa.create_engine(
    'postgresql+psycopg2://test:test@/mail', strategy='threadlocal'
)
metadata = sa.MetaData()

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

    folders = im.list_folders()
    folder_all = [l for l in folders if '\\All' in l[0]][0]
    resp = im.select_folder(folder_all[-1], readonly=True)

    last_uid = db.execute(sa.select([sa.func.max(emails.c.uid)])).scalar() or 0

    # Fetch all uids
    uids, step = [], 1000
    for i in range(last_uid + 1, resp['UIDNEXT'], step):
        uids += im.search('UID %d:%d' % (i, i + step - 1))

    step = 100
    for i in range(0, len(uids), step):
        uids_ = uids[i: i + step]
        log.info('Process headers: %s', uids_)
        data = im.fetch(uids_, 'BODY[HEADER] INTERNALDATE FLAGS RFC822.SIZE')

        items = []
        for uid, row in data.items():
            items.append(dict(
                uid=uid,
                internaldate=row['INTERNALDATE'],
                flags=row['FLAGS'],
                size=row['RFC822.SIZE'],
                header=row['BODY[HEADER]']
            ))
        db.execute(emails.insert().values(items))

    # Loads bodies
    stmt = (
        sa.select([emails.c.uid])
        .where(emails.c.body == sa.null())
        .order_by(emails.c.size)
    )
    uids = sum([[r.uid] for r in db.execute(stmt).fetchall()], [])
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
        db.execute(stmt, items)


if __name__ == '__main__':
    sync_gmail()
