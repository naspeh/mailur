from uuid import UUID
from collections import OrderedDict

import psycopg2
import psycopg2.extras

psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)
psycopg2.extensions.register_adapter(UUID, psycopg2.extras.UUID_adapter)
pre = '''
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE OR REPLACE FUNCTION fill_updated()
RETURNS TRIGGER AS $$
BEGIN
   IF row(NEW.*) IS DISTINCT FROM row(OLD.*) THEN
      NEW.modified = now();
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


def create_index(table, field):
    return '''
    DROP INDEX IF EXISTS ix_{0}_{1};
    CREATE INDEX ix_{0}_{1} ON {0} ({1})
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
    def insert(cls, items):
        fields = sorted(f for f in items[0])
        error = set(fields) - set(cls._fields)
        if error:
            raise ValueError('Fields are not exists %s' % error)

        sql = 'INSERT INTO {table} ({fields}) VALUES ({values})'.format(
            table=cls._name,
            fields=', '.join('"%s"' % i for i in fields),
            values=', '.join('%%(%s)s' % i for i in fields),
        )
        with connect() as cur:
            cur.executemany(sql, items)
            return cur


class Email(Table):
    __slots__ = ()

    _name = 'emails'
    _post_table = '; '.join([
        fill_updated(_name),
        create_index(_name, 'size'),
        create_index(_name, 'in_reply_to'),
        create_index(_name, 'msgid')
    ])

    id = 'uuid PRIMARY KEY DEFAULT gen_random_uuid()'
    created = 'timestamp NOT NULL DEFAULT current_timestamp'
    updated = 'timestamp NOT NULL DEFAULT current_timestamp'
    thrid = 'uuid NOT NULL REFERENCES emails(id)'

    raw = 'oid'
    size = 'integer'
    time = 'timestamp'
    labels = 'integer[]'

    subj = 'character varying'
    fr = 'character varying[]'
    to = 'character varying[]'
    cc = 'character varying[]'
    bcc = 'character varying[]'
    reply_to = 'character varying[]'
    sender = 'character varying'
    sender_time = 'timestamp'
    msgid = 'character varying'
    in_reply_to = 'character varying'
    refs = 'character varying[]'

    text = 'character varying'
    html = 'character varying'
    attachments = 'character varying[]'
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
    conn = None

    def __init__(self, **params):
        self.params = params

    def __enter__(self):
        params = dict(self.params)
        post = params.pop('post', None)
        params = dict({
            'host': 'localhost',
            'user': 'postgres',
            'dbname': 'test'
        }, **params)
        self.conn = conn = psycopg2.connect(**params)
        if post:
            post(conn)
        self.cur = cur = conn.cursor()
        return cur

    def __exit__(self, type, value, traceback):
        if type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def __call__(self, func):
        def inner(*a, **kw):
            with connect(**self.params) as cur:
                return func(cur, *a, **kw)
        return inner


def init(reset=False):
    if reset:
        params = {
            'dbname': 'postgres',
            'post': lambda c: c.set_isolation_level(0)
        }
        with connect(**params) as cur:
            cur.execute('DROP DATABASE IF EXISTS test')
            cur.execute('CREATE DATABASE test')

    with connect() as cur:
        cur.execute(pre + create_table(Email))
