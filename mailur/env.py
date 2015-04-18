import hashlib

import psycopg2
from werkzeug.utils import cached_property

from . import db


class Env():
    def __init__(self, conf):
        self.conf = conf
        self.accounts = db.Accounts(self)
        self.emails = db.Emails(self)

    def __call__(self, key, default=None):
        return self.conf(key, default)

    @property
    def db_name(self):
        return 'mailur_%s' % hashlib.sha1(self('email').encode()).hexdigest()

    def db_connect(self, **params):
        params = dict({
            'host': 'localhost',
            'user': self('pg_username'),
            'password': self('pg_password'),
            'dbname': self.db_name
        }, **params)
        conn = psycopg2.connect(**params)
        return conn

    @cached_property
    def db(self):
        return self.db_connect()

    def _sql(self, method, sql, *args, **options):
        options = dict({
            'cursor_factory': psycopg2.extras.DictCursor,
        }, **options)
        cur = self.db.cursor(**options)
        getattr(cur, method)(sql, *args)
        return cur

    def sql(self, *args, **kwargs):
        return self._sql('execute', *args, **kwargs)

    def sqlmany(self, *args, **kwargs):
        return self._sql('executemany', *args, **kwargs)
