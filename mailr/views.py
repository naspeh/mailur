from collections import OrderedDict
from itertools import groupby

from werkzeug.exceptions import abort
from werkzeug.routing import Map, Rule, BaseConverter, ValidationError

from . import log, imap, syncer
from .db import Email, Label, session

rules = [
    Rule('/', endpoint='index'),
    Rule('/compose/', endpoint='compose'),
    Rule('/labels/', endpoint='labels'),
    Rule('/label/<label:label>/', endpoint='label'),
    Rule('/gm-thread/<int:id>/', endpoint='gm_thread'),
    Rule('/raw/<email:email>/', endpoint='raw'),
    Rule('/mark/<label:label>/<name>/', methods=['POST'], endpoint='mark'),
    Rule('/copy/<label:label>/<label:to>/', methods=['POST'], endpoint='copy'),
    Rule('/sync/', defaults={'label': None}, endpoint='sync'),
    Rule('/sync/<label:label>/', endpoint='sync'),
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
    ctx = {
        l.alias: l for l in Label.get_all()
        if l.alias in [Label.A_INBOX, Label.A_STARRED, Label.A_TRASH]
    }
    return env.render('index.tpl', **ctx)


def compose(env):
    return env.render('compose.tpl')


def labels(env):
    labels = (
        session.query(Label)
        .filter(~Label.attrs.any(Label.NOSELECT))
        .order_by(Label.weight, Label.index)
    )
    return env.render('labels.tpl', labels=labels)


def label(env, label):
    emails = (
        session.query(Email)
        .filter(Email.labels.has_key(str(label.id)))
        .order_by(Email.date)
    )
    emails = OrderedDict((email.gm_thrid, email) for email in emails).values()
    emails = sorted(emails, key=lambda v: v.date, reverse=True)
    return env.render('label.tpl', emails=emails, label=label)


def gm_thread(env, id):
    emails = list(
        session.query(Email)
        .filter(Email.gm_thrid == id)
        .order_by(Email.date)
    )
    few_showed = 2
    groups = []
    if emails:
        groups = groupby(emails[:-1], lambda v: (v.unread or v.starred))
        groups = [(k, list(v)) for k, v in groups]
        if groups:
            # Show title of few last messages
            latest = groups[-1]
            if not latest[0] and len(latest[1]) > few_showed:
                group_latest = (False, latest[1][-few_showed:])
                groups[-1] = (False, latest[1][:-few_showed])
                groups.append(group_latest)
            # Show title of first message
            first = groups[0]
            if not first[0] and len(first[1]) > few_showed:
                group_1st = (False, [first[1][0]])
                groups[0] = (False, first[1][1:])
                groups.insert(0, group_1st)
        # Show last message
        groups += [(True, [emails[-1]])]

    thread = {
        'subject': emails[-1].human_subject(),
        'labels': set(sum([e.full_labels for e in emails], []))
    }
    return env.render(
        'thread.tpl', thread=thread, groups=groups, few_showed=few_showed
    )


def mark(env, label, name):
    store = {
        'starred': ('+FLAGS', Email.STARRED),
        'unstarred': ('-FLAGS', Email.STARRED),
        'read': ('+FLAGS', Email.SEEN),
        'unread': ('-FLAGS', Email.SEEN),
    }
    uids = env.request.form.getlist('ids[]', type=int)
    if name in store:
        key, value = store[name]
        im = imap.client()
        im.select('"%s"' % label.name, readonly=False)
        imap.store(im, uids, key, value)
    elif name == 'archived':
        im = imap.client()
        im.select('"%s"' % label.name, readonly=False)
        for uid in uids:
            _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
            uid_ = data[0].decode().split(' ')[0]
            res = im.uid('STORE', uid_, '+FLAGS', '\\Deleted')
            log.info('Archive(%s): %s', uid, res)
    elif name == 'deleted':
        label_trash = Label.get(lambda l: l.alias == Label.A_TRASH)
        im = imap.client()
        im.select('"%s"' % label.name, readonly=False)
        for uid in uids:
            _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
            uid_ = data[0].decode().split(' ')[0]
            res = im.uid('COPY', uid_, '"%s"' % label_trash.name)
            log.info('Delete(%s): %s', uid, res)
    else:
        abort(404)

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


def sync(env, label=None):
    if label:
        im = imap.client()
        im.select('"%s"' % label.name, readonly=False)
        syncer.fetch_emails(im, label, with_bodies=True)
    else:
        syncer.sync_gmail(True)
    return 'OK'


def raw(env, email):
    from tests import open_file

    desc = env.request.args.get('desc')
    if desc:
        name = '%s--%s.txt' % (email.uid, desc)
        with open_file('files_parser', name, mode='bw') as f:
            f.write(email.body)
    return env.make_response(email.body, content_type='text/plain')
