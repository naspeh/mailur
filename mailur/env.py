import hashlib
import logging.config
from pathlib import Path

import psycopg2
import valideer as v
from werkzeug.utils import cached_property

from . import db


class Missing:
    def __str__(self):
        return 'No value'


def get_conf(conf):
    app_dir = Path(__file__).parent.resolve()
    base_dir = app_dir.parent

    def exists(v):
        return Path(v).exists()

    schema_ = {
        '+pg_username': str,
        '+pg_password': str,
        '+google_id': str,
        '+google_secret': str,
        '+cookie_secret': str,
        'log_handlers': v.Nullable(
            [v.Enum(['console_simple', 'console_detail'])], ['console_simple']
        ),
        'log_level': v.Nullable(str, 'DEBUG'),
        'log_file': v.Nullable(str, ''),
        'path_attachments': v.Nullable(exists, str(base_dir / 'attachments')),
        'path_theme': v.Nullable(exists, str(app_dir / 'theme')),
        'imap_body_maxsize': v.Nullable(int, 50 * 1024 * 1024),
        'imap_batch_size': v.Nullable(int, 2000),
        'imap_debug': v.Nullable(int, 0),
        'ui_ga_id': str,
        'ui_is_public': v.Nullable(bool, False),
        'ui_use_names': v.Nullable(bool, True),
    }
    with v.parsing(additional_properties=False):
        schema = v.parse(schema_)

    # Validate two times to pass default values through the schema also
    conf = schema.validate(conf)
    conf = schema.validate(conf)
    return conf


class Env:
    def __init__(self, conf):
        self.conf = get_conf(conf)
        setup_logging(self)

        self.accounts = db.Accounts(self)
        self.emails = db.Emails(self)

    def __call__(self, key, default=None):
        value = self.conf[key]
        return default if isinstance(value, Missing) else value

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
