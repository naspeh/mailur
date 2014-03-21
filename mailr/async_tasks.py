import socket
from functools import wraps
from itertools import groupby

from . import log, syncer, Timer, conf
from .db import session, Task


def with_lock(func):
    target = ':'.join([func.__module__, func.__name__, conf.path])

    @wraps(func)
    def inner(*a, **kw):
        lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            lock_socket.bind('\0' + target)
            return func(*a, **kw)
        except socket.error:
            raise SystemExit('Already run: %s' % target)
    return inner


def sync():
    prev = (
        session.query(Task)
        .filter(Task.name == Task.N_SYNC)
        .filter(Task.is_new)
    )
    if prev.count():
        return
    else:
        session.add(Task(name='sync'))


@with_lock
def process_all():
    tasks = (
        session.query(Task)
        .with_for_update(nowait=True, of=Task)
        .filter(Task.is_new)
    )
    groups = groupby(tasks.order_by(Task.name), lambda v: v.name)
    timer = Timer()
    for name, group in groups:
        if name == 'sync':
            log.info('### Process "sync" task...')
            syncer.sync_gmail()
            duration = timer.time()
            with session.begin():
                for task in group:
                    task.is_new = False
                    task.duration = duration
                    session.merge(task)
                    log.info('# Task %s is done for %.2f', task.id, duration)
