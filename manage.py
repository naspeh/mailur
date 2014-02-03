#!/usr/bin/env python
import email.header
import imaplib

import chardet
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psa
from imapclient import IMAPClient

engine = sa.create_engine('postgresql+psycopg2://test:test@/mail', echo=True)
metadata = sa.MetaData()

mails = sa.Table('mails', metadata, *(
    sa.Column('id', sa.Integer, primary_key=True),

    sa.Column('uid', sa.Integer),
    sa.Column('flags', psa.ARRAY(sa.String)),
    sa.Column('internaldate', sa.DateTime),
    sa.Column('size', sa.Integer)

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
))
metadata.create_all(engine)


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
    print(addresses)
    return addresses and [decode_header(str(a)) for a in addresses]


def sync_gmail():
    conf = __import__('conf')
    im = IMAPClient('imap.gmail.com', use_uid=True, ssl=True)
    im.login(conf.username, conf.password)

    #im = imaplib.IMAP4_SSL('imap.gmail.com')
    #im.login(conf.username, conf.password)
    #im.select(readonly=True)
    #im.select('"[Gmail]/All Mail"')

    folders = im.list_folders()
    folder_all = [l for l in folders if '\\All' in l[0]][0]
    resp = im.select_folder(folder_all[-1], readonly=True)

    step = 1000
    pairs = [(n, n + step - 1) for n in range(1, resp['UIDNEXT'], step)]
    pairs[-1] = pairs[-1][0], resp['UIDNEXT']

    for pair in pairs:
        uids = im.search('UID %d:%d' % pair)
        data = im.fetch(uids, ['FAST'])
        for uid, row in data.items():
            envelope = row['ENVELOPE']
            mails.insert().values(
                id=uid,
                date=envelope.date,
                subject=decode_header(envelope.subject),
                from_=decode_addresses(envelope.from_),
                sender=decode_addresses(envelope.sender),
                reply_to=decode_addresses(envelope.reply_to),
                to=decode_addresses(envelope.to),
                cc=decode_addresses(envelope.cc),
                bcc=decode_addresses(envelope.bcc),
                message_id=envelope.message_id,
                in_reply_to=envelope.in_reply_to,
            )

if __name__ == '__main__':
    sync_gmail()
