import functools as ft
import os
import re

import valideer as v
from werkzeug.routing import Map, Rule

from . import parser, syncer, imap, filters as f

rules = [
    Rule('/auth/', endpoint='auth'),
    Rule('/auth-callback/', endpoint='auth_callback'),

    Rule('/', endpoint='index'),
    Rule('/init/', endpoint='init'),
    Rule('/raw/<id>/', endpoint='raw'),
    Rule('/body/<id>/', endpoint='body'),
    Rule('/thread/<id>/', endpoint='thread'),
    Rule('/emails/', endpoint='emails'),
    Rule('/search/<q>/', endpoint='search'),
    Rule('/mark/', endpoint='mark'),
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
    labels = [
        {'name': l, 'url': env.url_for('emails', {'in': l})}
        for l in labels
    ]
    return {'labels': labels}


def init(env):
    schema = v.parse({'+offset': v.Range(v.AdaptTo(int), min_value=0)})
    args = schema.validate(env.request.args)
    env.session['tz_offset'] = args['offset']
    return 'OK'


def ctx_emails(env, items, extra=None, thread=False):
    emails, last = [], None
    for i in items:
        last = i['updated'] if not last or i['updated'] > last else last
        email = {
            'id': i['id'],
            'thrid': i['thrid'],
            'domid': i['id'] if thread else i['thrid'],
            'subj': i['subj'],
            'subj_human': f.humanize_subj(i['subj']),
            'subj_url': env.url_for('emails', {'subj': i['subj']}),
            'preview': f.get_preview(i['text']),
            'pinned?': '\\Starred' in i['labels'],
            'unread?': '\\Unread' in i['labels'],
            'body_url': env.url_for('body', id=i['id']),
            'raw_url': env.url_for('raw', id=i['id']),
            'thread_url': env.url_for('thread', id=i['thrid']),
            'time': f.format_dt(env, i['time']),
            'time_human': f.humanize_dt(env, i['time']),
            'from': f.format_from(env, i['fr'][0]),
            'from_short': f.format_from(env, i['fr'][0], short=True),
            'from_url': env.url_for('emails', {'person': i['fr'][0][1]}),
            'gravatar': f.get_gravatar(i['fr'][0][1]),
            'attachments?': {'items': [
                {'name': os.path.basename(a), 'url': '/attachments/%s' % a}
                for a in i['attachments']
            ]} if i.get('attachments') else False,
        }
        email['hash'] = f.get_hash(email)
        email.update(**ctx_labels(env, i['labels']))
        if extra:
            for k in extra:
                email[k] = i[k]
        emails.append(email)

    emails = emails and {
        'items': emails,
        'length': len(emails),
        'last': str(last)
    }
    return {'emails?': emails, 'thread?': thread}


def ctx_labels(env, labels, ignore=None):
    ignore = ignore or []
    noslash = re.compile(r'(?:\\\\)*(?![\\]).*')
    return {'labels?': {'items': [
        {'name': l, 'url': env.url_for('emails', {'in': l})}
        for l in sorted(set(labels))
        if (
            l not in ignore and
            (noslash.match(l) or l in ('\\Inbox', '\\Junk', '\\Trash'))
        )
    ]} if labels else False}


@login_required
@adapt_fmt('emails')
def thread(env, id):
    i = env.sql('''
    SELECT
        id, thrid, subj, labels, time, fr, text, updated,
        html, attachments
    FROM emails
    WHERE thrid = %s
    ORDER BY time
    ''', [id])
    msgs, labels = [], set()

    def emails():
        for n, msg in enumerate(i):
            msg = dict(msg)
            labels.update(msg['labels'])
            if n == 0:
                subj = msg['subj']
            msg['subj_changed?'] = f.is_subj_changed(msg['subj'], subj)
            msg['subj_human'] = f.humanize_subj(msg['subj'], subj)
            msg['body?'] = (
                '\\Unread' in msg['labels'] and
                {'text': f.humanize_html(msg['html'], reversed(msgs))}
            )
            yield msg
            msgs.append(msg['html'])

    extra = ('subj_changed?', 'subj_human', 'body?')
    ctx = ctx_emails(env, emails(), extra, thread=True)
    if ctx['emails?']:
        emails = ctx['emails?']['items']
        msg = emails[-1]
        msg['body?'] = {'text': f.humanize_html(msgs[-1], reversed(msgs[:-1]))}
        ctx['subj'] = emails[0]['subj']
        ctx.update(**ctx_labels(env, labels))
    return ctx


@login_required
@adapt_fmt('emails')
def emails(env):
    schema = v.parse({
        'person': str,
        'subj': str,
        'in': str
    })
    args = schema.validate(env.request.args)
    if args.get('in'):
        where = env.mogrify('%s = ANY(labels)', [args['in']])
    elif args.get('subj'):
        where = env.mogrify('%s = subj', [args['subj']])
    elif args.get('person'):
        where = env.mogrify(
            '(%(fr)s IN (SELECT fr[1][2]) OR %(fr)s IN (SELECT "to"[1][2]))',
            {'fr': args['person']}
        )
    else:
        return env.abort(400)

    i = env.sql('''
    WITH
    thread_ids AS (
        SELECT thrid, max(time)
        FROM emails
        WHERE {where}
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
        id, t.thrid, subj, t.labels, time, fr, text, updated,
        count, subj_list
    FROM emails e
    JOIN threads t ON e.thrid = t.thrid
    WHERE id IN (
        SELECT id FROM emails
        WHERE id = ANY(t.id_list)
        ORDER BY time DESC LIMIT 1
    )
    ORDER BY time DESC
    '''.format(where=where))

    def emails():
        for msg in i:
            base_subj = dict(msg["subj_list"])
            base_subj = base_subj[sorted(base_subj)[0]]
            msg = dict(msg)
            msg['labels'] = set(sum(msg['labels'], [])) - {args.get('in')}
            msg['count'] = msg['count'] > 1 and msg['count']
            msg['subj_human'] = f.humanize_subj(msg['subj'], base_subj)
            yield msg

    ctx = ctx_emails(env, emails(), ('count', 'subj_human'))
    return ctx


@login_required
@adapt_fmt('emails')
def search(env, q):
    i = env.sql('''
    WITH search AS (
        SELECT id
        FROM emails_search
        WHERE document @@ plainto_tsquery('simple', %(query)s)
        ORDER BY ts_rank(document, plainto_tsquery('simple', %(query)s)) DESC
        LIMIT 100
    )
    SELECT
        e.id, thrid, subj, labels, time, fr, text, updated,
        html, attachments
    FROM emails e, search s
    WHERE e.id = s.id
    ''', {'query': q})

    def emails():
        for msg in i:
            msg = dict(msg)
            msg['subj_changed?'] = True
            yield msg

    ctx = ctx_emails(env, emails(), ['subj_changed?'], thread=True)
    ctx['thread?'] = True
    return ctx


@login_required
def body(env, id):
    def get_html(raw, parents=None):
        def parse(raw):
            if not raw:
                return ''
            res = parser.parse(raw.tobytes(), id, env('path_attachments'))
            return res['html']

        return f.humanize_html(parse(raw), (parse(r) for r in parents or []))

    row = env.sql('''
    SELECT raw, thrid, time FROM emails WHERE id=%s LIMIT 1
    ''', [id]).fetchone()
    if row:
        i = env.sql('''
        SELECT raw FROM emails
        WHERE thrid=%s AND id!=%s AND time<%s
        ORDER BY time DESC
        ''', [row['thrid'], id, row['time']])
        result = get_html(row['raw'], (p['raw'] for p in i))
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


@login_required
def mark(env):
    syncer.mark(env, env.request.json, new=True)
    return 'OK'
