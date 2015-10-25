import functools as ft
import re

import valideer as v
from werkzeug.routing import Map, Rule

from . import parser, syncer, gmail, filters as f

rules = [
    Rule('/', endpoint='index', build_only=True),

    Rule('/login/', endpoint='login'),
    Rule('/logout/', endpoint='logout'),
    Rule('/gmail/', endpoint='gmail_connect'),
    Rule('/gmail/callback/', endpoint='gmail_callback'),
    Rule('/info/', endpoint='info'),
    Rule('/init/', endpoint='init'),
    Rule('/pwd/', endpoint='reset_password'),
    Rule('/pwd/<username>/<token>/', endpoint='reset_password'),
    Rule('/labels/', endpoint='labels'),
    Rule('/raw/<id>/', endpoint='raw'),
    Rule('/body/<id>/', endpoint='body'),
    Rule('/thread/<id>/', endpoint='thread'),
    Rule('/emails/', endpoint='emails'),
    Rule('/mark/', endpoint='mark'),
    Rule('/thread/new/', endpoint='new_thread'),
    Rule('/compose/new/', endpoint='compose'),
    Rule('/compose/<id>/', endpoint='compose'),
    Rule('/draft/<thrid>/<action>/', endpoint='draft'),
    Rule('/search-email/', endpoint='search_email')
]
url_map = Map(rules)


def redirect_url(env):
    return '%sapi%s' % (env.request.host_url, env.url_for('gmail_callback'))


def gmail_connect(env):
    return env.redirect(gmail.auth_url(env, redirect_url(env), env.email))


def gmail_callback(env):
    try:
        gmail.auth_callback(env, redirect_url(env), env.request.args['code'])
        return env.redirect_for('index')
    except gmail.AuthError as e:
        return str(e)


def login(env):
    ctx = {}
    if env.request.method == 'POST':
        args = env.request.json
        schema = v.parse({'+username': str, '+password': str})
        try:
            args = schema.validate(args)
        except v.ValidationError:
            pass
        else:
            if env.check_auth(args['username'], args['password']):
                return ctx_init(env)
        ctx.update({
            'username': args['username'],
            'error': 'Wrong username or password'
        })
    return ctx


def logout(env):
    env.session.pop('username', None)
    return 'OK'


def login_required(func):
    def inner(env, *a, **kw):
        if env.valid_username or env.valid_token:
            return func(env, *a, **kw)
        return env.abort(403)
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


def reset_password(env, username=None, token=None):
    def inner(env):
        ctx = {}
        if env.request.method == 'POST':
            schema = v.parse({'+password': str, '+password_confirm': str})
            args = schema.validate(env.request.json)
            if args['password'] == args['password_confirm']:
                env.set_password(args['password'])
                return {'username': env.username}
            ctx['error'] = 'Passwords aren\'t the same'
            return ctx
        return ctx

    if not username and not token:
        if env('readonly'):
            return env.abort(400)
        return login_required(inner)(env)

    env.username = username
    if env.check_password_token(token):
        return inner(env)
    return env.abort(400)


def info(env):
    schema = v.parse({'offset': v.AdaptTo(int)})
    args = schema.validate(env.request.args)
    if args.get('offset'):
        env.session['tz_offset'] = args['offset']

    if env.valid_username or env.valid_token:
        res = ctx_init(env)
    else:
        res = {}
    return res


@login_required
def labels(env):
    i = env.sql('''
    WITH labels(name) AS (SELECT DISTINCT unnest(labels) FROM emails)
    SELECT l.name, count(e.id) AS unread FROM labels l
    LEFT JOIN emails e ON l.name = ANY(labels)
        AND ARRAY['\\Unread', '\\All']::varchar[] <@ labels
    GROUP BY l.name
    ''')
    labels = (
        dict(l, url=url_query(env, 'in', l['name']))
        for l in i if not l['name'].startswith('%s/' % syncer.THRID)
    )
    labels = (
        dict(l, unread=0) if l['name'] in ['\\Pinned', '\\All'] else l
        for l in labels
    )
    labels = sorted(labels, key=lambda v: v['name'].lower())
    return bool(labels) and {'items': labels}


def ctx_init(env):
    last_sync = env.storage.get('last_sync')
    last_sync = last_sync and f.humanize_dt(env, last_sync, secs=True, ts=True)
    return {
        'username': env.username,
        'email': env.email,
        'last_sync': last_sync
    }


def url_query(env, name, value):
    if ' ' in value:
        value = '"%s"' % value.replace('"', '\\"')
    return env.url_for('emails', {'q': ':'.join([name, value])})


def parse_query(env, query, page):
    where, labels = [], []

    def replace(obj):
        for name, value in obj.groupdict().items():
            if not value:
                continue
            if name == 'labels':
                value = value.strip('"')
                value = value.split(',')
                labels.extend(value)
                sql = ''
            elif name == 'subj':
                value = value.strip('"')
                sql = 'subj LIKE %s'
            elif name == 'from':
                value = '%<{}>%'.format(value)
                sql = "array_to_string(fr, ',') LIKE %s"
            elif name == 'to':
                value = '%<{}>%'.format(value)
                sql = "array_to_string(\"to\" || cc, ',') LIKE %s"
            elif name == 'person':
                value = '%<{}>%'.format(value)
                sql = "array_to_string(\"to\" || cc || fr, ',') LIKE %s"

            if sql:
                where.append(env.mogrify(sql, [value]))
        return ''

    pattern = (
        r'('
        r'in:(?P<labels>".*?"|[^ ]*)'
        r'|'
        r'subj:(?P<subj>".*?"|[^ ]*)'
        r'|'
        r'from:(?P<from>[^ ]*)'
        r'|'
        r'to:(?P<to>[^ ]*)'
        r'|'
        r'person:(?P<person>[^ ]*)'
        r')'
    )
    q = re.sub(pattern, replace, query)
    q = re.sub('[ ]+', ' ', q)

    fields = 'id, id AS sort'
    if q.strip():
        tsq = []
        for lang in env('search_lang'):
            tsq.append(env.mogrify(
                'plainto_tsquery(%(lang)s, %(query)s)',
                {'lang': lang, 'query': q}
            ))
        tsq = ' || '.join(tsq)
        where.append('search @@ (%s)' % tsq)
        fields = 'id, ts_rank(search, %s) AS sort' % tsq

    labels = list(
        labels if set(labels) & set(syncer.FOLDERS + ('\\Inbox',))
        else set(labels) | {'\\All'}
    )
    where.append(env.mogrify('labels @> %s::varchar[]', [labels]))

    if page['last']:
        where.append(env.mogrify('created < %s', [page['last']]))

    where = ' AND '.join(where)
    where = ('WHERE %s' % where) if where else ''
    sql = 'SELECT {} FROM emails {}'.format(fields, where)
    return sql, labels


def ctx_emails(env, items, threads=False):
    emails, last = [], None
    for i in items:
        extra = i.get('_extra', {})
        email = dict({
            'id': i['id'],
            'thrid': i['thrid'],
            'subj': i['subj'],
            'subj_human': f.humanize_subj(i['subj']),
            'subj_url': url_query(env, 'subj', i['subj']),
            'preview': f.get_preview(i['text'], i['attachments']),
            'body': False,
            'pinned': '\\Pinned' in i['labels'],
            'unread': '\\Unread' in i['labels'],
            'draft': '\\Draft' in i['labels'],
            'links': ctx_links(env, i['id'], i['thrid'], i['to'] + i['cc']),
            'time': f.format_dt(env, i['time']),
            'time_human': f.humanize_dt(env, i['time']),
            'created': str(i['created']),
            'fr': ctx_person(env, i['fr'][0]),
            'to': [ctx_person(env, v) for v in i['to']],
            'cc': [ctx_person(env, v) for v in i['cc']],
            'to_all': len(i['to'] + i['cc']) > 1,
            'labels': ctx_labels(env, i['labels'])
        }, **extra)
        if threads:
            email['thread_url'] = env.url_for('thread', {'id': i['thrid']})
        else:
            email['body_url'] = env.url_for('body', {'id': i['id']})

        last = i['created'] if not last or i['created'] > last else last
        emails.append(email)

    emails = bool(emails) and {
        'items': emails,
        'length': len(emails),
        'last': str(last)
    }
    return {'emails': emails}


def ctx_links(env, id, thrid=None, to=None):
    reply_url = env.url_for('compose', {'id': id})
    return {
        'replyall': reply_url + '?target=all',
        'reply': reply_url,
        'forward': reply_url + '?target=forward',
        'thread': env.url_for('thread', {'id': thrid}),
        'body': env.url_for('body', {'id': id}),
        'raw': env.url_for('raw', {'id': id})
    }


def ctx_person(env, addr):
    email = f.get_addr(addr)
    return {
        'full': addr,
        'short': f.format_addr(env, addr),
        'url': url_query(env, 'person', email),
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
    return labels


def ctx_all_labels(env):
    i = env.sql('SELECT DISTINCT unnest(labels) FROM emails')
    items = (r[0] for r in i.fetchall())
    items = set(items) | set(syncer.FOLDERS)
    return ctx_labels(env, sorted(items))


def ctx_header(env, title, labels=None):
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
    labels = {
        'items': ctx_labels(env, labels),
        'all': ctx_all_labels(env),
        'base_url': url_query(env, 'in', ''),
    }
    return {
        'title': title,
        'buttons': buttons,
        'labels': labels
    }


def ctx_body(env, msg, msgs, show=False):
    if msgs and isinstance(msgs[0], dict):
        msgs = (m['html'] for m in msgs if m['id'] <= msg['parent'])
    if not show and '\\Unread' not in msg['labels']:
        return False
    attachments = msg.get('attachments')
    attachments = bool(attachments) and {'items': [
        env.files.to_dict(**v) for v in attachments
    ]}
    return {
        'text': f.humanize_html(msg['html'], msgs),
        'attachments': attachments,
        'show': True,
        'details': False
    }


def ctx_quote(env, msg, forward=False):
    return env.render('quote', {
        'subj': msg['subj'],
        'html': msg['html'],
        'fr': ', '.join(msg['fr']),
        'to': ', '.join(msg['to'] + msg['cc']),
        'time': msg['time'],
        'type': 'Forwarded' if forward else 'Original'
    })


@login_required
def thread(env, id):
    i = env.sql('''
    SELECT
        id, thrid, subj, labels, time, fr, "to", text, cc, created,
        html, attachments, parent
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
                'body': ctx_body(env, msg, msgs)
            }
            yield msg
            msgs.insert(0, msg)

    ctx = ctx_emails(env, emails())
    if ctx['emails']:
        emails = ctx['emails']['items']
        subj = f.humanize_subj(emails[0]['subj'])

        last = emails[-1]
        last['body'] = ctx_body(env, msgs[0], msgs[1:], show=True)

        ctx['header'] = ctx_header(env, subj, labels)
        ctx['thread'] = True
        ctx['reply_url'] = env.url_for('compose', {'target': 'all', 'id': id})
    return ctx


@login_required
@adapt_page()
def emails(env, page):
    schema = v.parse({'q': v.Nullable(str, '')})
    q = schema.validate(env.request.args)['q']
    if q.startswith('g! '):
        # Gmail search
        ids = syncer.search(env, env.email, q[3:])
        select = env.mogrify('''
        (SELECT * FROM unnest(%s::bigint[][]) WITH ORDINALITY) AS ids(id, sort)
        ''', [list(reversed(ids))])
        labels = ['\\All']
    else:
        select, labels = parse_query(env, q, page)
        select = '(%s) AS ids' % select

    i = env.sql('''
    SELECT count(distinct thrid) FROM emails e JOIN {} ON e.id = ids.id
    '''.format(select))
    count = i.fetchone()[0]

    i = env.sql('''
    WITH
    thread_ids AS (
        SELECT thrid, max(ids.sort) AS sort
        FROM emails e
        JOIN {select} ON e.id = ids.id
        GROUP BY thrid
        ORDER BY 2 DESC
        LIMIT {page[limit]} OFFSET {page[offset]}
    ),
    threads AS (
        SELECT
            max(t.sort) AS sort,
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
    FROM threads t
    JOIN emails e ON e.thrid = t.thrid
    WHERE id IN (SELECT unnest(t.id_list) ORDER BY 1 DESC LIMIT 1)
    ORDER BY t.sort DESC
    '''.format(select=select, page=page))

    def emails():
        for msg in i:
            base_subj = dict(msg["subj_list"])
            base_subj = base_subj[sorted(base_subj)[0]]
            msg = dict(msg, **{
                'labels': list(
                    set(sum(msg['labels'], [])) -
                    (set(labels) - {'\\Pinned', '\\Unread'})
                ),
                '_extra': {
                    'count': msg['count'] > 1 and msg['count'],
                    'subj_human': f.humanize_subj(msg['subj'], base_subj)
                }
            })
            yield msg

    ctx = ctx_emails(env, emails(), threads=True)
    ctx['count'] = count
    ctx['threads'] = True
    ctx['header'] = ctx_header(env, q, labels)
    ctx['search_query'] = q
    ctx['next'] = page['count'] < count and {'url': env.url(
        env.request.path,
        dict(
            env.request.args.to_dict(),
            # last=page['last'] or ctx['emails']['items'][0]['created'],
            page=page['next']
        )
    )}
    return ctx


@login_required
def body(env, id):
    def parse(raw, id):
        return parser.parse(env, raw.tobytes(), id)

    row = env.sql('''
    SELECT
        id, thrid, subj, labels, time, fr, "to", cc, text, created,
        raw, attachments, parent
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
            msgs = [
                parse(p['raw'], p['id'])['html']
                for p in i if p['id'] <= msg['parent']
            ]
            msg['_extra'] = {
                'body': ctx_body(env, msg, msgs, show=True),
                'labels': ctx_labels(env, msg['labels'])
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
        '+ids': [int],
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
    schema = v.parse({'+ids': [int], '+action': v.Enum(('new', 'merge'))})
    params = schema.validate(env.request.json)

    action = params['action']
    if action == 'new':
        id = params['ids'][0]
        syncer.new_thread(env, id)
        return {'url': env.url_for('thread', {'id': id})}
    elif action == 'merge':
        thrid = syncer.merge_threads(env, params['ids'])
        return {'url': env.url_for('thread', {'id': thrid})}


@login_required
def compose(env, id=None):
    if not env.storage.get('gmail_info'):
        return env.abort(400)

    schema = v.parse({
        'target': v.Nullable(v.Enum(('all', 'forward')))
    })
    args = schema.validate(env.request.args)
    fr = '"%s" <%s>' % (env.storage.get('gmail_info').get('name'), env.email)
    ctx = {
        'fr': fr, 'to': '', 'subj': '', 'body': '', 'files': [],
        'quoted': False, 'forward': False, 'id': id
    }
    parent = {}
    if id:
        parent = env.sql('''
        SELECT
            thrid, "to", fr, cc, bcc, subj, reply_to, html, time,
            attachments, embedded
        FROM emails WHERE id=%s LIMIT 1
        ''', [id]).fetchone()
        if f.get_addr(parent['fr'][0]) == env.email:
            to = parent['to']
            fr = parent['fr'][0]
        else:
            to = parent['reply_to'] or parent['fr']
            to += [a for a in parent['to'] if f.get_addr(a) != env.email]
            fr = [a for a in parent['to'] if f.get_addr(a) == env.email]
            fr = fr[0] if fr else env.email

        forward = args.get('target') == 'forward'
        if forward:
            to = []
        elif args.get('target') == 'all':
            to += parent['cc']

        ctx.update({
            'fr': fr,
            'to': ', '.join(to),
            'subj': 'Re: %s' % f.humanize_subj(parent['subj'], empty=''),
            'quote': ctx_quote(env, parent, forward),
            'quoted': forward,
            'forward': forward,
        })

    thrid = parent.get('thrid')
    saved = env.storage('compose', thrid=thrid)
    saved_path = env.files.subpath('compose', thrid=thrid)
    if saved.get():
        ctx.update(saved.get())
    ctx['draft'] = saved.get() is not None
    ctx['header'] = {'title': ctx.get('subj') or 'New message'}

    if ctx['forward'] and not ctx['draft']:
        env.files.copy(f.slugify(id), saved_path)

        files = list(parent['attachments']) + list(parent['embedded'].values())
        for i in files:
            path = i['path'].replace(id, saved_path)
            asset = env.files.to_dict(**dict(i, path=path))
            ctx['files'].append(asset)
            quote = ctx.get('quote')
            if quote:
                parent_url = re.escape(env.files.url(i['path']))
                ctx['quote'] = re.sub(parent_url, asset['url'], quote)

    ctx['links'] = {
        a: env.url_for('draft', {'thrid': str(thrid) or 'new', 'action': a})
        for a in ('preview', 'rm', 'send', 'upload')
    }
    return ctx


@login_required
def draft(env, thrid, action):
    saved = env.storage('compose', thrid=thrid)
    saved_path = env.files.subpath('compose', thrid=thrid)
    if action == 'preview':
        schema = v.parse({
            '+fr': str,
            '+to': str,
            '+subj': str,
            '+body': str,
            '+quoted': bool,
            '+forward': bool,
            '+id': v.Nullable(str),
            'quote': v.Nullable(str)
        })
        data = schema.validate(env.request.json)
        if env.request.args.get('save', False):
            saved.set(data)
        return get_html(data['body'], data.get('quote', ''))
    elif action == 'upload':
        count = env.request.form.get('count', type=int)
        files = []
        for n, i in enumerate(env.request.files.getlist('files'), count):
            path = '/'.join([saved_path, str(n), f.slugify(i.filename)])
            env.files.write(path, i.stream.read())

            files.append(env.files.to_dict(path, i.mimetype, i.filename))
        return files

    elif action == 'send':
        from email.utils import parseaddr
        import dns.resolver
        import dns.exception

        class Email(v.Validator):
            def validate(self, value, adapt=True):
                if not value:
                    raise v.ValidationError('No email')
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
            'id': str,
            'quote': v.Nullable(str, ''),
        })
        msg = schema.validate(env.request.json)
        if msg.get('id'):
            parent = env.sql('''
            SELECT thrid, msgid, refs
            FROM emails WHERE id=%s LIMIT 1
            ''', [msg['id']]).fetchone()
            msg['in_reply_to'] = parent.get('msgid')
            msg['refs'] = parent.get('refs', [])[-10:]
        else:
            parent = {}

        sendmail(env, msg)
        if saved.get():
            draft(env, thrid, 'rm')
        syncer.sync_gmail(env, env.email, only=['\\All'], fast=1, force=1)

        url = url_query(env, 'in', '\\Sent')
        if parent.get('thrid'):
            url = env.url_for('thread', {'id': parent['thrid']})
        return {'url': url}

    elif action == 'rm':
        if saved.get({}).get('files'):
            env.files.rm(saved_path)
        saved.rm()
        return 'OK'

    env.abort(400)


def get_html(text, quote=''):
    from mistune import markdown

    html = markdown(text, escape=False, hard_wrap=True)
    return ('\n\n').join(i for i in (html, quote) if i)


def sendmail(env, msg):
    import uuid
    from email.encoders import encode_base64
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formatdate, formataddr, getaddresses
    from lxml import html as lh

    def embed_html(htm, files):
        htm = lh.fromstring(htm)
        for img in htm.xpath('//img[@src]'):
            url = img.attrib.get('src')

            src = [i for i in files if i['url'] == url]
            if src:
                src = src[0]
                src['cid'] = uuid.uuid4().hex
                img.attrib['src'] = 'cid:%s' % src['cid']

        htm = lh.tostring(htm, encoding='utf-8').decode()
        return htm, files

    files = msg.get('files', [])
    html = get_html(msg['body'], msg.get('quote'))
    if html:
        html, files = embed_html(html, files)

    if msg.get('quote'):
        text = MIMEMultipart()
        text.attach(MIMEText(html, 'html'))
    else:
        text = MIMEMultipart('alternative')
        text.attach(MIMEText(msg['body'], 'plain'))
        text.attach(MIMEText(html, 'html'))
    email = text

    if files:
        email = MIMEMultipart()
        email.attach(text)

    for i in files:
        a = MIMEBase(*i['type'].split('/'))
        with open(i['path'], 'rb') as fd:
            a.set_payload(fd.read())
        a.add_header('Content-Disposition', 'attachment', filename=i['name'])
        if 'cid' in i:
            a.add_header('Content-ID', '<%s>' % i['cid'])
        encode_base64(a)
        email.attach(a)

    email['From'] = msg['fr']
    email['To'] = ', '.join(formataddr(a) for a in getaddresses(msg['to']))
    email['Date'] = formatdate()
    email['Subject'] = msg['subj']

    in_reply_to = msg.get('in_reply_to')
    if in_reply_to:
        email['In-Reply-To'] = in_reply_to
        email['References'] = ' '.join([in_reply_to] + msg.get('refs'))

    if env('readonly'):
        return env.abort(400, description=(
            'Readonly mode. You can\'t send a message'
        ))

    _, sendmail = gmail.smtp_connect(env, env.email)
    sendmail(msg['fr'], msg['to'], email.as_string())


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
    SELECT addr, max(time) FROM addresses
    {where} GROUP BY addr ORDER BY 2 DESC LIMIT 100
    '''.format(where=where, addresses=addresses))
    return [{'text': v[0], 'value': v[0]} for v in i if len(v[0]) < 100]
