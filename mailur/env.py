import hashlib
import logging.config
import os

import psycopg2
from werkzeug.utils import cached_property

from . import db


class Missing:
    def __str__(self):
        return 'No value'


def get_conf(conf):
    app_dir = os.path.abspath(os.path.dirname(__file__))
    base_dir = os.path.abspath(os.path.join(app_dir, '..'))

    defaults = {
        'pg_username': Missing(),
        'pg_password': Missing(),
        'google_id': Missing(),
        'google_secret': Missing(),
        'cookie_secret': Missing(),
        'password': Missing(),
        'log_handlers': ['console_simple'],
        'log_level': 'DEBUG',
        'path_attachments': os.path.join(base_dir, 'attachments'),
        'path_theme': os.path.join(app_dir, 'theme'),
        'imap_body_maxsize': 50 * 1024 * 1024,
        'imap_batch_size': 2000,
        'imap_debug': 0,
        'ui_ga_id': '',
        'ui_is_public': False,
        'ui_use_names': True,
    }
    conf = dict(defaults, **conf)
    return conf


class Env:
    def __init__(self, conf):
        self.conf = get_conf(conf)
        setup_logging(self)

        self.accounts = db.Accounts(self)
        self.emails = db.Emails(self)

    def __call__(self, key, default=None):
        return self.conf.get(key, default)

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


def setup_logging(env):
    conf = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'simple': {
                'format': '%(levelname)s %(asctime)s  %(message)s',
                'datefmt': '%H:%M:%S'
            },
            'detail': {
                'format': (
                    '%(asctime)s[%(threadName)-12.12s][%(levelname)-5.5s] '
                    '%(name)s %(message)s'
                )
            }
        },
        'handlers': {
            'console_simple': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'simple',
                'stream': 'ext://sys.stdout'
            },
            'console_detail': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'detail',
                'stream': 'ext://sys.stdout'
            },
        },
        'loggers': {
            '': {
                'handlers': env('log_handlers', ['console_detail']),
                'level': env('log_level', 'INFO'),
                'propagate': True
            }
        }
    }
    log_file = env('log_file')
    if log_file:
        conf['handlers'].update(file={
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'INFO',
            'formatter': 'detail',
            'filename': log_file,
            'maxBytes': 10485760,
            'backupCount': 20,
            'encoding': 'utf8'
        })
        conf['loggers']['']['handlers'].append('file')
    logging.config.dictConfig(conf)
