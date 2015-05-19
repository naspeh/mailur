import functools as ft

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
    def inner(env, *a, **kw):
        if not (env.is_logined or env('ui_is_public')):
            return env.redirect_for('auth')
        return func(env, *a, **kw)

    return ft.wraps(func)(inner)


def adapt_fmt(tpl):
    def inner(env, *a, **kw):
        fmt = env.request.args.get('fmt', 'html')

        ctx = inner.func(env, *a, **kw)
        if fmt == 'json':
            return env.to_json(ctx)
        return env.render_body(tpl, ctx)

    def wrapper(func):
        inner.func = func
        return ft.wraps(func)(inner)
    return wrapper


@login_required
@adapt_fmt('index')
def index(env):
    i = env.sql('SELECT DISTINCT unnest(labels) FROM emails;')
    labels = sorted(r[0] for r in i.fetchall())
    labels = [{'name': l, 'url': env.url_for('label', name=l)} for l in labels]
    return {'labels': labels}


def init(env):
    env.session['tz_offset'] = env.request.args.get('offset', type=int) or 0
    return 'OK'


def ctx_emails(env, items):
    fmt_from = f.get_addr_name if env('ui_use_names') else f.get_addr
    emails = [{
        'id': i['id'],
        'subj': i['subj'],
        'subj_human': f.humanize_subj(i['subj']),
        'preview': f.get_preview(i),
        'pinned?': '\\Starred' in i['labels'],
        'unread?': '\\Unread' in i['labels'],
        'body_url': env.url_for('body', id=i['id']),
        'raw_url': env.url_for('raw', id=i['id']),
        'thread_url': env.url_for('thread', id=i['thrid']),
        'time': f.format_dt(env, i['time']),
        'time_human': f.humanize_dt(env, i['time']),
        'from': i['fr'][0],
        'from_short': fmt_from(i['fr']),
        'gravatar': f.get_gravatar(i['fr'])
    } for i in items]
    return emails


@login_required
@adapt_fmt('emails')
def thread(env, id):
    i = env.sql('''
    SELECT id, thrid, subj, labels, time, fr, text, html
      FROM emails
      WHERE thrid = %s
      ORDER BY time
    ''', [id])

    emails = ctx_emails(env, i)
    last = emails[-1]
    last['last?'] = True
    last['body'] = body(env, last['id'])
    subj = emails[0]['subj']
    for msg in emails:
        msg['subj_changed?'] = f.is_subj_changed(msg, subj)
    return {'emails': emails, 'thread?': True, 'subj': subj}


@login_required
@adapt_fmt('emails')
def label(env, name):
    i = env.sql('''
    SELECT id, thrid, subj, labels, time, fr, text, html
      FROM emails
      WHERE id IN (
        SELECT thrid FROM emails
          WHERE %s=ANY(labels)
          GROUP BY thrid
          LIMIT 100
      )
      ORDER BY time DESC
    ''', [name])
    return {'emails': ctx_emails(env, i)}


@login_required
def body(env, id):
    i = env.sql('SELECT raw FROM emails WHERE id=%s LIMIT 1', [id])
    raw = i.fetchone()[0]
    if raw:
        result = parser.parse(raw.tobytes(), id, env('path_attachments'))
        result = f.humanize_html(result['html'])
    else:
        result = ''
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
