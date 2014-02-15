from werkzeug.exceptions import abort
from werkzeug.routing import Map, Rule

from .db import Email, Label, session

url_map = Map([
    Rule('/', endpoint='index'),
    Rule('/label/<int:id>/', endpoint='label'),
    Rule('/raw/<int:id>/', endpoint='raw')
])


def index(env):
    labels = (
        session.query(Label)
        #.filter(Label.weight > 0)
        .order_by(Label.weight.desc())
    )
    return env.render('index.tpl', labels=labels)


def label(env, id):
    label = session.query(Label).filter(Label.id == id).first()
    if not label:
        abort(404)

    emails = (
        session.query(Email)
        .filter(Email.labels.any(label.id))
        #.filter(Email.in_reply_to.__eq__(None))
        .order_by(Email.date.desc())
    )
    return env.render('list.tpl', emails=emails)


def raw(env, id):
    from tests import open_file

    email = session.query(Email).filter(Email.id == id).first()
    if not email:
        abort(404)

    desc = env.request.args.get('desc')
    if desc:
        name = '%s--%s.txt' % (email.uid, desc)
        body = email.body if email.body else email.header
        with open_file('emails', name, mode='bw') as f:
            f.write(body.encode())
    return env.make_response(email.body, content_type='text/plain')
