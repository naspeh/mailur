from collections import OrderedDict

from werkzeug.exceptions import abort
from werkzeug.routing import Map, Rule

from .db import Email, Label, session

url_map = Map([
    Rule('/', endpoint='index'),
    Rule('/label/<int:id>/', endpoint='label'),
    Rule('/gm-thread/<int:id>/', endpoint='gm_thread'),
    Rule('/raw/<int:id>/', endpoint='raw')
])


def index(env):
    labels = (
        session.query(Label)
        .filter(Label.weight > 0)
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
        .order_by(Email.date.desc())
    )
    emails = OrderedDict((email.gm_thrid, email) for email in emails).values()
    return env.render('list.tpl', emails=emails)


def gm_thread(env, id):
    emails = (
        session.query(Email)
        .filter(Email.gm_thrid == id)
        .order_by(Email.date)
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
        with open_file('files_parser', name, mode='bw') as f:
            f.write(email.body)
    return env.make_response(email.body, content_type='text/plain')
