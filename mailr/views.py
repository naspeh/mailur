from functools import wraps
from itertools import groupby

from sqlalchemy import func
from werkzeug.routing import Map, Rule, BaseConverter, ValidationError

from . import log, conf, imap, syncer, async_tasks
from .db import Email, Label, session

rules = [
    Rule('/auth/', endpoint='auth'),
    Rule('/auth-callback/', endpoint='auth_callback'),
    Rule('/auth-refresh/', endpoint='auth_refresh'),

    Rule('/', endpoint='index'),
    Rule('/compose/', endpoint='compose'),
    Rule('/labels/', endpoint='labels'),
    Rule('/emails/', endpoint='emails'),
    Rule('/gm-thread/<int:id>/', endpoint='gm_thread'),
    Rule('/raw/<email:email>/', endpoint='raw'),
    Rule('/mark/<name>/', methods=['POST'], endpoint='mark'),
    Rule('/copy/<label:label>/<label:to>/', methods=['POST'], endpoint='copy'),
    Rule('/sync/', endpoint='sync'),
]


def model_converter(model, pk='id'):
    class Converter(BaseConverter):
        def to_python(self, value):
            row = session.query(model)\
                .filter(getattr(model, pk) == value).first()
            if not row:
                raise ValidationError
            return row

        def to_url(self, value):
            return str(value)
    return Converter

converters = {
    'label': model_converter(Label),
    'email': model_converter(Email, pk='uid')
}
url_map = Map(rules, converters=converters)


def auth(env):
    redirect_uri = env.url_for('auth_callback', _external=True)
    return env.redirect(imap.auth_url(redirect_uri))


def auth_callback(env):
    redirect_uri = env.url_for('auth_callback', _external=True)
    try:
        imap.auth_callback(redirect_uri, env.request.args['code'])
        env.login()
        return env.redirect_for('index')
    except imap.AuthError as e:
        return str(e)


def login_required(func):
    @wraps(func)
    def inner(env, *a, **kw):
        if not conf('opt:is_public') and not env.is_logined:
            return env.redirect_for('auth')
        return func(env, *a, **kw)
    return inner


@login_required
def index(env):
    ctx = {
        l.alias: l for l in Label.get_all()
        if l.alias in [Label.A_INBOX, Label.A_STARRED, Label.A_TRASH]
    }
    return env.render('index.tpl', ctx)


@login_required
def compose(env):
    return env.render('compose.tpl')


def get_labels():
    labels = (
        session.query(Label)
        .filter(~Label.attrs.any(Label.NOSELECT))
        .order_by(Label.weight, Label.index)
    )
    return labels


@login_required
def emails(env):
    emails = (
        session.query(*Email.columns())
        .order_by(Email.gm_thrid, Email.date.desc())
    )
    if 'label' in env.request.args:
        label_id = env.request.args['label']
        label = session.query(Label).filter(Label.id == label_id).one()
        emails = emails.filter(Email.labels.has_key(label_id))
    elif 'email' in env.request.args:
        email = env.request.args['email']
        emails = emails.filter(
            func.array_to_string(Email.from_ + Email.to, ',')
            .contains('<%s>' % email)
        )
        label = None
    else:
        env.abort(404)

    groups = groupby(emails, lambda v: v.gm_thrid)
    groups = [(k, list(v)) for k, v in groups]
    counts = {k: len(v) for k, v in groups}
    emails = (Email.model(v[0]) for k, v in groups)
    emails = sorted(emails, key=lambda v: v.date, reverse=True)
    return env.render('emails.tpl', {
        'emails': emails,
        'counts': counts,
        'label': label,
        'labels': get_labels()
    })


@login_required
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
    return env.render('thread.tpl', {
        'thread': thread,
        'groups': groups,
        'few_showed': few_showed,
        'labels': get_labels()
    })


@login_required
def mark(env, name):
    label_all = Label.get_by_alias(Label.A_ALL)
    store = {
        'starred': ('+FLAGS', Email.STARRED),
        'unstarred': ('-FLAGS', Email.STARRED),
        'read': ('+FLAGS', Email.SEEN),
        'unread': ('-FLAGS', Email.SEEN),
    }
    label_id = env.request.form.get('label', label_all.id)
    label = Label.get(label_id)
    uids = env.request.form.getlist('ids[]', type=int)
    emails = session.query(Email.uid, Email.labels).filter(Email.uid.in_(uids))
    emails = {m.uid: m for m in emails}
    if name in store:
        key, value = store[name]
        im = imap.client()
        im.select('"%s"' % label.name, readonly=False)
        imap.store(im, uids, key, value)
    elif name == 'archived':
        label_in = Label.get_by_alias(Label.A_INBOX)
        im = imap.client()
        im.select('"%s"' % label_in.name, readonly=False)
        for uid in uids:
            if str(label_in.id) not in emails[uid].labels:
                continue
            _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
            if not data[0]:
                continue
            uid_ = data[0].decode().split(' ')[0]
            res = im.uid('STORE', uid_, '+FLAGS', '\\Deleted')
            log.info('Archive(%s): %s', uid, res)

        syncer.fetch_emails(im, label_in, with_bodies=False)
    elif name == 'deleted':
        label_trash = Label.get_by_alias(Label.A_TRASH)
        im = imap.client()
        im.select('"%s"' % label.name, readonly=False)
        for uid in uids:
            _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
            if not data[0]:
                continue
            uid_ = data[0].decode().split(' ')[0]
            res = im.uid('COPY', uid_, '"%s"' % label_trash.name)
            log.info('Delete(%s): %s', uid, res)
        syncer.fetch_emails(im, label_trash, with_bodies=False)
    else:
        env.abort(404)

    syncer.fetch_emails(im, label, with_bodies=False)
    return 'OK'


@login_required
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


@login_required
def sync(env):
    async_tasks.sync()
    return 'OK'


@login_required
def raw(env, email):
    from tests import open_file

    desc = env.request.args.get('desc')
    if env.is_logined and desc:
        name = '%s--%s.txt' % (email.uid, desc)
        with open_file('files_parser', name, mode='bw') as f:
            f.write(email.body)
    return env.make_response(email.body, content_type='text/plain')
