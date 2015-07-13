import hashlib
import socket
import time
from contextlib import ContextDecorator, contextmanager

from . import log


@contextmanager
def with_lock(target):
    name = 'mailur:%s' % hashlib.md5(target.encode()).hexdigest()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.bind('\0' + name)
    except IOError:
        log.warn('Target %r is running already' % target)
        raise SystemExit()

    yield
    sock.close()


class Timer(ContextDecorator):
    __slots__ = ('start', 'finish', 'label')

    def __init__(self, label=None):
        self.reset()
        self.label = label

    def __enter__(self):
        self.reset()

    def __exit__(self, *a, **kw):
        duration = self.duration
        if self.label:
            log.info('%s for %.2fs', self.label, duration)

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
