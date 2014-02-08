from werkzeug.routing import Map, Rule

from .db import Email, Label, session

url_map = Map([
    Rule('/', endpoint='index'),
    Rule('/label/<int:id>/', endpoint='label')
])


def index(env):
    labels = session.query(Label)\
        .filter(Label.weight > 0).order_by(Label.weight.desc())
    return env.render('index.tpl', labels=labels)


def label(env, id):
    uids = session.query(Label.uids).filter_by(id=id).scalar()
    emails = session.query(Email)\
        .filter(Email.uid.in_(uids))
    return env.render('list.tpl', emails=emails)
