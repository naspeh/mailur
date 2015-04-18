import socket
import time
from contextlib import ContextDecorator
from functools import wraps

from . import conf, log


def with_lock(func):
    target = ':'.join([func.__module__, func.__name__, conf.path])

    @wraps(func)
    def inner(*a, **kw):
        lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        lock_socket.bind('\0' + target)
        return func(*a, **kw)
    return inner


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
