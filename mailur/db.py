from collections import OrderedDict
from functools import wraps
from uuid import UUID

import psycopg2
import psycopg2.extras

from . import conf

psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)
psycopg2.extensions.register_adapter(UUID, psycopg2.extras.UUID_adapter)


def pre():
    return '''
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";
    CREATE OR REPLACE FUNCTION fill_updated()
    RETURNS TRIGGER AS $$
    BEGIN
       IF row(NEW.*) IS DISTINCT FROM row(OLD.*) THEN
          NEW.updated = now();
          RETURN NEW;
       ELSE
          RETURN OLD;
       END IF;
    END;
    $$ language 'plpgsql';
    '''


def fill_updated(table, field='updated'):
    return '''
    DROP TRIGGER IF EXISTS fill_{0}_{1} ON {0};
    CREATE TRIGGER fill_{0}_{1} BEFORE UPDATE ON {0}
       FOR EACH ROW EXECUTE PROCEDURE fill_updated()
    '''.format(table, field)


def create_index(table, field, using=''):
    if using:
        using = 'USING %s ' % using
    return '''
    DROP INDEX IF EXISTS ix_{0}_{1};
    CREATE INDEX ix_{0}_{1} ON {0} {2}({1})
    '''.format(table, field, using)


def create_seq(table, field):
    return '''
    DROP SEQUENCE IF EXISTS seq_{0}_{1};
    CREATE SEQUENCE seq_{0}_{1};
    ALTER TABLE {0} ALTER COLUMN {1} SET DEFAULT nextval('seq_{0}_{1}')
    '''.format(table, field)


class TableMeta(type):
    def __new__(cls, name, bases, classdict):
        new = type.__new__(cls, name, bases, dict(classdict))
        new._fields = [
            k for k, v in classdict.items()
            if not k.startswith('_') and isinstance(v, str)
        ]
        return new

    @classmethod
    def __prepare__(mcls, cls, bases):
        return OrderedDict()


class Table(metaclass=TableMeta):
    @classmethod
    def insert(cls, cur, items):
        fields = sorted(f for f in items[0])
        error = set(fields) - set(cls._fields)
        if error:
            raise ValueError('Fields are not exists %s' % error)

        values = '(%s)' % (', '.join('%%(%s)s' % i for i in fields))
        values = ','.join([cur.mogrify(values, v).decode() for v in items])
        sql = 'INSERT INTO {table} ({fields}) VALUES '.format(
            table=cls._name,
            fields=', '.join('"%s"' % i for i in fields),
        )
        sql += values
        cur.execute(sql)
        return cur


class Account(Table):
    __slots__ = ()

    _name = 'accounts'
    _post_table = '; '.join([
        fill_updated(_name),
        create_seq(_name, 'id')
    ])

    id = "int PRIMARY KEY"
    email = 'varchar UNIQUE'
    type = 'varchar'
    data = 'jsonb'

    created = 'timestamp NOT NULL DEFAULT current_timestamp'
    updated = 'timestamp NOT NULL DEFAULT current_timestamp'

    @classmethod
    def get(cls, cur, email):
        cur.execute('SELECT id, data FROM accounts WHERE email=%s', (email,))
        return cur.fetchone() or (None, {})

    @classmethod
    def get_key(cls, cur, email, key):
        return cls.get(cur, email)[1].get(key)

    @classmethod
    def exists(cls, cur, email):
        cur.execute('SELECT count(*) FROM accounts WHERE email=%s', (email,))
        return cur.fetchone()[0]

    @classmethod
    def add_or_update(cls, cur, email, data):
        if cls.exists(cur, email):
            return cls.update(cur, email, data)

        cls.insert(cur, [{'type': 'gmail', 'email': email, 'data': data}])
        return cur.rowcount

    @classmethod
    def update(cls, cur, email, data):
        data = dict(cls.get(cur, email)[1], **data)
        cur.execute(
            'UPDATE accounts SET data=%s  WHERE email=%s',
            (data, email)
        )
        return cur.rowcount


class Email(Table):
    __slots__ = ()

    _name = 'emails'
    _post_table = '; '.join([
        fill_updated(_name),
        create_index(_name, 'size'),
        create_index(_name, 'in_reply_to'),
        create_index(_name, 'msgid'),
        create_index(_name, 'labels', 'GIN'),
    ])

    id = 'uuid PRIMARY KEY DEFAULT gen_random_uuid()'
    created = 'timestamp NOT NULL DEFAULT current_timestamp'
    updated = 'timestamp NOT NULL DEFAULT current_timestamp'
    thrid = 'uuid REFERENCES emails(id)'
    # account_id = 'int NOT NULL REFERENCES accounts(id)'

    header = 'bytea'
    raw = 'bytea'
    size = 'int'
    time = 'timestamp'
    labels = "varchar[] DEFAULT '{}'"

    subj = 'varchar'
    fr = "varchar[] DEFAULT '{}'"
    to = "varchar[] DEFAULT '{}'"
    cc = "varchar[] DEFAULT '{}'"
    bcc = "varchar[] DEFAULT '{}'"
    reply_to = "varchar[] DEFAULT '{}'"
    sender = 'varchar'
    sender_time = 'timestamp'
    msgid = 'varchar'
    in_reply_to = 'varchar'
    refs = "varchar[] DEFAULT '{}'"

    text = 'text'
    html = 'text'
    attachments = "varchar[] DEFAULT '{}'"
    embedded = 'jsonb'
    extra = 'jsonb'


def create_table(tbl):
    body = []
    for attr in tbl._fields:
        body.append('"%s" %s' % (attr, getattr(tbl, attr)))
    if hasattr(tbl, '_post'):
        body.append(tbl._post)
    body = ', '.join(body)
    sql = ['CREATE TABLE IF NOT EXISTS %s (%s)' % (tbl._name, body)]

    if hasattr(tbl, '_pre_table'):
        sql.insert(0, tbl._pre_table)
    if hasattr(tbl, '_post_table'):
        sql.append(tbl._post_table)
    return '; '.join(sql)


class connect():
    _conn = {}

    def __init__(self, **params):
        self.params = params
        self.dbname = params.get('dbname')

    @property
    def conn(self):
        return self._conn[self.dbname]

    def __enter__(self):
        params = dict(self.params)
        params = dict({
            'host': 'localhost',
            'user': conf('pg_username'),
            'password': conf('pg_password'),
            'dbname': conf.dbname
        }, **params)
        self._conn[self.dbname] = conn = psycopg2.connect(**params)
        return conn

    def __exit__(self, type, value, traceback):
        if type is None:
            self.conn.commit()
        else:
            self.conn.rollback()

    def __call__(self, func):
        @wraps(func)
        def inner(*a, **kw):
            with self.__class__(**self.params) as c:
                return func(c, *a, **kw)
        return inner


class cursor(connect):
    def __enter__(self):
        conn = super().__enter__()
        self.cur = cur = conn.cursor()
        return cur

    def __exit__(self, type, value, traceback):
        super().__exit__(type, value, traceback)
        self.cur.close()


def init(reset=False):
    if reset:
        with connect(dbname='postgres') as conn:
            conn.set_isolation_level(0)
            with conn.cursor() as cur:
                cur.execute('DROP DATABASE IF EXISTS %s' % conf.dbname)
                cur.execute('CREATE DATABASE %s' % conf.dbname)

    with cursor() as cur:
        cur.execute(';'.join(
            [pre()] + [create_table(t) for t in [Account, Email]]
        ))
