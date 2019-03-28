import hashlib
import os
import signal
import time
from contextlib import contextmanager

from gevent import sleep

from . import conf


class Error(Exception):
    pass


@contextmanager
def global_scope(target, timeout=180, wait=3, force=False):
    path = '/tmp/%s' % (hashlib.md5(target.encode()).hexdigest())

    def is_locked():
        if not os.path.exists(path):
            return

        with open(path) as f:
            pid = f.read()

        # Check if process exists
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            os.remove(path)
            return

        elapsed = time.time() - os.path.getctime(path)
        if elapsed > timeout or force:
            try:
                os.kill(int(pid), signal.SIGQUIT)
                os.remove(path)
            except Exception:
                pass
            return
        return elapsed

    locked = True
    for i in range(wait):
        locked = is_locked()
        if not locked:
            break
        sleep(1)

    if locked:
        msg = (
            '%r is locked (for %.2f minutes). Remove file %r to run'
            % (target, locked / 60, path)
        )
        raise Error(msg)

    try:
        with open(path, 'w') as f:
            f.write(str(os.getpid()))
        yield
    finally:
        os.remove(path)


@contextmanager
def user_scope(target, **opts):
    target = '%s:%s' % (conf['USER'], target)
    with global_scope(target, **opts):
        yield
