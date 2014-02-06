from .db import Label, session


def on_index(env):
    labels = session.query(Label).all()
    return ' '.join(l.name for l in labels)
