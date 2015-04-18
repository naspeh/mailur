import json
import logging
import logging.config
import os

log = logging.getLogger(__name__)
app_dir = os.path.abspath(os.path.dirname(__file__))
base_dir = os.path.abspath(os.path.join(app_dir, '..'))


class _Conf:
    def __init__(self):
        filename = os.environ.get('MAILUR_CONF', 'conf.json')
        self.path = os.path.join(base_dir, filename)

        with open(self.path, 'br') as f:
            conf = json.loads(f.read().decode())

        defaults = {
            'attachments_dir': 'attachments',
            'imap_body_maxsize': 50 * 1024 * 1024,
            'imap_batch_size': 2000,
            'imap_debug': 0,
            'ui_ga_id': '',
            'ui_is_public': False,
            'ui_use_names': True,
        }
        self.data = dict(defaults, **conf)
        self.setup_logging()

    def __call__(self, key, default=None):
        return self.data.get(key, default)

    @property
    def theme_dir(self):
        return os.path.join(app_dir, 'theme')

    @property
    def attachments_dir(self):
        dir_ = self('attachments_dir')
        return os.path.join(base_dir, dir_)

    def setup_logging(self):
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
                    'handlers': self('log_handlers', ['console_detail']),
                    'level': self('log_level', 'INFO'),
                    'propagate': True
                }
            }
        }
        log_file = self('log_file')
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

conf = _Conf()
