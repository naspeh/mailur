import re
from functools import wraps
from itertools import groupby

import trafaret as t
from sqlalchemy import func
from werkzeug.routing import Map, Rule, BaseConverter, ValidationError

from . import conf, cache, imap, async_tasks
from .db0 import Email, Label, session

rules = [
    Rule('/auth/', endpoint='auth'),
    Rule('/auth-callback/', endpoint='auth_callback'),
    Rule('/auth-refresh/', endpoint='auth_refresh'),

    Rule('/', endpoint='index'),
    Rule('/init/', endpoint='init'),
    Rule('/compose/', endpoint='compose'),
    Rule('/labels/', endpoint='labels'),
    Rule('/emails/', endpoint='emails'),
    Rule('/gm-thread/<int:id>/', endpoint='gm_thread'),
    Rule('/raw/<email:email>/', endpoint='raw'),
    Rule('/mark/<name>/', methods=['POST'], endpoint='mark'),
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
        if not conf('ui_is_public') and not env.is_logined:
            return env.redirect_for('auth')
        return func(env, *a, **kw)
    return inner


def cached_view(timeout=conf('cached_view_timeout', 1)):
    def wrapper(func):
        @wraps(func)
        def inner(env, *a, **kw):
            key = env.request.full_path
            value = cache.get(key)
            if value is None:
                value = func(env, *a, **kw)
                cache.set(key, value, timeout=timeout)
            return value
        return inner
    return wrapper


@login_required
def index(env):
    ctx = {
        l.alias: l for l in Label.get_all()
        if l.alias in [Label.A_INBOX, Label.A_STARRED, Label.A_TRASH]
    }
    return env.render('index.tpl', ctx)


@login_required
def init(env):
    env.session['tz_offset'] = env.request.args.get('offset', type=int) or 0
    return 'OK'


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
@cached_view()
def emails(env):
    label = None
    emails = (
        session.query(Email.gm_thrid)
        .order_by(Email.gm_thrid, Email.date.desc())
    )
    if 'label' in env.request.args:
        label_id = env.request.args['label']
        label = session.query(Label).filter(Label.id == label_id).one()
        emails = emails.filter(Email.labels.has_key(label_id)).all()
    elif 'email' in env.request.args:
        email = env.request.args['email']
        emails = emails.filter(
            func.array_to_string(Email.from_ + Email.to, ',')
            .contains('<%s>' % email)
        ).all()
    elif 'subj' in env.request.args:
        subj = env.request.args['subj']
        subj = re.sub(r'([()\[\]{}_*|+?])', r'\\\1', subj)
        emails = emails.filter(
            Email.subject.op('SIMILAR TO')('(_{2,10}:)*\ ?' + subj)
        ).all()
    elif 'q' in env.request.args and env.request.args['q']:
        query = env.request.args['q']
        query = query.replace(' ', '\ ')
        emails = session.execute(
            '''
            SELECT id, gm_thrid
            FROM emails_search
            WHERE document @@ to_tsquery('simple', :query)
            ORDER BY ts_rank(document, to_tsquery('simple', :query)) DESC
            ''',
            {'query': query}
        ).fetchall()
    else:
        env.abort(404)

    if len(emails):
        threads = list(
            session.query(
                Email.gm_thrid,
                func.count('*').label('count'),
                func.max(Email.uid).label('uid')
            )
            .filter(Email.gm_thrid.in_([m.gm_thrid for m in emails]))
            .group_by(Email.gm_thrid)
        )
        emails = (
            session.query(Email)
            .filter(Email.uid.in_([m.uid for m in threads]))
            .order_by(Email.date.desc())
        ).all()
        counts = {t.gm_thrid: t.count for t in threads}
    else:
        emails, counts = [], {}

    return env.render('emails.tpl', {
        'emails': emails,
        'emails_count': len(emails),
        'counts': counts,
        'label': label,
        'labels': get_labels()
    })


@login_required
@cached_view()
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
        'subject': emails[-1].human_subject() if emails else None,
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
    schema = t.Dict({
        t.Key('use_threads', False): t.Bool,
        'ids': t.List(t.Int)
    })
    try:
        data = schema.check(env.request.json)
    except t.DataError as e:
        return env.abort(400, e)
    uids = data['ids']
    if data['use_threads']:
        uids = session.query(Email.uid).filter(Email.gm_thrid.in_(uids))
        uids = [r.uid for r in uids]
    async_tasks.mark(name, uids, add_task=True)
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
            f.write(email.raw.body)
    return env.make_response(email.raw.body, content_type='text/plain')
