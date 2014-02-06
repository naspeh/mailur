import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psa

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
drop_all = lambda: metadata.drop_all(engine)
