from collections import OrderedDict

from werkzeug.exceptions import abort
from werkzeug.routing import Map, Rule

from .db import Email, Label, session

url_map = Map([
    Rule('/', endpoint='index'),
    Rule('/label/<int:id>/', endpoint='label'),
    Rule('/gm-thread/<int:id>/', endpoint='gm_thread'),
    Rule('/raw/<int:id>/', endpoint='raw'),
    Rule('/change-label/', methods=['POST'], endpoint='change_label'),
])


def index(env):
    labels = (
        session.query(Label)
        .filter(~Label.attrs.any(Label.NOSELECT))
        .order_by(Label.is_folder.desc(), Label.weight.desc(), Label.index)
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
    return env.render('list.tpl', emails=list(emails))


def gm_thread(env, id):
    emails = (
        session.query(Email)
        .filter(Email.gm_thrid == id)
        .order_by(Email.date)
    )
    return env.render('list.tpl', emails=emails)


def change_label(env):
    ids = env.request.form.getlist('ids[]', type=int)
    labels = env.request.form.getlist('labels[]', type=int)
    unset = env.request.form.get('unset', False)
    print(ids, labels, unset)
    return 'OK'


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
