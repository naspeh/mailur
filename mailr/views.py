from werkzeug.exceptions import abort
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
    label = session.query(Label).filter_by(id=id).first()
    if not label:
        abort(404)

    emails = (
        session.query(Email)
        .filter(Email.labels.any(label.id))
        #.filter(Email.in_reply_to.__eq__(None))
        .order_by(Email.date.desc())
    )
    return env.render('list.tpl', emails=emails)
