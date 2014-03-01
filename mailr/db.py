from psycopg2.extras import register_hstore
from sqlalchemy import (
    create_engine, Column, func,
    DateTime, String, Integer, BigInteger, SmallInteger, Boolean, LargeBinary
)
from sqlalchemy.dialects.postgresql import ARRAY, HSTORE
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import sessionmaker

engine = create_engine('postgresql+psycopg2://test:test@/mail', echo=False)
register_hstore(engine.raw_connection(), True)

Base = declarative_base()
drop_all = lambda: Base.metadata.drop_all(engine)


class Label(Base):
    __tablename__ = 'labels'
    NOSELECT = '\\Noselect'
    A_INBOX = 'inbox'
    A_STARRED = 'starred'
    A_SENT = 'sent'
    A_DRAFTS = 'drafts'
    A_ALL = 'all'
    A_SPAM = 'spam'
    A_TRASH = 'trash'
    A_IMPORTANT = 'important'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    attrs = Column(ARRAY(String))
    delim = Column(String)
    name = Column(String, unique=True)

    alias = Column(String, unique=True)
    hidden = Column(Boolean, default=False)
    index = Column(SmallInteger, default=0)
    weight = Column(SmallInteger, default=0)
    unread = Column(SmallInteger, default=0)
    exists = Column(SmallInteger, default=0)

    @property
    def human_name(self):
        from .imap_utf7 import decode

        name = self.name.replace('[Gmail]/', '')
        return decode(name)

    @classmethod
    def get_all(cls):
        if not hasattr(cls, '_labels'):
            cls._labels = list(
                session.query(Label)
                .order_by(Label.weight.desc())
            )
        return cls._labels

    @classmethod
    def get(cls, func_or_id=None):
        if isinstance(func_or_id, (int, str)):
            func = lambda l: l.id == int(func_or_id)
        else:
            func = func_or_id

        label = [l for l in cls.get_all() if func(l)]
        if label:
            if len(label) > 1:
                raise ValueError('Must be one row, but %r' % label)
            return label[0]
        return None


class Email(Base):
    __tablename__ = 'emails'
    SEEN = '\\Seen'
    STARRED = '\\Flagged'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    uid = Column(BigInteger, unique=True)
    labels = Column(MutableDict.as_mutable(HSTORE))
    gm_msgid = Column(BigInteger, unique=True)
    gm_thrid = Column(BigInteger)

    flags = Column(ARRAY(String), default=[])
    internaldate = Column(DateTime)
    size = Column(Integer, index=True)
    body = Column(LargeBinary)

    date = Column(DateTime)
    subject = Column(String)
    from_ = Column(ARRAY(String), name='from')
    sender = Column(ARRAY(String))
    reply_to = Column(ARRAY(String))
    to = Column(ARRAY(String))
    cc = Column(ARRAY(String))
    bcc = Column(ARRAY(String))
    in_reply_to = Column(String, index=True)
    message_id = Column(String, index=True)

    text = Column(String)
    html = Column(String)

    @property
    def full_labels(self):
        return [Label.get(l) for l in self.labels]

    @property
    def unread(self):
        return self.SEEN not in self.flags

    @property
    def starred(self):
        return self.STARRED in self.flags


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autocommit=True)
session = Session()
