from uuid import UUID

import psycopg2
import psycopg2.extras

psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)
psycopg2.extensions.register_adapter(UUID, psycopg2.extras.UUID_adapter)


def init(env, reset=False):
    if reset:
        with env.db_connect(dbname='postgres') as conn:
            conn.set_isolation_level(0)
            with conn.cursor() as cur:
                cur.execute('DROP DATABASE IF EXISTS %s' % env.db_name)
                cur.execute('CREATE DATABASE %s' % env.db_name)

    sql = '''
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
    sql += ';'.join(t.table for t in [Accounts, Emails])
    env.sql(sql)
    env.db.commit()


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
    DO $$
    BEGIN
    IF NOT EXISTS (SELECT to_regclass('seq_{0}_{1}')) THEN
        CREATE SEQUENCE seq_{0}_{1};
        ALTER TABLE {0} ALTER COLUMN {1} SET DEFAULT nextval('seq_{0}_{1}');
    END IF;
    END$$;
    '''.format(table, field)


def create_table(name, body, before=None, after=None):
    sql = ['CREATE TABLE IF NOT EXISTS %s (%s)' % (name, ', '.join(body))]
    before, after = (
        [v] if isinstance(v, str) else list(v or [])
        for v in (before, after)
    )
    return '; '.join(before + sql + after)


class Manager():
    def __init__(self, env):
        self.env = env
        self.field_names = tuple(f.split()[0].strip('"') for f in self.fields)

        # bind sql functions directly to obj
        self.sql = env.sql
        self.sqlmany = env.sqlmany

    @property
    def db(self):
        return self.env.db

    def insert(self, items):
        cur = self.db.cursor()

        fields = sorted(f for f in items[0])
        error = set(fields) - set(self.field_names)
        if error:
            raise ValueError('No fields: %s' % error)

        values = '(%s)' % (', '.join('%%(%s)s' % i for i in fields))
        values = ','.join([cur.mogrify(values, v).decode() for v in items])
        sql = 'INSERT INTO {table} ({fields}) VALUES '.format(
            table=self.name,
            fields=', '.join('"%s"' % i for i in fields),
        )
        sql += values + 'RETURNING id'
        cur.execute(sql)
        return [r[0] for r in cur]

    def update(self, values, where, params=None):
        cur = self.db.cursor()

        fields = sorted(f for f in values)
        error = set(fields) - set(self.field_names)
        if error:
            raise ValueError('No fields: %s' % error)
        values_ = ', '.join('%%(%s)s' % i for i in fields)
        values_ = cur.mogrify(values_, values).decode()
        where_ = cur.mogrify(where, params).decode()
        sql = '''
        UPDATE {table} SET ({fields}) = ({values})
          WHERE {where}
          RETURNING id
        '''.format(
            table=self.name,
            fields=', '.join('"%s"' % i for i in fields),
            values=values_,
            where=where_
        )
        cur.execute(sql)
        return [r[0] for r in cur]


class Accounts(Manager):
    name = 'accounts'
    fields = (
        'id int PRIMARY KEY',
        'email varchar UNIQUE',
        'type varchar',
        'data jsonb',

        'created timestamp NOT NULL DEFAULT current_timestamp',
        'updated timestamp NOT NULL DEFAULT current_timestamp'
    )
    table = create_table(name, fields, after=(
        fill_updated(name),
        create_seq(name, 'id')
    ))

    def get_data(self, email):
        i = self.sql('SELECT data FROM accounts WHERE email=%s', (email,))
        data = i.fetchone()
        return data['data'] if data else {}

    def exists(self, email):
        i = self.sql('SELECT count(id) FROM accounts WHERE email=%s', (email,))
        return i.fetchone()[0]

    def add_or_update(self, email, data):
        if self.exists(email):
            return self.update(email, data)

        return self.insert([{'type': 'gmail', 'email': email, 'data': data}])

    def update(self, email, data):
        data = dict(self.get_data(email), **data)
        i = self.sql(
            'UPDATE accounts SET data=%s  WHERE email=%s',
            (data, email)
        )
        return i.rowcount


class Emails(Manager):
    name = 'emails'
    fields = (
        'id uuid PRIMARY KEY DEFAULT gen_random_uuid()',
        'created timestamp NOT NULL DEFAULT current_timestamp',
        'updated timestamp NOT NULL DEFAULT current_timestamp',
        'thrid uuid REFERENCES emails(id)',
        # 'account_id int NOT NULL REFERENCES accounts(id)',

        'header bytea',
        'raw bytea',
        'size int',
        'time timestamp',
        "labels varchar[] DEFAULT '{}'",

        'subj varchar',
        "fr varchar[] DEFAULT '{}'",
        '"to" varchar[] DEFAULT \'{}\'',
        "cc varchar[] DEFAULT '{}'",
        "bcc varchar[] DEFAULT '{}'",
        "reply_to varchar[] DEFAULT '{}'",
        'sender varchar',
        'sender_time timestamp',
        'msgid varchar',
        'in_reply_to varchar',
        "refs varchar[] DEFAULT '{}'",

        'text text',
        'html text',
        "attachments varchar[] DEFAULT '{}'",
        'embedded jsonb',
        'extra jsonb',
    )
    table = create_table(name, fields, after=(
        fill_updated(name),
        create_index(name, 'size'),
        create_index(name, 'msgid'),
        create_index(name, 'in_reply_to'),
        create_index(name, 'refs', 'GIN'),
        create_index(name, 'labels', 'GIN'),
        '''
        DROP MATERIALIZED VIEW IF EXISTS emails_search;

        CREATE MATERIALIZED VIEW emails_search AS
        SELECT id, thrid,
            setweight(to_tsvector('simple', subj), 'A') ||
            setweight(to_tsvector('simple', text), 'C') ||
            setweight(to_tsvector('simple', {fr}), 'C') ||
            setweight(to_tsvector('simple', {to}), 'C') ||
            setweight(to_tsvector('simple', {cc}), 'C') ||
            setweight(to_tsvector('simple', {bcc}), 'C')
            AS document
        FROM emails;

        DROP INDEX IF EXISTS ix_emails_search;
        CREATE INDEX ix_emails_search ON emails_search USING gin(document);
        '''.format(**{
            i: '''coalesce(array_to_string("%s", ','), '')''' % i
            for i in ('fr', 'to', 'cc', 'bcc')
        })
    ))
