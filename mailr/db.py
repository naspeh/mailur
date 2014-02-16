from sqlalchemy import (
    create_engine, Column, func,
    DateTime, String, Integer, BigInteger, SmallInteger, Boolean, LargeBinary
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

engine = create_engine('postgresql+psycopg2://test:test@/mail')

Base = declarative_base()
drop_all = lambda: Base.metadata.drop_all(engine)


class Label(Base):
    __slots__ = ()
    __tablename__ = 'labels'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    attrs = Column(ARRAY(String))
    delim = Column(String)
    name = Column(String, unique=True)

    is_folder = Column(Boolean, default=False)
    weight = Column(SmallInteger, default=0)
    unread = Column(SmallInteger, default=0)
    exists = Column(SmallInteger, default=0)

    @property
    def human_name(self):
        return self.name.replace('[Gmail]/', '')


class Email(Base):
    __slots__ = ()
    __tablename__ = 'emails'

    SEEN = '\\Seen'
    STARRED = '\\Flagged'
    _labels = None

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    uid = Column(BigInteger, unique=True)
    labels = Column(ARRAY(Integer), default=[])
    t_labels = Column(ARRAY(Integer))
    gm_msgid = Column(BigInteger, unique=True)
    gm_thrid = Column(BigInteger)

    flags = Column(ARRAY(String), default=[])
    t_flags = Column(ARRAY(String))
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
    in_reply_to = Column(String)
    message_id = Column(String)

    text = Column(String)
    html = Column(String)

    @property
    def full_labels(self):
        if self._labels is None:
            self._labels = dict((l.id, l) for l in (
                session.query(Label)
                .order_by(Label.weight.desc())
            ))
        return [self._labels[l] for l in self.labels if l in self._labels]

    @property
    def unread(self):
        return self.SEEN not in self.flags

    @property
    def starred(self):
        return self.STARRED in self.flags


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autocommit=True)
session = Session()
