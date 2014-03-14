import re

from psycopg2.extras import register_hstore
from sqlalchemy import (
    create_engine, Column, func,
    DateTime, String, Integer, BigInteger, SmallInteger, Boolean, LargeBinary
)
from sqlalchemy.dialects.postgresql import ARRAY, HSTORE
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import sessionmaker

from . import conf
from .parser import hide_quote
from .imap_utf7 import decode

engine = create_engine(
    'postgresql+psycopg2://{pg_username}:{pg_password}@/{pg_database}'
    .format(**conf.data), echo=False
)
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
    subject = Column(String, default='')
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
    embedded = Column(MutableDict.as_mutable(HSTORE))
    attachments = Column(ARRAY(String))

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
        text = self.text or re.sub('<[^>]*?>', '', self.html or '')
        return self.human_subject(), text[:200].strip()

    def human_subject(self, strip=True):
        subj = (
            re.sub(r'(?i)^(Re[^:]*:\s?)+', '', self.subject or '')
            if strip else self.subject
        ).strip()

        subj = subj or '(no subject)'
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
        from lxml import html
        from lxml.html.clean import Cleaner
        from mistune import markdown

        if self.html:
            cleaner = Cleaner(links=False, safe_attrs_only=False)
            html_ = cleaner.clean_html(self.html)
            if self.embedded:
                root = html.fromstring(html_)
                for img in root.findall('.//img'):
                    if not img.attrib.get('src').startswith('cid:'):
                        continue
                    cid = '<%s>' % img.attrib.get('src')[4:]
                    img.attrib['src'] = '/attachments/' + self.embedded[cid]
                html_ = html.tostring(root, encoding='utf8').decode()
        elif self.text:
            html_ = markdown(self.text)
            html_ = re.sub(r'(?m)(\n|\r|\r\n)', '<br/>', html_)
        else:
            html_ = ''

        html_ = re.sub(r'(<br[/]?>\s*)$', '', html_).strip()
        if html_ and self.parent:
            parent_html = self.parent.html or self.parent.human_html()
            html_ = hide_quote(html_, parent_html, class_)
        return html_


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autocommit=True)
session = Session()
