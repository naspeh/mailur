from .db import session, Task, Email, Label


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


def mark(name, uids, add_task=False):
    emails = session.query(Email).filter(Email.uid.in_(uids))
    l_inbox = str(Label.get_by_alias(Label.A_INBOX).id)
    l_star = str(Label.get_by_alias(Label.A_STARRED).id)
    l_all = str(Label.get_by_alias(Label.A_ALL).id)
    l_trash = str(Label.get_by_alias(Label.A_TRASH).id)
    if name == 'starred':
        emails.update({
            Email.labels: Email.labels + {l_star: ''},
            Email.flags: Email.flags + {Email.STARRED: ''}
        }, synchronize_session=False)

    elif name == 'unstarred':
        emails.update({
            Email.labels: Email.labels.delete(l_star),
            Email.flags: Email.flags.delete(Email.STARRED)
        }, synchronize_session=False)

    elif name == 'unread':
        emails.update({
            Email.flags: Email.flags.delete(Email.SEEN)
        }, synchronize_session=False)

    elif name == 'read':
        emails.update({
            Email.flags: Email.flags + {Email.SEEN: ''}
        }, synchronize_session=False)

    elif name == 'inboxed':
        emails.update({
            Email.labels: (
                Email.labels.delete(l_trash) + {l_all: '', l_inbox: ''}
            )
        }, synchronize_session=False)

    elif name == 'archived':
        emails.update({
            Email.labels: (
                Email.labels - {l_inbox: '', l_trash: ''} + {l_all: ''}
            )
        }, synchronize_session=False)

    elif name == 'deleted':
        emails.update({
            Email.labels: {l_trash: ''}
        }, synchronize_session=False)

    else:
        raise ValueError('Unknown name')

    if add_task:
        session.add(Task(name='mark_' + name, uids=uids))
