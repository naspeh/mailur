from collections import OrderedDict

from werkzeug.exceptions import abort
from werkzeug.routing import Map, Rule

from . import log, imap, syncer
from .db import Email, Label, session

url_map = Map([
    Rule('/', endpoint='index'),
    Rule('/label/<int:id>/', endpoint='label'),
    Rule('/gm-thread/<int:id>/', endpoint='gm_thread'),
    Rule('/raw/<int:id>/', endpoint='raw'),
    Rule('/imap-store/', methods=['POST'], endpoint='imap_store'),
    Rule('/archive/<int:label>/', methods=['POST'], endpoint='archive'),
    Rule('/sync/', endpoint='sync'),
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


def imap_store(env):
    ids = env.request.form.getlist('ids[]')
    key = env.request.form.get('key')
    value = env.request.form.get('value')
    unset = env.request.form.get('unset', False, type=bool)
    im = imap.client()
    im.select('"[Gmail]/All Mail"', readonly=False)
    imap.store(im, ids, key, value, unset)
    return 'OK'


def archive(env, label):
    label = session.query(Label).filter(Label.id == label).first()
    uids = env.request.form.getlist('ids[]')
    im = imap.client()
    im.select('"%s"' % label.name, readonly=False)
    for uid in uids:
        _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
        uid_ = data[0].decode().split(' ')[0]
        res = im.uid('COPY', uid_, '"[Gmail]/All Mail"')
        log.info('Archive(%s): %s', uid_, res)
        res = im.uid('STORE', uid_, '+FLAGS', '\\Deleted')
        log.info('Delete(%s): %s', uid_, res)
    return 'OK'


def sync(env):
    syncer.sync_gmail(False)
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
