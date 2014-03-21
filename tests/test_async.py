from unittest.mock import patch

from sqlalchemy import event

from mailr import async_tasks
from mailr.db import engine, session, drop_all, Task

trans = None


def setup():
    global trans
    trans = engine.begin()

    @event.listens_for(session, 'after_transaction_end')
    def restart_savepoint(session, transaction):
        if transaction.nested and not transaction._parent.nested:
            session.begin_nested()


def teardown():
    global trans
    trans.transaction.rollback()
    drop_all()


def test_sync():
    tasks = session.query(Task).filter(Task.name == Task.N_SYNC)
    assert tasks.count() == 0
    async_tasks.sync()
    assert tasks.count() == 1
    async_tasks.sync()
    assert tasks.count() == 1

    task = tasks.first()
    assert task.is_new

    with patch('mailr.async_tasks.syncer') as mok:
        async_tasks.process_all()
        assert mok.sync_gmail.called

    task = tasks.first()
    assert not task.is_new
    assert task.duration
