from unittest.mock import patch

from sqlalchemy import event

from namail import syncer, async_tasks
from namail.db import engine, session, init, clear, Task

trans = None


def setup():
    global trans
    init()
    trans = engine.begin()

    @event.listens_for(session, 'after_transaction_end')
    def restart_savepoint(session, transaction):
        if transaction.nested and not transaction._parent.nested:
            session.begin_nested()


def teardown():
    global trans
    trans.transaction.rollback()
    clear()


def test_sync():
    tasks = session.query(Task).filter(Task.name == Task.N_SYNC)
    assert tasks.count() == 0
    async_tasks.sync()
    assert tasks.count() == 1
    async_tasks.sync()
    assert tasks.count() == 1

    task = tasks.first()
    assert task.is_new

    with patch('namail.syncer.sync_gmail') as mok:
        syncer.process_tasks()
        assert mok.called

    task = tasks.first()
    assert not task.is_new
    assert task.duration
