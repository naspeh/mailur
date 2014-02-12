
from sqlalchemy import (
    create_engine, Column, func,
    DateTime, String, Integer, BigInteger, SmallInteger
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

engine = create_engine('postgresql+psycopg2://test:test@/mail')
Base = declarative_base()
drop_all = lambda: Base.metadata.drop_all(engine)


class Label(Base):
    __tablename__ = 'labels'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    weight = Column(SmallInteger, default=0)

    attrs = Column(ARRAY(String))
    delim = Column(String)
    name = Column(String, unique=True)

    uids = Column(ARRAY(BigInteger))

    @property
    def human_name(self):
        return self.name.replace('[Gmail]/', '')

    @property
    def unread(self):
        count = (
            session.query(func.count(Email.id))
            .filter(Email.uid.in_(self.uids))
            .filter(~Email.flags.any('\\Seen'))
            .scalar()
        )
        return count

    @property
    def exists(self):
        return len(self.uids)


class Email(Base):
    __tablename__ = 'emails'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    uid = Column(BigInteger, unique=True)
    gm_msgid = Column(BigInteger, unique=True)
    gm_thrid = Column(BigInteger)

    flags = Column(ARRAY(String))
    internaldate = Column(DateTime)
    size = Column(Integer, index=True)
    header = Column(String)
    body = Column(String)

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
    def unread(self):
        return '\\Seen' not in self.flags


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autocommit=True)
session = Session()
