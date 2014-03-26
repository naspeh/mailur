from itertools import groupby

from . import log, syncer, Timer, with_lock
from .db import session, Task


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
            group = list(group)
            log.info('### Process "sync" tasks %r...' % [t.id for t in group])
            syncer.sync_gmail()
            duration = timer.time()
            with session.begin():
                for task in group:
                    task.is_new = False
                    task.duration = duration
                    session.merge(task)
                    log.info('# Task %s is done for %.2f', task.id, duration)
