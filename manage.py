#!/usr/bin/env python
import email.header

import chardet
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psa
from imapclient import IMAPClient

db = sa.create_engine(
    'postgresql+psycopg2://test:test@/mail', strategy='threadlocal'
)
metadata = sa.MetaData()

emails = sa.Table('emails', metadata, *(
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('updated_at', sa.DateTime, server_onupdate='NOW()'),
    sa.Column('created_at', sa.DateTime, server_default='NOW()'),

    sa.Column('uid', sa.Integer, unique=True),
    sa.Column('flags', psa.ARRAY(sa.String)),
    sa.Column('internaldate', sa.DateTime),
    sa.Column('size', sa.Integer, index=True),
    sa.Column('body', sa.String),
))

parsed_emails = sa.Table('parsed_emails', metadata, *(
    sa.Column('id', sa.ForeignKey('emails.id'), primary_key=True),
    sa.Column('updated_at', sa.DateTime, server_onupdate='NOW()'),
    sa.Column('created_at', sa.DateTime, server_default='NOW()'),

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
metadata.create_all(db)


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


def decode_addresses(addresses):
    return addresses and [decode_header(a) for a in addresses]


def sync_gmail():
    conf = __import__('conf')
    im = IMAPClient('imap.gmail.com', use_uid=True, ssl=True)
    im.login(conf.username, conf.password)

    folders = im.list_folders()
    folder_all = [l for l in folders if '\\All' in l[0]][0]
    resp = im.select_folder(folder_all[-1], readonly=True)

    step = 1000
    pairs = [(n, n + step - 1) for n in range(1, resp['UIDNEXT'], step)]
    pairs[-1] = pairs[-1][0], resp['UIDNEXT']

    for pair in pairs:
        uids = im.search('UID %d:%d' % pair)
        print('Start:', uids)
        fields = (
            'BODY[HEADER.FIELDS ('
            '   DATE SUBJECT FROM SENDER REPLY-TO TO CC BCC'
            '   IN-REPLY-TO MESSAGE-ID'
            ')]'
        )
        body = 'BODY[TEXT]'

        data = im.fetch(uids, ['FLAGS INTERNALDATE RFC822.SIZE RFC822'])
        with db.begin() as c:
            for uid, row in data.items():
                c.execute(emails.insert().values(
                    uid=uid,
                    internaldate=row['INTERNALDATE'],
                    flags=row['FLAGS'],
                    size=row['RFC822.SIZE'],
                    body=row['RFC822']
                ))
        print('Done.')


if __name__ == '__main__':
    sync_gmail()
