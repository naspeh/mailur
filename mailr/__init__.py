import logging
import json
import os
import time

log = logging.getLogger(__name__)
app_dir = os.path.abspath(os.path.dirname(__file__))
base_dir = os.path.abspath(os.path.join(app_dir, '..'))


class _Conf:
    def __init__(self):
        filename = os.environ.get('MAILR_CONF', 'conf.json')
        self.path = os.path.join(base_dir, filename)

        with open(self.path, 'br') as f:
            conf = json.loads(f.read().decode())
        self.data = conf

    def update(self, *args, **kwargs):
        self.data.update(*args, **kwargs)
        content = json.dumps(
            self.data, sort_keys=True, indent=4, separators=(',', ': ')
        )
        with open(self.path, 'bw') as f:
            f.write(content.encode())

    def __call__(self, key, default=None):
        return self.data.get(key, default)

    @property
    def theme_dir(self):
        return os.path.join(app_dir, 'theme')

    @property
    def attachments_dir(self):
        dir_ = self('attachments_dir', 'attachments')
        return os.path.join(base_dir, dir_)

conf = _Conf()


class Timer:
    __slots__ = ('start', 'finish')

    def __init__(self):
        self.reset()

    def reset(self):
        self.start = time.time()

    @property
    def duration(self):
        self.finish = time.time()
        return self.finish - self.start

    def time(self, reset=True):
        duration = self.duration
        if reset:
            self.reset()
        return duration
