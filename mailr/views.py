from collections import OrderedDict

from werkzeug.routing import Map, Rule, BaseConverter, ValidationError

from . import log, imap, syncer
from .db import Email, Label, session

rules = [
    Rule('/', endpoint='index'),
    Rule('/labels/', endpoint='labels'),
    Rule('/label/<label:label>/', endpoint='label'),
    Rule('/gm-thread/<int:id>/', endpoint='gm_thread'),
    Rule('/raw/<email:email>/', endpoint='raw'),
    Rule('/store/<label:label>/', methods=['POST'], endpoint='store'),
    Rule('/archive/<label:label>/', methods=['POST'], endpoint='archive'),
    Rule('/copy/<label:label>/<label:to>/', methods=['POST'], endpoint='copy'),
    Rule('/sync/', endpoint='sync'),
]


def model_converter(model):
    class Converter(BaseConverter):
        def to_python(self, value):
            row = session.query(model).filter(model.id == value).first()
            if not row:
                raise ValidationError
            return row

        def to_url(self, value):
            return str(value)
    return Converter

converters = {
    'label': model_converter(Label),
    'email': model_converter(Email)
}
url_map = Map(rules, converters=converters)


def index(env):
    return env.render('index.tpl')


def labels(env):
    labels = (
        session.query(Label)
        .filter(~Label.attrs.any(Label.NOSELECT))
        .order_by(Label.is_folder.desc(), Label.weight.desc(), Label.index)
    )
    return env.render('labels.tpl', labels=labels)


def label(env, label):
    emails = (
        session.query(Email)
        .filter(Email.labels.has_key(str(label.id)))
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


def store(env, label):
    ids = env.request.form.getlist('ids[]', type=int)
    key = env.request.form.get('key')
    value = env.request.form.get('value')
    unset = env.request.form.get('unset', False, type=bool)
    im = imap.client()
    im.select('"%s"' % label.name, readonly=False)
    imap.store(im, ids, key, value, unset)
    syncer.fetch_emails(im, label, with_bodies=False)
    return 'OK'


def archive(env, label):
    uids = env.request.form.getlist('ids[]', type=int)
    label_all = Label.get(lambda l: '\\All' in l.attrs)
    label_trash = Label.get(lambda l: '\\Trash' in l.attrs)

    im = imap.client()
    im.select('"%s"' % label.name, readonly=False)
    for uid in uids:
        _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
        uid_ = data[0].decode().split(' ')[0]
        if label_trash == label:
            res = im.uid('COPY', uid_, '"%s"' % label_all.name)
            log.info('Archive(%s): %s', uid, res)
        else:
            res = im.uid('STORE', uid_, '+FLAGS', '\\Deleted')
            log.info('Delete(%s): %s', uid, res)

    syncer.fetch_emails(im, label, with_bodies=False)
    return 'OK'


def copy(env, label, to):
    uids = env.request.form.getlist('ids[]', type=int)
    im = imap.client()
    im.select('"%s"' % label.name, readonly=False)
    for uid in uids:
        _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
        uid_ = data[0].decode().split(' ')[0]
        res = im.uid('COPY', uid_, '"%s"' % to.name)
        log.info('Copy(%s from %s to %s): %s', uid, label.name, to.name, res)

    syncer.fetch_emails(im, label, with_bodies=False)
    syncer.fetch_emails(im, to, with_bodies=False)
    return 'OK'


def sync(env):
    syncer.sync_gmail(False)
    return 'OK'


def raw(env, email):
    from tests import open_file

    desc = env.request.args.get('desc')
    if desc:
        name = '%s--%s.txt' % (email.uid, desc)
        with open_file('files_parser', name, mode='bw') as f:
            f.write(email.body)
    return env.make_response(email.body, content_type='text/plain')
