from functools import wraps

from psycopg2 import DataError
from werkzeug.routing import Map, Rule

from . import imap, parser, filters as f

rules = [
    Rule('/auth/', endpoint='auth'),
    Rule('/auth-callback/', endpoint='auth_callback'),

    Rule('/', endpoint='index'),
    Rule('/init/', endpoint='init'),
    Rule('/raw/<id>/', endpoint='raw'),
    Rule('/body/<id>/', endpoint='body'),
    Rule('/emails/', endpoint='emails')
]
url_map = Map(rules)


def auth(env):
    redirect_uri = env.url_for('auth_callback', _external=True)
    return env.redirect(imap.auth_url(env, redirect_uri))


def auth_callback(env):
    redirect_uri = env.url_for('auth_callback', _external=True)
    try:
        imap.auth_callback(env, redirect_uri, env.request.args['code'])
        env.login()
        return env.redirect_for('index')
    except imap.AuthError as e:
        return str(e)


def login_required(func):
    @wraps(func)
    def inner(env, *a, **kw):
        if not (env.is_logined or env('ui_is_public')):
            return env.redirect_for('auth')
        return func(env, *a, **kw)
    return inner


@login_required
def index(env):
    return 'OK'


@login_required
def init(env):
    env.session['tz_offset'] = env.request.args.get('offset', type=int) or 0
    return 'OK'


@login_required
def emails(env):
    fmt = env.request.args.get('fmt', 'html')
    i = env.sql('''
    SELECT id, subj, labels, time
      FROM emails
      ORDER BY time DESC
      LIMIT 100
    ''')
    ctx = [{
        'subj': e['subj'],
        'pinned?': '\\Starred' in e['labels'],
        'body_url': env.url_for('body', id=e['id']),
        'time': f.format_dt(env, e['time']),
        'time_human': f.humanize_dt(env, e['time'])
    } for e in i]
    if fmt == 'json':
        return env.to_json(ctx)
    return env.render_body('emails', {'emails': ctx})


@login_required
def body(env, id):
    i = env.sql('SELECT raw FROM emails WHERE id=%s LIMIT 1', [id])
    raw = i.fetchone()[0].tobytes()
    result = parser.parse(raw, id, env('path_attachments'))
    result = parser.human_html(result['html'])
    return result


@login_required
def raw(env, id):
    from tests import open_file

    try:
        i = env.sql('SELECT raw, header FROM emails WHERE id=%s LIMIT 1', [id])
    except DataError:
        raw = None
    else:
        raw = i.fetchone()
    if not raw:
        env.abort(404)

    raw = raw[0] or raw[1]
    desc = env.request.args.get('desc')
    if env.is_logined and desc:
        name = '%s--%s.txt' % (id, desc)
        with open_file('files_parser', name, mode='bw') as f:
            f.write(raw)
    return env.make_response(raw, content_type='text/plain')
