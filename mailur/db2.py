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
    CREATE TRIGGER fill_{0}_{1}
       BEFORE UPDATE ON {0}
       FOR EACH ROW EXECUTE PROCEDURE fill_updated()
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
        (
            'DROP INDEX IF EXISTS ix_{0}_{1};'
            'CREATE INDEX ix_{0}_{1} ON {0} ({1})'
            .format(_name, 'size')
        )
    ])

    uid = 'uid uuid PRIMARY KEY DEFAULT gen_random_uuid()'
    created = 'created timestamp NOT NULL DEFAULT current_timestamp'
    updated = 'updated timestamp NOT NULL DEFAULT current_timestamp'

    size = 'size integer'
    time = 'time timestamp'
    raw = 'raw oid'
    labels = 'labels integer[]'

    id = 'id character varying'
    parent = 'parent character varying'
    refs = 'refs character varying[]'

    subj = 'subj character varying'
    fr = 'fr character varying[]'
    to = '"to" character varying[]'
    cc = 'cc character varying[]'
    bcc = 'bcc character varying[]'
    sender = 'sender character varying[]'
    reply_to = 'reply_to character varying[]'
    sent_time = 'sent_time timestamp'

    text = 'text character varying'
    html = 'html character varying'
    attachments = 'attachments character varying[]'
    embedded = 'embedded json'
    extra = 'extra json'


def create_table(tbl):
    body = []
    for attr in tbl._fields:
        body.append(getattr(tbl, attr))
    if hasattr(tbl, '_post'):
        body.append(tbl._post)
    body = ', '.join(body)
    sql = ['CREATE TABLE IF NOT EXISTS %s (%s)' % (tbl._name, body)]

    if hasattr(tbl, '_pre_table'):
        sql.insert(0, tbl._pre_table)
    if hasattr(tbl, '_post_table'):
        sql.append(tbl._post_table)
    return '; '.join(sql)


def init():
    conn = psycopg2.connect('host=localhost user=postgres dbname=test')
    cur = conn.cursor()
    sql = pre + create_table(Emails)
    cur.execute(sql)
    conn.commit()
