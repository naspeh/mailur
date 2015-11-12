import json
import logging
import logging.config
import os
import shutil
import uuid
from contextlib import contextmanager
from email.utils import parseaddr
from pathlib import Path

import bcrypt
import psycopg2
import valideer as v
from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.utils import cached_property

from . import db

log = logging.getLogger(__name__)


def get_conf(conf=None):
    if not conf:
        with open('conf.json', 'br') as f:
            conf = json.loads(f.read().decode())

    exists = v.Condition(lambda v: Path(v).exists())
    strip_slash = v.AdaptBy(lambda v: str(v).rstrip('/'))

    app_dir = Path(__file__).parent.resolve()
    base_dir = app_dir.parent
    log_handlers = ['console_simple', 'console_detail', 'file']
    with v.parsing(additional_properties=False):
        schema = v.parse({
            'debug': v.Nullable(bool, False),
            '+pg_username': str,
            '+pg_password': str,
            '+cookie_secret': str,
            'google_id': str,
            'google_secret': str,
            'readonly': v.Nullable(bool, True),
            'enabled': v.Nullable(bool, True),
            'log_handlers': (
                v.Nullable([v.Enum(log_handlers)], log_handlers[:1])
            ),
            'log_level': v.Nullable(str, 'DEBUG'),
            'log_file': v.Nullable(str, ''),
            'path_attachments': v.Nullable(str, str(base_dir / 'attachments')),
            'path_theme': v.Nullable(exists, str(base_dir / 'front')),
            'imap_body_maxsize': v.Nullable(int, 50 * 1024 * 1024),
            'imap_batch_size': v.Nullable(int, 2000),
            'imap_debug': v.Nullable(int, 0),
            'smtp_debug': v.Nullable(bool, False),
            'async_pool': v.Nullable(int, 0),
            'ui_ga_id': v.Nullable(str, ''),
            'ui_is_public': v.Nullable(bool, False),
            'ui_use_names': v.Nullable(bool, True),
            'ui_per_page': v.Nullable(int, 100),
            'ui_greeting': v.Nullable(str, ''),
            'ui_ws_proxy': v.Nullable(bool, False),
            'ui_ws_enabled': v.Nullable(bool, True),
            'ui_ws_timeout': v.Nullable(int, 1000),
            'ui_firebug': v.Nullable(bool, False),
            'ui_thread_few': v.Nullable(int, 5),
            'host_ws': v.Nullable(str, 'ws://localhost/async/'),
            'host_web': v.Nullable(strip_slash, 'http://localhost:8000'),
            'search_lang': v.Nullable([str], ['simple', 'english']),
        })
    conf = schema.validate(conf)

    path = Path(conf['path_attachments'])
    if not path.exists():
        path.mkdir()
    return conf


class Theme():
    def __init__(self, env):
        self.base_path = Path(env('path_theme'))

    def path(self, subpath=None):
        if subpath is None:
            return self.base_path
        return self.base_path / subpath

    def read(self, subpath):
        path = self.path(subpath)
        if path.exists():
            with path.open('br') as f:
                return f.read()

    def write(self, subpath, data, rewrite=False):
        path = self.path(subpath)
        if not rewrite and path.exists():
            return

        if isinstance(data, str):
            data = data.encode()

        os.makedirs(str(path.parent), exist_ok=True)
        with path.open('bw') as f:
            return f.write(data)


class Files(Theme):
    def __init__(self, env):
        self.base_url = '/attachments/%s' % env.username
        self.base_path = Path(env('path_attachments')) / env.username

    def subpath(self, name, **params):
        targets = {
            'compose': lambda thrid: 'compose/%s' % (thrid or 'new'),
        }
        return targets[name](**params)

    def url(self, subpath=None):
        if subpath is None:
            return self.base_url
        return '/'.join((self.base_url, subpath))

    def to_dict(self, path, type=None, name=None):
        return {
            'path': str(self.path(path)),
            'url': self.url(path),
            'maintype': type and type.split('/')[0],
            'type': type,
            'name': name
        }

    def to_db(self, path, type=None, name=None):
        return {
            'path': path,
            'type': type,
            'name': name
        }

    def copy(self, src, dest):
        src, dest = self.path(src), self.path(dest)
        if src.exists():
            if dest.exists():
                shutil.rmtree(str(dest))
            shutil.copytree(str(src), str(dest))
        return dest

    def rm(self, subpath):
        path = self.path(subpath)
        if path.exists():
            shutil.rmtree(str(path))


class Env:
    def __init__(self, username=None, conf=None):
        conf = get_conf(conf)
        self.conf_default = conf
        self.conf_logging = setup_logging(conf)

        self.storage = db.Storage(self)
        self.emails = db.Emails(self)

        # General setup
        self.username = None
        self.request = None
        self.theme = Theme(self)

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
        self.__dict__.pop('token', None)
        self.__dict__.pop('files', None)

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

    def equal_email(self, addr):
        addr = parseaddr(addr)[1]
        return addr.lower() == self.email.lower()

    @cached_property
    def token(self):
        return self.storage.get('token')

    @cached_property
    def files(self):
        return Files(self)

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
            auth = self.request.authorization
            if auth:
                self.username = auth.username
                return self.valid_username and auth.password == self.token
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

    def set_password(self, value=None, reset=False):
        if reset:
            token = str(uuid.uuid4())
            self.storage.set('password_token', token)
            self.db.commit()
            return token

        if not value:
            raise ValueError('Password should set')
        h = bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()
        self.storage.set('password_hash', h)
        self.storage.set('token', str(uuid.uuid4()))
        self.storage.rm('password_token')
        self.db.commit()

    def check_password_token(self, token):
        password_token = self.storage.get('password_token')
        if password_token and password_token == token:
            return True
        return False

    def add_tasks(self, tasks, name='mark'):
        items = [
            {'key': 'task:%s:%s' % (name, uuid.uuid4()), 'value': t}
            for t in tasks
        ]
        if not items:
            return []
        return self.storage.insert(items)

    @cached_property
    def templates(self):
        return {
            n.stem: self.theme.read(n)
            for n in self.theme.path().glob('*.mustache')
        }

    def render(self, name, ctx=None):
        from pystache import Renderer

        render = Renderer(partials=self.templates).render
        tpl = self.templates[name]
        return render(tpl, ctx)


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
