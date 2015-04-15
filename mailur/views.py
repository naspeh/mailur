from functools import wraps

from werkzeug.routing import Map, Rule
from psycopg2 import DataError

from . import imap
from .db import cursor

rules = [
    Rule('/auth/', endpoint='auth'),
    Rule('/auth-callback/', endpoint='auth_callback'),
    Rule('/auth-refresh/', endpoint='auth_refresh'),

    Rule('/', endpoint='index'),
    Rule('/init/', endpoint='init'),
    Rule('/raw/<id>/', endpoint='raw'),
]
url_map = Map(rules)


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
        if not env.is_logined:
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
@cursor()
def raw(cur, env, id):
    from tests import open_file

    try:
        cur.execute('SELECT raw, header FROM emails WHERE id=%s LIMIT 1', [id])
    except DataError:
        raw = None
    else:
        raw = cur.fetchone()
    if not raw:
        env.abort(404)

    raw = raw[0] or raw[1]
    desc = env.request.args.get('desc')
    if env.is_logined and desc:
        name = '%s--%s.txt' % (id, desc)
        with open_file('files_parser', name, mode='bw') as f:
            f.write(raw)
    return env.make_response(raw, content_type='text/plain')
