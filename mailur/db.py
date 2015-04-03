import os
import re
import uuid

from psycopg2.extras import register_hstore
from sqlalchemy import (
    create_engine, func, Column, ForeignKey, Index,
    DateTime, String, Integer, BigInteger, SmallInteger,
    Boolean, LargeBinary, Float
)
from sqlalchemy.dialects.postgresql import ARRAY, HSTORE
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import sessionmaker, relationship

from . import conf, filters, base_dir
from .parser import human_html
from .imap_utf7 import decode

engine = create_engine(
    'postgresql+psycopg2://{pg_username}:{pg_password}@localhost/{pg_database}'
    .format(**conf.data), echo=False
)
register_hstore(engine.raw_connection(), True)

Base = declarative_base()
Session = sessionmaker(bind=engine, autocommit=True)
session = Session()


def init():
    Base.metadata.create_all(engine)
    with open(os.path.join(base_dir, 'db-init.sql')) as f:
        sql = f.read()
    engine.execute(sql)


class Task(Base):
    __tablename__ = 'tasks'
    N_SYNC = 'sync'

    id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    uids = Column(ARRAY(BigInteger), default=[])
    name = Column(String)
    params = Column(HSTORE)
    is_new = Column(Boolean, default=True)
    duration = Column(Float)

    __mapper_args__ = {
        'version_id_col': id,
        'version_id_generator': lambda v: uuid.uuid4().hex
    }


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
        name = self.name.replace('[Gmail]/', '')
        return decode(name)

    @property
    def url(self):
        return '/emails/?label=%s' % self.id

    @classmethod
    def get_all(cls):
        if not hasattr(cls, '_labels'):
            cls._labels = list(
                session.query(Label)
                .order_by(Label.weight.desc())
            )
        return cls._labels

    @classmethod
    def get(cls, func_or_id):
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

    @classmethod
    def get_by_alias(cls, alias):
        return cls.get(lambda l: l.alias == alias)


class EmailBody(Base):
    __tablename__ = 'email_bodies'

    uid = Column(BigInteger, ForeignKey('emails.uid'), primary_key=True)
    body = Column(LargeBinary)


class Email(Base):
    __tablename__ = 'emails'
    __table_args__ = (
        Index('ix_labels', 'labels', postgresql_using='gin'),
        Index('ix_flags', 'flags', postgresql_using='gin'),
    )
    SEEN = '\\Seen'
    STARRED = '\\Flagged'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    uid = Column(BigInteger, unique=True)
    labels = Column(MutableDict.as_mutable(HSTORE))
    gm_msgid = Column(BigInteger, unique=True)
    gm_thrid = Column(BigInteger, index=True)

    flags = Column(MutableDict.as_mutable(HSTORE))
    internaldate = Column(DateTime)
    size = Column(Integer, index=True)

    date = Column(DateTime)
    subject = Column(String, default='')
    from_ = Column(ARRAY(String), name='from', default=[])
    sender = Column(ARRAY(String), default=[])
    reply_to = Column(ARRAY(String), default=[])
    to = Column(ARRAY(String), default=[])
    cc = Column(ARRAY(String), default=[])
    bcc = Column(ARRAY(String), default=[])
    in_reply_to = Column(String, index=True)
    message_id = Column(String, index=True)

    text = Column(String, default='')
    html = Column(String, default='')
    embedded = Column(MutableDict.as_mutable(HSTORE))
    attachments = Column(ARRAY(String))

    raw = relationship('EmailBody', backref='email', uselist=False)

    @property
    def full_labels(self):
        return [Label.get(l) for l in self.labels]

    @property
    def unread(self):
        return self.SEEN not in self.flags

    @property
    def starred(self):
        return self.STARRED in self.flags

    @property
    def text_line(self):
        text = self.text or self.html or ''
        text = re.sub('<[^>]*?>', '', text)
        return self.human_subject(), text[:200].strip()

    def str_from(self, delimiter=', ', full=False):
        if full:
            filter = lambda v: v
        else:
            filter = 'get_addr_name' if conf('ui_use_names') else 'get_addr'
            filter = getattr(filters, filter)
        return delimiter.join([filter(f) for f in self.from_])

    @property
    def clean_subject(self):
        return re.sub(r'(?i)^(.{2,10}:\ ?)+', '', self.subject or '')

    def human_subject(self, strip=True):
        subj = self.subject or ''
        if strip and subj:
            subj = self.clean_subject

        subj = subj.strip() or '(no subject)'
        return subj

    @property
    def parent(self):
        if not hasattr(self, '_parent'):
            self._parent = None
            if self.in_reply_to:
                p = (
                    session.query(Email)
                    .filter(Email.message_id == self.in_reply_to)
                    .first()
                )
                self._parent = p if p and p.id != self.id else None
        return self._parent

    def human_html(self, class_='email-quote'):
        return human_html(self.html, self.parent and self.parent.html)
