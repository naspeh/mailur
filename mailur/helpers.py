import socket
import time
from contextlib import ContextDecorator
from functools import wraps

from . import log


def with_lock(func):
    @wraps(func)
    def inner(env, *a, **kw):
        target = ':'.join([func.__module__, func.__name__, env('path')])

        lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        lock_socket.bind('\0' + target)
        return func(env, *a, **kw)
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
