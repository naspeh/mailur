from collections import OrderedDict

import psycopg2

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


def make_index(table, field):
    return '''
    DROP INDEX IF EXISTS ix_{0}_{1};
    CREATE INDEX ix_{0}_{1} ON {0} ({1})
    '''.format(table, field)


class TableBase(type):
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


class Emails(metaclass=TableBase):
    __slots__ = ()

    _name = 'emails'
    _post_table = '; '.join([
        fill_updated(_name),
        make_index(_name, 'size'),
        make_index(_name, 'in_reply_to'),
        make_index(_name, 'msgid')
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


def init(reset=False):
    if reset:
        conn = psycopg2.connect('host=localhost user=postgres dbname=postgres')
        conn.set_isolation_level(0)
        cur = conn.cursor()
        cur.execute('DROP DATABASE IF EXISTS test')
        cur.execute('CREATE DATABASE test')
        conn.commit()

    conn = psycopg2.connect('host=localhost user=postgres dbname=test')
    cur = conn.cursor()
    sql = pre + create_table(Emails)
    cur.execute(sql)
    conn.commit()
