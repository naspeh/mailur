import collections
import datetime as dt
import json
import logging
import logging.config
import os
import pathlib
import uuid


def get_conf():
    conf = {}
    defaults = {
        'debug': True,
        'uid': uuid.uuid4().hex[:8],
        'secret': uuid.uuid4().hex,
        'github_basic': None,
        'logs_root': '/var/tmp/mlr-ci',
        'smtp_host': None,
        'smtp_port': 587,
        'smtp_user': None,
        'smtp_pass': None,
        'notify_subj': 'Failed check on naspeh/mailur',
    }
    for name, value in defaults.items():
        conf[name] = os.environ.get('CI_%s' % name.upper(), value)
    conf = collections.namedtuple('Conf', conf.keys())(*conf.values())
    return conf


conf = get_conf()
log = logging.getLogger(__name__)
logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'f': {
        'datefmt': '%Y-%m-%d %H:%M:%S%Z',
        'format': (
            '[%(asctime)s][%(process)s][{uid}][%(levelname).3s] %(message)s'
            .format(uid=conf.uid)
        ),
    }},
    'handlers': {'h': {
        'class': 'logging.StreamHandler',
        'level': logging.DEBUG,
        'formatter': 'f',
        'stream': 'ext://sys.stdout',
    }},
    'loggers': {
        __name__: {
            'handlers': 'h',
            'level': logging.DEBUG if conf.debug else logging.INFO,
            'propagate': False
        },
        '': {
            'handlers': 'h',
            'level': logging.INFO,
            'propagate': False
        },
    }
})


def pretty_json(obj):
    if isinstance(obj, bytes):
        obj = obj.decode()
    if isinstance(obj, str):
        obj = json.loads(obj)
    return json.dumps(obj, indent=2, sort_keys=True)


def new_log_dir(sha):
    logs_root = pathlib.Path(conf.logs_root)
    logs = logs_root / 'all/{time:%Y%m%d-%H%M%S}-{rand}-{sha}/'.format(
        sha=sha[:8],
        time=dt.datetime.now(),
        rand=conf.uid[:2]
    )
    if not logs.exists():
        logs.mkdir(parents=True)

    latest = logs_root / 'latest'
    if latest.exists():
        latest.unlink()
    latest.symlink_to(logs)
    return logs
