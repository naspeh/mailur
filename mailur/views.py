from functools import wraps

from werkzeug.routing import Map, Rule

from . import imap, parser, filters as f

rules = [
    Rule('/auth/', endpoint='auth'),
    Rule('/auth-callback/', endpoint='auth_callback'),

    Rule('/', endpoint='index'),
    Rule('/init/', endpoint='init'),
    Rule('/raw/<id>/', endpoint='raw'),
    Rule('/body/<id>/', endpoint='body'),
    Rule('/thread/<id>/', endpoint='thread'),
    Rule('/in/<name>/', endpoint='label')
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


def ctx_email(env, msg):
    fmt_from = f.get_addr_name if env('ui_use_names') else f.get_addr
    return {
        'subj': msg['subj'],
        'pinned?': '\\Starred' in msg['labels'],
        'body_url': env.url_for('body', id=msg['id']),
        'thread_url': env.url_for('thread', id=msg['thrid']),
        'time': f.format_dt(env, msg['time']),
        'time_human': f.humanize_dt(env, msg['time']),
        'from': msg['fr'][0],
        'from_short': fmt_from(msg['fr']),
        'gravatar': f.get_gravatar(msg['fr'])
    }


@login_required
def thread(env, id):
    fmt = env.request.args.get('fmt', 'html')
    i = env.sql('''
    SELECT id, thrid, subj, labels, time, fr
      FROM emails
      WHERE thrid = %s
      ORDER BY time
    ''', [id])
    ctx = [ctx_email(env, e) for e in i]
    if fmt == 'json':
        return env.to_json(ctx)
    return env.render_body('emails', {'emails': ctx})


@login_required
def label(env, name):
    fmt = env.request.args.get('fmt', 'html')
    i = env.sql('''
    SELECT id, thrid, subj, labels, time, fr
      FROM emails
      WHERE id IN (
        SELECT thrid FROM emails
          WHERE %s=ANY(labels)
          GROUP BY thrid
          LIMIT 100
      )
      ORDER BY time DESC
    ''', [name])
    ctx = [ctx_email(env, e) for e in i]
    if fmt == 'json':
        return env.to_json(ctx)
    return env.render_body('label', {'emails': ctx})


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

    i = env.sql('SELECT raw, header FROM emails WHERE id=%s LIMIT 1', [id])
    row = i.fetchone()
    raw = row[0] or row[1]
    if env('debug') and env.request.args.get('save'):
        name = '%s--test.txt' % id
        with open_file('files_parser', name, mode='bw') as f:
            f.write(raw)
    return env.make_response(raw, content_type='text/plain')
