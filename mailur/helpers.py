import hashlib
import os
import time
import signal
from contextlib import ContextDecorator, contextmanager

from . import log


@contextmanager
def with_lock(target):
    path = '/tmp/%s' % (hashlib.md5(target.encode()).hexdigest())
    def minutes_elapsed():
        return (time.time() - os.path.getctime(path)) / 60

    def expired(timeout=10):
        with open(path) as f:
            pid = int(f.read())
        os.path.getctime(path)
        if minutes_elapsed() > timeout:
            os.kill(pid, signal.SIGQUIT)
            os.remove(path)
            return True
        return False

    if os.path.exists(path) and not expired():
        log.warn(
            '%r is locked (for %.2f minutes). Remove file %r to run',
            target, minutes_elapsed(), path
        )
        raise SystemExit()
    else:
        try:
            with open(path, 'w') as f:
                f.write(str(os.getpid()))
            yield
        finally:
            os.remove(path)


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
