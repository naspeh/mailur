from .db import Label, session


def on_index(env):
    labels = session.query(Label)\
        .filter(Label.weight > 0).order_by(Label.weight.desc())
    return env.render('index.tpl', labels=labels)
