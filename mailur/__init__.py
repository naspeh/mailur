import json
import logging
import logging.config
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import bcrypt
import psycopg2
import valideer as v
from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.http import parse_authorization_header
from werkzeug.utils import cached_property

from . import db

log = logging.getLogger(__name__)


def get_conf(conf=None):
    if not conf:
        with open('conf.json', 'br') as f:
            conf = json.loads(f.read().decode())

    def exists(v):
        return Path(v).exists()

    app_dir = Path(__file__).parent.resolve()
    base_dir = app_dir.parent
    log_handlers = ['console_simple', 'console_detail']
    with v.parsing(additional_properties=False):
        schema = v.parse({
            'debug': v.Nullable(bool, False),
            'readonly': v.Nullable(bool, True),
            'enabled': v.Nullable(bool, True),
            '+pg_username': str,
            '+pg_password': str,
            '+google_id': str,
            '+google_secret': str,
            '+cookie_secret': str,
            '+token': v.Nullable(str, str(uuid4())),
            'log_handlers': (
                v.Nullable([v.Enum(log_handlers)], log_handlers[:1])
            ),
            'log_level': v.Nullable(str, 'DEBUG'),
            'log_file': v.Nullable(str, ''),
            'path_attachments': v.Nullable(str, str(base_dir / 'attachments')),
            'path_theme': v.Nullable(exists, str(app_dir / 'theme')),
            'imap_body_maxsize': v.Nullable(int, 50 * 1024 * 1024),
            'imap_batch_size': v.Nullable(int, 2000),
            'imap_debug': v.Nullable(int, 0),
            'smtp_debug': v.Nullable(bool, False),
            'async_pool': v.Nullable(int, 0),
            'ui_ga_id': str,
            'ui_is_public': v.Nullable(bool, False),
            'ui_use_names': v.Nullable(bool, True),
            'ui_per_page': v.Nullable(int, 100),
            'ui_greeting': v.Nullable(str, ''),
        })
    conf = schema.validate(conf)

    path = Path(conf['path_attachments'])
    if not path.exists():
        path.mkdir()
    return conf


class Env:
    def __init__(self, username=None, conf=None):
        conf = get_conf(conf)
        self.conf_default = conf
        self.conf_logging = setup_logging(conf)

        self.storage = db.Storage(self)
        self.emails = db.Emails(self)
        self.tasks = db.Tasks(self)

        # General setup
        self.username = None
        self.request = None

        # User specific setup
        if username is not None:
            self.username = username

    def __call__(self, key, default=None):
        value = self.conf[key]
        return default if value is None else value

    @property
    def users(self):
        with self.db_cursor({'dbname': 'postgres'}) as cur:
            cur.execute('''
            SELECT datname FROM pg_database
            WHERE datistemplate = false;
            ''')
            for row in cur:
                username = row[0].find('mailur_') == 0 and row[0][7:]
                if not username:
                    continue

                yield username

    @property
    def username(self):
        return self.__dict__['username']

    @username.setter
    def username(self, value):
        self.__dict__['username'] = value

        # Clear cached properties
        self.__dict__.pop('db', None)
        self.__dict__.pop('conf', None)
        self.__dict__.pop('email', None)

    @cached_property
    def db(self):
        return self.db_connect()

    @cached_property
    def conf(self):
        try:
            custom = self.storage.get('conf', {})
        except (psycopg2.ProgrammingError, ValueError) as e:
            log.error(e)
            custom = {}
        return get_conf(dict(self.conf_default, **custom))

    @cached_property
    def email(self):
        return self.storage.get('gmail_info', {}).get('email')

    @property
    def attachments_dir(self):
        return str(Path(self('path_attachments')) / self.username)

    @property
    def db_name(self):
        if not self.username:
            raise ValueError('No username')
        return 'mailur_%s' % self.username

    def db_connect(self, **params):
        dbname = params.pop('dbname', None)
        params = dict({
            'host': 'localhost',
            'user': self.conf_default['pg_username'],
            'password': self.conf_default['pg_password'],
            'dbname': dbname or self.db_name
        }, **params)
        try:
            return psycopg2.connect(**params)
        except psycopg2.OperationalError:
            raise ValueError('Wrong username or credentials')

    @contextmanager
    def db_cursor(self, connect_params=None, **params):
        connect_params = connect_params or {}
        with self.db_connect(**connect_params) as conn:
            with conn.cursor(**params) as cur:
                yield cur

    def _sql(self, method, sql, *args, **opts):
        opts = dict({'cursor_factory': psycopg2.extras.DictCursor}, **opts)
        cur = self.db.cursor(**opts)
        getattr(cur, method)(sql, *args)
        return cur

    def sql(self, *args, **kwargs):
        return self._sql('execute', *args, **kwargs)

    def sqlmany(self, *args, **kwargs):
        return self._sql('executemany', *args, **kwargs)

    def mogrify(self, sql, params):
        result = self.db.cursor().mogrify(sql, params)
        return result.decode()

    @property
    def request(self):
        return self.__dict__['request']

    @request.setter
    def request(self, value):
        self.__dict__.pop('session', None)  # clear cached property
        self.__dict__['request'] = value

    @cached_property
    def session(self):
        if self.request is None:
            return
        secret_key = self('cookie_secret').encode()
        session = SecureCookie.load_cookie(self.request, secret_key=secret_key)
        return session

    @property
    def valid_token(self):
        if self.request is not None:
            header = self.request.headers.get('authorization')
            if header:
                auth = parse_authorization_header(header)
                return auth and auth.username == self('token')
        return False

    @property
    def valid_username(self):
        if not self.username:
            username = self.session and self.session.get('username')
            if not username:
                return False

            self.username = username

        # check db_connect
        try:
            self.db_connect()
            return True
        except ValueError:
            return False

    def check_auth(self, username, password):
        self.username = username
        if not self.valid_username:
            return False

        ph = self.storage.get('password_hash')
        if not ph:
            return False

        ph = ph.encode()
        if bcrypt.hashpw(password.encode(), ph) != ph:
            return False

        self.session['username'] = self.username
        return True


def setup_logging(conf):
    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'simple': {
                'format': (
                    '%(asctime)s|'
                    '%(module)-10.10s|'
                    '%(levelname)-3.3s|%(message)s'
                ),
                'datefmt': '%H:%M:%S'
            },
            'detail': {
                'format': (
                    '%(asctime)s|'
                    '%(process)d:%(thread)d|'
                    '%(module)-10.10s|'
                    '%(levelname)-3.3s|%(message)s'
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
                'handlers': conf.get('log_handlers', ['console_detail']),
                'level': conf.get('log_level', 'INFO'),
                'propagate': True
            }
        }
    }
    log_file = conf.get('log_file')
    if log_file:
        config['handlers'].update(file={
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'INFO',
            'formatter': 'detail',
            'filename': log_file,
            'maxBytes': 10485760,
            'backupCount': 20,
            'encoding': 'utf8'
        })
        config['loggers']['']['handlers'].append('file')
    logging.config.dictConfig(config)
    return config
