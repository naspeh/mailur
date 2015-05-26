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
    Rule('/in/<name>/', endpoint='label'),
    Rule('/search/<q>/', endpoint='search'),
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
        elif fmt == 'body':
            return env.render(tpl, ctx)
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


def ctx_emails(env, items, extra=None):
    fmt_from = f.get_addr_name if env('ui_use_names') else f.get_addr
    emails, last = [], None
    for i in items:
        last = i['updated'] if not last or i['updated'] > last else last
        email = {
            'id': i['id'],
            'thrid': i['thrid'],
            'subj': i['subj'],
            'subj_search': env.url_for('search', q=i['subj']),
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
            'from_search': env.url_for('search', q=i['fr']),
            'gravatar': f.get_gravatar(i['fr'])
        }
        email['hash'] = f.get_hash(email)
        if extra:
            for k in extra:
                email[k] = i[k]
        emails.append(email)

    emails = emails and {
        'items': emails,
        'length': len(emails),
        'last': str(last)
    }
    return {'emails?': emails}


@login_required
@adapt_fmt('emails')
def thread(env, id):
    i = env.sql('''
    SELECT id, thrid, subj, labels, time, fr, text, html, updated
    FROM emails
    WHERE thrid = %s
    ORDER BY time
    ''', [id])

    ctx = ctx_emails(env, i)
    if ctx['emails?']:
        emails = ctx['emails?']['items']
        subj = emails[0]['subj']
        for i, msg in enumerate(emails):
            msg['subj_changed?'] = f.is_subj_changed(msg['subj'], subj)
            msg['subj_human'] = f.humanize_subj(msg['subj'], subj)
            msg['body?'] = (
                (msg['unread?'] or i == len(emails) - 1) and
                {'text': body(env, msg['id'])}
            )

    ctx['thread?'] = True
    ctx['subj'] = subj
    return ctx


@login_required
@adapt_fmt('emails')
def label(env, name):
    i = env.sql('''
    WITH
    thread_ids AS (
        SELECT thrid, max(time)
        FROM emails
        WHERE %s=ANY(labels)
        GROUP BY thrid
        ORDER BY 2 DESC
        LIMIT 100
    ),
    threads  AS (
        SELECT
            t.thrid,
            json_agg(e.labels) AS labels,
            array_agg(id) AS id_list,
            count(id) AS count,
            json_object_agg(e.time, e.subj) AS subj_list
        FROM thread_ids t
        JOIN emails e ON e.thrid = t.thrid
        GROUP BY t.thrid
    )
    SELECT
        id, t.thrid, subj, t.labels, time, fr, text, html, updated,
        count, subj_list
    FROM emails e
    JOIN threads t ON e.thrid = t.thrid
    WHERE id IN (
        SELECT id FROM emails
        WHERE id = ANY(t.id_list)
        ORDER BY time DESC LIMIT 1
    )
    ORDER BY time DESC
    ''', [name])

    def emails():
        for msg in i:
            base_subj = dict(msg["subj_list"])
            base_subj = base_subj[sorted(base_subj)[0]]
            msg = dict(msg)
            msg['labels'] = sum(msg['labels'], [])
            msg['count'] = msg['count'] > 1 and msg['count']
            msg['subj_human'] = f.humanize_subj(msg['subj'], base_subj)
            yield msg

    ctx = ctx_emails(env, emails(), ['count', 'subj_human'])
    return ctx


@login_required
@adapt_fmt('emails')
def search(env, q):
    q = '"%s"' % q
    i = env.sql('''
    WITH search AS (
        SELECT id
        FROM emails_search
        WHERE document @@ plainto_tsquery('simple', %(query)s)
        ORDER BY ts_rank(document, plainto_tsquery('simple', %(query)s)) DESC
        LIMIT 100
    )
    SELECT e.id, thrid, subj, labels, time, fr, text, html, updated
    FROM emails e, search s
    WHERE e.id = s.id
    ''', {'query': q})

    def emails():
        for msg in i:
            msg = dict(msg)
            msg['body'] = msg['html']
            msg['subj_changed?'] = True
            yield msg

    ctx = ctx_emails(env, emails(), ['body', 'subj_changed?'])
    ctx['thread?'] = True
    return ctx


@login_required
def body(env, id):
    i = env.sql('SELECT raw, thrid FROM emails WHERE id=%s LIMIT 1', [id])
    row = i.fetchone()
    if row:
        i = env.sql('''
        SELECT html FROM emails WHERE thrid=%s AND id!=%s ORDER BY time DESC
        ''', [row[1], id])
        msgs = [p[0] for p in i]
        result = parser.parse(row[0].tobytes(), id, env('path_attachments'))
        result = f.humanize_html(result['html'], msgs)
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
