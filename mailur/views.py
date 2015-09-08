import datetime as dt
import functools as ft
import json
import re

import valideer as v
from werkzeug.routing import Map, Rule

from . import parser, syncer, gmail, filters as f

rules = [
    Rule('/login/', endpoint='login'),
    Rule('/logout/', endpoint='logout'),
    Rule('/gmail/', endpoint='gmail_connect'),
    Rule('/gmail-callback/', endpoint='gmail_callback'),

    Rule('/', endpoint='index'),
    Rule('/check-auth/', endpoint='check_auth'),
    Rule('/init/', endpoint='init'),
    Rule('/pwd/', endpoint='reset_password'),
    Rule('/pwd/<username>/<token>/', endpoint='reset_password'),
    Rule('/sidebar/', endpoint='sidebar'),
    Rule('/raw/<id>/', endpoint='raw'),
    Rule('/body/<id>/', endpoint='body'),
    Rule('/thread/<id>/', endpoint='thread'),
    Rule('/emails/', endpoint='emails'),
    Rule('/search/', endpoint='search'),
    Rule('/mark/', endpoint='mark'),
    Rule('/new-thread/', endpoint='new_thread'),
    Rule('/compose/', endpoint='compose'),
    Rule('/preview/', endpoint='preview'),
    Rule('/search-email/', endpoint='search_email')
]
url_map = Map(rules)


def gmail_connect(env):
    redirect_uri = env.url_for('gmail_callback', _external=True)
    return env.redirect(gmail.auth_url(env, redirect_uri, env.email))


def gmail_callback(env):
    redirect_uri = env.url_for('gmail_callback', _external=True)
    try:
        gmail.auth_callback(env, redirect_uri, env.request.args['code'])
        return env.redirect_for('index')
    except gmail.AuthError as e:
        return str(e)


def login(env):
    ctx = {'greeting': env('ui_greeting')}
    if env.request.method == 'POST':
        schema = v.parse({'+username': str, '+password': str})
        args = schema.validate(env.request.form)
        if env.check_auth(args['username'], args['password']):
            return env.redirect_for('index')
        ctx = {'username': args['username'], 'error': True}
    return render_body(env, 'login', ctx)


def logout(env):
    del env.session['username']
    return env.redirect_for('index')


def init(env):
    schema = v.parse({'+offset': v.AdaptTo(int)})
    args = schema.validate(env.request.args)
    env.session['tz_offset'] = args['offset']
    return 'OK'


def login_required(func):
    def inner(env, *a, **kw):
        if env.valid_username or env.valid_token:
            return func(env, *a, **kw)
        return env.redirect_for('login')
    return ft.wraps(func)(inner)


def adapt_page():
    def inner(env, *a, **kw):
        schema = v.parse({
            'page': v.Nullable(v.AdaptTo(int), 1),
            'last': v.Nullable(str)
        })
        data = schema.validate(env.request.args)
        page, last = data['page'], data.get('last')
        page = {
            'limit': env('ui_per_page'),
            'offset': env('ui_per_page') * (page - 1),
            'last': last,
            'count': env('ui_per_page') * page,
            'current': page,
            'next': page + 1,
        }
        return wrapper.func(env, page, *a, **kw)

    def wrapper(func):
        wrapper.func = func
        return ft.wraps(func)(inner)
    return wrapper


def render(env, name, ctx):
    return env.render(name, ctx)


def render_js(env, name, ctx):
    return env.render('js', {'name': name, 'ctx': json.dumps(ctx)})


def adapt_fmt(tpl, formats=None, render=render):
    formats = formats or ['html', 'body', 'json']

    def inner(env, *a, **kw):
        default = 'body' if env.request.is_xhr else kw.pop('fmt', formats[0])
        fmt = env.request.args.get('fmt', default)
        assert fmt in formats

        ctx = wrapper.func(env, *a, **kw)
        if fmt == 'json':
            return env.to_json(ctx)
        elif fmt == 'body':
            return render(env, tpl, ctx)
        return render_body(env, tpl, ctx, render, with_sidebar=True)

    def wrapper(func):
        wrapper.func = func
        return ft.wraps(func)(inner)
    return wrapper


def render_body(env, name, ctx=None, render=render, with_sidebar=False):
    body = render(env, name, ctx)
    sname = 'all' if env('debug') else 'all.min'
    ctx = {
        'cssfile': '/theme/build/%s.css?%s' % (sname, env.theme_version),
        'jsfile': '/theme/build/%s.js?%s' % (sname, env.theme_version),
        'ga_id': env('ui_ga_id'),
        'host_ws': env('host_ws'),
        'host_web': env('host_web'),
    }
    if with_sidebar:
        ctx['sidebar'] = sidebar(env)
    if render == render_js:
        ctx['template'] = env.templates[name]
        ctx['script'] = body
    else:
        ctx['body'] = body

    return env.render('base', ctx)


def reset_password(env, username=None, token=None):
    def inner(env):
        if env.request.method == 'POST':
            schema = v.parse({'+password': str, '+password_confirm': str})
            args = schema.validate(env.request.form)
            if args['password'] != args['password_confirm']:
                raise v.SchemaError('Passwords aren\'t the same')
            env.set_password(args['password'])
            return env.redirect_for('index')
        return render_body(env, 'reset_password')

    if not username and not token:
        if env('readonly'):
            return env.abort(400)
        return login_required(inner)(env)

    env.username = username
    if env.check_password_token(token):
        return inner(env)
    return env.abort(400)


@login_required
def index(env):
    return env.redirect_for('emails', {'in': '\Inbox'})


@login_required
def check_auth(env):
    return env.to_json({'username': env.username})


@login_required
@adapt_fmt('sidebar', formats=['body', 'json'])
def sidebar(env):
    i = env.sql('''
    WITH labels(name) AS (SELECT DISTINCT unnest(labels) FROM emails)
    SELECT l.name, count(e.id) AS unread FROM labels l
    LEFT JOIN emails e ON l.name = ANY(labels)
        AND ARRAY['\\Unread', '\\All']::varchar[] <@ labels
    GROUP BY l.name
    ''')
    labels = (
        dict(l, url=env.url_for('emails', {'in': l['name']}))
        for l in i if not l['name'].startswith('%s/' % syncer.THRID)
    )
    labels = (
        dict(l, unread=0) if l['name'] in ['\\Pinned', '\\All'] else l
        for l in labels
    )
    labels = sorted(labels, key=lambda v: v['name'].lower())
    ctx = {
        'username': env.username,
        'email': env.email,
        'labels': bool(labels) and {'items': labels}
    }

    ctx['search_query'] = env.session.get('search_query', '')
    if not labels:
        ctx['gmail'] = bool(env.email)
    return ctx


def ctx_emails(env, items, domid='id'):
    emails, last = [], None
    for i in items:
        extra = i.get('_extra', {})
        email = dict({
            'id': i['id'],
            'thrid': i['thrid'],
            'domid': i[domid],
            'subj': i['subj'],
            'subj_human': f.humanize_subj(i['subj']),
            'subj_url': env.url_for('emails', {'subj': i['subj']}),
            'preview': f.get_preview(i['text'], i['attachments']),
            'pinned': '\\Pinned' in i['labels'],
            'unread': '\\Unread' in i['labels'],
            'draft': '\\Draft' in i['labels'],
            'links': ctx_links(env, i['id'], i['thrid']),
            'time': f.format_dt(env, i['time']),
            'time_human': f.humanize_dt(env, i['time']),
            'created': str(i['created']),
            'fr': ctx_person(env, i['fr'][0]),
            'to': [ctx_person(env, v) for v in i['to'] or []],
            'cc': [ctx_person(env, v) for v in i['cc'] or []],
            'labels': ctx_labels(env, i['labels'])
        }, **extra)
        last = i['created'] if not last or i['created'] > last else last
        email['hash'] = f.get_hash(email)
        emails.append(email)

    emails = bool(emails) and {
        'items': emails,
        'length': len(emails),
        'last': str(last)
    }
    return {
        'emails': emails,
        'emails_class': 'emails-byid' if domid == 'id' else ''
    }


def ctx_links(env, id, thrid=None):
    reply_url = env.url_for('compose', {'id': id})
    links = [
        {'title': 'Details', 'name': 'details'},
        {'title': 'Reply', 'name': 'reply', 'href': reply_url},
        {
            'name': 'replyall',
            'title': 'Reply to all',
            'href': reply_url + '&target=all'
        },
        {
            'name': 'forward',
            'title': 'Forward',
            'href': reply_url + '&target=forward'
        },
        {
            'name': 'thread',
            'title': 'Show full thread',
            'href': env.url_for('thread', id=thrid),
            'ifmany': True
        },
        {
            'name': 'body',
            'title': 'Show this message',
            'href': env.url_for('body', id=id),
            'ifmany': True
        },
        {
            'name': 'extract',
            'title': 'Extract new thread',
            'ifmany': True
        },
        {'title': 'Delete this message', 'name': 'delete'},
        {
            'name': 'raw',
            'title': 'Show original',
            'href': env.url_for('raw', id=id)
        },
    ]
    return links


def ctx_person(env, addr):
    email = f.get_addr(addr)
    return {
        'full': addr,
        'short': f.format_addr(env, addr),
        'url': env.url_for('emails', {'person': email}),
        'image': f.get_gravatar(email, size=75),
    }


def ctx_labels(env, labels, ignore=None):
    if not labels:
        return False
    ignore = re.compile('(%s)' % '|'.join(
        [r'^%s/.*' % re.escape(syncer.THRID)] +
        [re.escape(i) for i in ignore or []]
    ))
    pattern = re.compile('(%s)' % '|'.join(
        [r'(?:\\\\)*(?![\\]).*'] +
        [re.escape(i) for i in ('\\Inbox', '\\Spam', '\\Trash')]
    ))
    labels = [
        l for l in sorted(set(labels))
        if not ignore.match(l) and pattern.match(l)
    ]
    items = [
        {'name': l, 'url': env.url_for('emails', {'in': l})}
        for l in labels
    ]
    return {
        'items': items,
        'items_json': json.dumps(items),
        'names': labels,
        'names_json': json.dumps(labels)
    }


def ctx_all_labels(env):
    i = env.sql('SELECT DISTINCT unnest(labels) FROM emails;')
    items = sorted(r[0] for r in i.fetchall())
    items = set(items) | {'\\Spam', '\\Trash'}
    return ctx_labels(env, items)


def ctx_header(env, subj, labels=None):
    labels = list(labels) if labels else []
    buttons = (
        ([] if '\\Inbox' not in labels else [{
            'name': 'arch',
            'label': '\\Inbox',
            'action': '-',
            'title': 'Archive'
        }]) +
        ([] if '\\Trash' in labels else [
            {'name': 'del', 'label': '\\Trash', 'title': 'Delete'}
        ]) +
        ([] if '\\Spam' in labels else [
            {'name': 'spam', 'label': '\\Spam', 'title': 'Report spam'}
        ]) +
        [{'name': 'merge', 'title': 'Merge threads to one'}]
    )
    labels = ctx_labels(env, labels)
    return {
        'subj': subj,
        'buttons': buttons,
        'labels': {
            'items_json': labels['names_json'] if labels else '[]',
            'all_json': ctx_all_labels(env)['items_json'],
            'base_url': env.url_for('emails', {'in': ''})
        },
    }


def ctx_body(env, msg, msgs, show=False):
    if not show and '\\Unread' not in msg['labels']:
        return False
    attachments = msg.get('attachments')
    attachments = bool(attachments) and {'items': attachments}
    return {
        'text': f.humanize_html(msg['html'], msgs),
        'attachments': attachments
    }


def ctx_quote(env, msg, forward=False):
    return env.render('quote', {
        'subj': msg['subj'],
        'html': msg['html'],
        'fr': ', '.join(msg['fr']),
        'to': ', '.join(msg['to'] or [] + msg['cc'] or []),
        'time': msg['time'],
        'type': 'Forwarded' if forward else 'Original'
    })


@login_required
@adapt_fmt('emails')
def thread(env, id):
    i = env.sql('''
    SELECT
        id, thrid, subj, labels, time, fr, "to", text, cc, created,
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
            msg['_extra'] = {
                'subj_changed': f.is_subj_changed(msg['subj'], subj),
                'subj_human': f.humanize_subj(msg['subj'], subj),
                'body': ctx_body(env, msg, (m['html'] for m in msgs[::-1]))
            }
            yield msg
            msgs.append(msg)

    ctx = ctx_emails(env, emails())
    if ctx['emails']:
        emails = ctx['emails']['items']
        subj = f.humanize_subj(emails[0]['subj'])

        last = emails[-1]
        parents = reversed([p['html'] for p in msgs[:-1]])
        last['body'] = ctx_body(env, msgs[-1], parents, show=True)

        ctx['header'] = ctx_header(env, subj, labels)
        ctx['emails_class'] = ctx['emails_class'] + ' thread'
    return ctx


@login_required
@adapt_fmt('emails', render=render_js)
@adapt_page()
def emails(env, page):
    schema = v.parse({
        'person': str,
        'subj': str,
        'in': str
    })
    args = schema.validate(env.request.args)
    label = args.get('in')
    if label:
        subj = label
        l = [label] if label in ['\\Trash', '\\Spam'] else [label, '\\All']
        where = env.mogrify('%s::varchar[] <@ labels', [l])
    elif args.get('subj'):
        subj = 'Filter by subj %r' % args['subj']
        where = env.mogrify('%s = subj', [args['subj']])
    elif args.get('person'):
        subj = 'Filter by person %r' % args['person']
        where = env.mogrify(
            '(fr[1] LIKE %(fr)s OR "to"[1] LIKE %(fr)s)',
            {'fr': '%%<{}>'.format(args['person'])}
        )
    else:
        return env.abort(400)

    if page['last']:
        where = env.mogrify(where + ' AND created < %s', [page['last']])

    i = env.sql('''
    WITH
    thread_ids AS (
        SELECT thrid, max(time)
        FROM emails
        WHERE {where}
        GROUP BY thrid
        ORDER BY 2 DESC
        LIMIT {page[limit]} OFFSET {page[offset]}
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
        id, t.thrid, subj, t.labels, time, fr, text, "to", cc, created,
        attachments, count, subj_list
    FROM emails e
    JOIN threads t ON e.thrid = t.thrid
    WHERE id IN (
        SELECT id FROM emails
        WHERE id = ANY(t.id_list)
        ORDER BY time DESC LIMIT 1
    )
    ORDER BY time DESC
    '''.format(where=where, page=page))

    def emails():
        for msg in i:
            base_subj = dict(msg["subj_list"])
            base_subj = base_subj[sorted(base_subj)[0]]
            msg = dict(msg, **{
                'labels': list(set(sum(msg['labels'], [])) - {label}),
                '_extra': {
                    'count': msg['count'] > 1 and msg['count'],
                    'subj_human': f.humanize_subj(msg['subj'], base_subj)
                }
            })
            yield msg

    sql = 'SELECT count(distinct thrid) FROM emails WHERE %s' % where
    count = env.sql(sql).fetchone()[0]

    ctx = ctx_emails(env, emails(), domid='thrid')
    ctx['count'] = count
    if page['count'] < count:
        ctx['next'] = {'url': env.url(env.request.path, dict(
            env.request.args.to_dict(),
            # last=page['last'] or ctx['emails']['items'][0]['created'],
            page=page['next']
        ))}
    ctx['header'] = ctx_header(env, subj, label and [label])
    return ctx


@login_required
@adapt_fmt('emails')
def search(env):
    schema = v.parse({'+q': str})
    q = schema.validate(env.request.args)['q']
    env.session['search_query'] = q

    if q.startswith('g '):
        q = q[2:]
        ids = syncer.search(env, env.email, q)[:env('ui_per_page')]
    else:
        i = env.sql('''
        SELECT id
        FROM emails_search
        WHERE document @@ (
            plainto_tsquery('simple', %(query)s) ||
            plainto_tsquery('english', %(query)s) ||
            plainto_tsquery('russian', %(query)s)
        )
        ORDER BY ts_rank(document, (
            plainto_tsquery('simple', %(query)s) ||
            plainto_tsquery('english', %(query)s) ||
            plainto_tsquery('russian', %(query)s)
        )) DESC
        LIMIT 100
        ''', {'query': q})
        ids = [r[0] for r in i]

    i = env.sql('''
    SELECT
        id, thrid, subj, labels, time, fr, "to", cc, text, created,
        html, attachments
    FROM emails
    WHERE id = ANY(%(ids)s::uuid[])
    ''', {'ids': ids})

    subj = 'Search by %r' % q
    ctx = ctx_emails(env, i)
    ctx['header'] = ctx_header(env, subj)
    return ctx


@login_required
@adapt_fmt('emails')
def body(env, id):
    def parse(raw, id):
        return parser.parse(env, raw.tobytes(), id)

    row = env.sql('''
    SELECT
        id, thrid, subj, labels, time, fr, "to", cc, text, created,
        raw, attachments
    FROM emails WHERE id=%s LIMIT 1
    ''', [id]).fetchone()
    if not row:
        return env.abort(404)

    i = env.sql('''
    SELECT id, raw, labels FROM emails
    WHERE thrid=%s AND id!=%s AND time<%s
    ORDER BY time DESC
    ''', [row['thrid'], id, row['time']])

    def emails():
        for msg in [row]:
            if not msg['raw']:
                continue

            parsed = parse(msg['raw'], msg['id'])
            msg = dict(msg)
            msg['html'] = (
                parser.text2html(parsed['text'])
                if env.request.args.get('text') else
                parsed['html']
            )
            msg['text'] = parsed['text']
            msg['attachments'] = parsed['attachments']
            msg['embedded'] = parsed['embedded']
            msgs = [parse(p['raw'], p['id'])['html'] for p in i]
            msg['_extra'] = {
                'body': ctx_body(env, msg, msgs, show=True),
                'labels': msg['labels']
            }
            yield msg

    ctx = ctx_emails(env, emails())
    email = ctx['emails']['items'][0]
    ctx['header'] = ctx_header(env, email['subj'], email['labels'])
    return ctx


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
    def name(value):
        if isinstance(value, str):
            value = [value]
        return [v for v in value if v]

    schema = v.parse({
        '+action': v.Enum(('+', '-', '=')),
        '+name': v.AdaptBy(name),
        '+ids': [str],
        'old_name': v.AdaptBy(name),
        'thread': v.Nullable(bool, False),
        'last': v.Nullable(str)
    })
    data = schema.validate(env.request.json)
    if not data['ids']:
        return 'OK'

    ids = tuple(data['ids'])
    if data['thread']:
        i = env.sql('''
        SELECT id FROM emails WHERE thrid IN %s AND created <= %s
        ''', [ids, data['last']])
        ids = tuple(r[0] for r in i)

    mark = ft.partial(syncer.mark, env, ids=ids, new=True)
    if data['action'] == '=':
        if data.get('old_name') is None:
            raise ValueError('Missing parameter "old_name" for %r' % data)
        if data['old_name'] == data['name']:
            return []

        mark('-', set(data['old_name']) - set(data['name']))
        mark('+', set(data['name']) - set(data['old_name']))
        return 'OK'

    mark(data['action'], data['name'])
    return 'OK'


@login_required
def new_thread(env):
    schema = v.parse({'+ids': [str], '+action': v.Enum(('new', 'merge'))})
    params = schema.validate(env.request.json)

    action = params['action']
    if action == 'new':
        id = params['ids'][0]
        syncer.new_thread(env, id)
        return env.to_json({'url': env.url_for('thread', id=id)})
    elif action == 'merge':
        thrid = syncer.merge_threads(env, params['ids'])
        return env.to_json({'url': env.url_for('thread', id=thrid)})


@login_required
def compose(env):
    schema = v.parse({
        'id': str,
        'target': v.Nullable(v.Enum(('all', 'forward')))
    })
    args = schema.validate(env.request.args)
    fr = '"%s" <%s>' % (env.storage.get('gmail_info').get('name'), env.email)
    ctx, parent = {'fr': fr}, {}
    if args.get('id'):
        parent = env.sql('''
        SELECT
            thrid, msgid, "to", fr, cc, bcc, subj, reply_to, refs, html, time
        FROM emails WHERE id=%s LIMIT 1
        ''', [args['id']]).fetchone()
        if f.get_addr(parent['fr'][0]) == env.email:
            to = parent['to']
            fr = parent['fr'][0]
        else:
            to = parent['reply_to'] or parent['fr']
            fr = [a for a in parent['to'] if f.get_addr(a) == env.email]
            fr = fr[0] if fr else env.email

        forward = args.get('target') == 'forward'
        if forward:
            to = []
        elif args.get('target') == 'all':
            to += parent['cc'] or []

        ctx.update({
            'fr': fr,
            'to': ', '.join(to),
            'subj': 'Re: %s' % f.humanize_subj(parent['subj'], empty=''),
            'quote': {'html': ctx_quote(env, parent, forward)},
            'forward': forward
        })

    if env.request.method == 'POST':
        from email.utils import parseaddr
        import dns.resolver
        import dns.exception

        class Email(v.Validator):
            def validate(self, value, adapt=True):
                addr = parseaddr(value)[1]
                hostname = addr[addr.find('@') + 1:]
                try:
                    dns.resolver.query(hostname, 'MX')
                except dns.exception.DNSException:
                    raise v.ValidationError('No MX record for %s' % hostname)
                return value

        schema = v.parse({
            '+to': v.ChainOf(
                v.AdaptBy(lambda v: [i.strip() for i in v.split(',')]),
                [Email]
            ),
            '+fr': Email,
            '+subj': str,
            '+body': str,
            'quote': v.Nullable(str, ''),
            'quoted': v.Nullable(str)
        })
        msg = schema.validate(env.request.form)
        msg['in_reply_to'] = parent.get('msgid')
        msg['refs'] = (parent.get('refs') or [])[-10:]
        msg['files'] = env.request.files.getlist('files')
        sendmail(env, msg)
        if parent.get('thrid'):
            return env.redirect_for('thread', id=parent['thrid'])
        return env.redirect_for('emails', {'in': '\\Sent'})
    return render_body(env, 'compose', ctx, with_sidebar=True)


def markdown(html):
    from mistune import markdown

    return markdown(html, escape=False, hard_wrap=True)


def sendmail(env, msg):
    from email.encoders import encode_base64
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formatdate, formataddr, getaddresses

    html = markdown(msg['body'])
    in_reply_to, files = msg.get('in_reply_to'), msg.get('files', [])
    if msg.get('quoted'):
        html = ('\n\n').join(i for i in (html, msg['quote']) if i)
        text = MIMEMultipart()
        text.attach(MIMEText(html, 'html'))
    else:
        text = MIMEMultipart('alternative')
        text.attach(MIMEText(msg['body'], 'plain'))
        text.attach(MIMEText(html, 'html'))
    email = text

    files = [i for i in files if i.filename]
    if files:
        email = MIMEMultipart()
        email.attach(text)
    for i in files:
        a = MIMEBase(*i.mimetype.split('/'))
        a.set_payload(i.stream.read())
        a.add_header('Content-Disposition', 'attachment', filename=i.filename)
        encode_base64(a)
        email.attach(a)

    email['From'] = msg['fr']
    email['To'] = ', '.join(formataddr(a) for a in getaddresses(msg['to']))
    email['Date'] = formatdate()
    email['Subject'] = msg['subj']

    if in_reply_to:
        email['In-Reply-To'] = in_reply_to
        email['References'] = ' '.join([in_reply_to] + msg.get('refs'))

    env.storage.set('send:%s' % dt.datetime.now(), email.as_string())
    env.db.commit()
    if env('readonly'):
        return

    _, sendmail = gmail.smtp_connect(env, env.email)
    sendmail(msg['fr'], msg['to'], email.as_string())


@login_required
@adapt_fmt('body')
def preview(env):
    schema = v.parse({'+body': str, 'quote': v.Nullable(str)})
    data = schema.validate(env.request.json)
    body = '\n\n'.join([markdown(data['body']), data.get('quote', '')])
    return {'body': body}


@login_required
def search_email(env):
    schema = v.parse({'q': str})
    args = schema.validate(env.request.args)

    where = ''
    if args.get('q'):
        where += env.mogrify('addr LIKE %s', ['%{}%'.format(args['q'])])
    where = ('WHERE ' + where) if where else ''

    addresses = env.mogrify('''
    SELECT distinct unnest("to") AS addr, time
    FROM emails
    WHERE fr[1] LIKE %s
    ''', ['%<{}>'.format(env.email)])

    i = env.sql('''
    WITH addresses AS ({addresses})
    SELECT addr, time FROM addresses
    {where} ORDER BY time DESC LIMIT 100
    '''.format(where=where, addresses=addresses))
    return env.to_json([
        {'text': v[0], 'value': v[0]} for v in i if len(v[0]) < 100
    ])
