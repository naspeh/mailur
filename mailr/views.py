from collections import OrderedDict
from itertools import groupby
from urllib.parse import urlencode

import requests
from werkzeug.routing import Map, Rule, BaseConverter, ValidationError

from . import log, conf, imap, syncer
from .db import Email, Label, session

rules = [
    Rule('/auth/', endpoint='auth'),
    Rule('/auth-callback/', endpoint='auth_callback'),
    Rule('/auth-refresh/', endpoint='auth_refresh'),
    Rule('/check-imap/', endpoint='check_imap'),

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

OAUTH_URL = 'https://accounts.google.com/o/oauth2/auth'
OAUTH_URL_TOKEN = 'https://accounts.google.com/o/oauth2/token'


def auth(env):
    params = {
        'client_id': conf('google_id'),
        'scope': 'https://mail.google.com/',
        'login_hint': conf('email'),
        'redirect_uri': env.url_for('auth_callback', _external=True),
        'access_type': 'offline',
        'response_type': 'code',
        'approval_prompt': 'force',
    }
    return env.redirect('?'.join([OAUTH_URL, urlencode(params)]))


def auth_callback(env):
    res = requests.post(OAUTH_URL_TOKEN, data={
        'code': env.request.args['code'],
        'client_id': conf('google_id'),
        'client_secret': conf('google_secret'),
        'redirect_uri': env.url_for('auth_callback', _external=True),
        'grant_type': 'authorization_code'
    })
    if res.ok:
        conf.update(google_response=res.json())
        return 'OK'
    return '%s: %s' % (res.reason, res.text)


def auth_refresh(env):
    res = requests.post(OAUTH_URL_TOKEN, data={
        'client_id': conf('google_id'),
        'client_secret': conf('google_secret'),
        'refresh_token': conf('google_response', {}).get('refresh_token'),
        'grant_type': 'refresh_token',
    })
    if res.ok:
        new = dict(conf('google_response'), **res.json())
        conf.update(google_response=new)
        return 'OK'
    return '%s: %s' % (res.reason, res.text)


def check_imap(env):
    try:
        imap.client()
    except ValueError:
        return env.make_response('FAIL', status=500)
    return 'OK'


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
        env.abort(404)

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
