from email.utils import getaddresses

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

engine = sa.create_engine('postgresql+psycopg2://test:test@/mail')
Base = declarative_base()
drop_all = lambda: Base.metadata.drop_all(engine)


class Label(Base):
    __tablename__ = 'labels'

    id = sa.Column(sa.Integer, primary_key=True)
    created_at = sa.Column(sa.DateTime, default=sa.func.now())
    updated_at = sa.Column(sa.DateTime, onupdate=sa.func.now())
    weight = sa.Column(sa.SmallInteger, default=0)

    attrs = sa.Column(psa.ARRAY(sa.String))
    delim = sa.Column(sa.String)
    name = sa.Column(sa.String, unique=True)

    uids = sa.Column(psa.ARRAY(sa.BigInteger))
    recent = sa.Column(sa.Integer)
    exists = sa.Column(sa.Integer)

    @property
    def human_name(self):
        return self.name.replace('[Gmail]/', '')


class Email(Base):
    __tablename__ = 'emails'

    id = sa.Column(sa.Integer, primary_key=True)
    created_at = sa.Column(sa.DateTime, default=sa.func.now())
    updated_at = sa.Column(sa.DateTime, onupdate=sa.func.now())

    uid = sa.Column(sa.BigInteger, unique=True)
    gm_msgid = sa.Column(sa.BigInteger, unique=True)
    gm_thrid = sa.Column(sa.BigInteger)

    flags = sa.Column(psa.ARRAY(sa.String))
    internaldate = sa.Column(sa.DateTime)
    size = sa.Column(sa.Integer, index=True)
    header = sa.Column(sa.String)
    body = sa.Column(sa.String)

    date = sa.Column(sa.DateTime)
    subject = sa.Column(sa.String)
    from_ = sa.Column(psa.ARRAY(sa.String), name='from')
    sender = sa.Column(psa.ARRAY(sa.String))
    reply_to = sa.Column(psa.ARRAY(sa.String))
    to = sa.Column(psa.ARRAY(sa.String))
    cc = sa.Column(psa.ARRAY(sa.String))
    bcc = sa.Column(psa.ARRAY(sa.String))
    in_reply_to = sa.Column(sa.String)
    message_id = sa.Column(sa.String)

    text = sa.Column(sa.String)
    html = sa.Column(sa.String)

    @property
    def names_from(self):
        return [e.split('@')[0] for n, e in getaddresses(self.from_)]

    @property
    def gravatars_from(self):
        from hashlib import md5

        gen_hash = lambda e: md5(e.strip().lower().encode()).hexdigest()
        gen_url = lambda h: '//www.gravatar.com/avatar/%s' % h if h else None

        return [
            (f, gen_url(gen_hash(e[1])))
            for f, e in zip(self.from_, getaddresses(self.from_))
        ]

    @property
    def local_date(self):
        import arrow
        return arrow.get(self.date).to('Europe/Kiev')


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autocommit=True)
session = Session()
