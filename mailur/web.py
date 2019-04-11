import base64
import datetime as dt
import functools as ft
import pathlib
import re
import time
import urllib.parse
import urllib.request
from multiprocessing.pool import ThreadPool

from bottle import Bottle, HTTPError, abort, request, response, template
from itsdangerous import BadData, BadSignature, URLSafeSerializer
from pytz import common_timezones, timezone, utc

from . import conf, html, imap, json, local, lock, log, message, remote, schema

root = pathlib.Path(__file__).parent.parent
assets = (root / 'assets/dist').resolve()
app = Bottle()
app.catchall = not conf['DEBUG']


def session(callback):
    cookie_name = 'session'
    serializer = URLSafeSerializer(conf['SECRET'])

    def inner(*args, **kwargs):
        data_raw = data = request.get_cookie(cookie_name)
        if data_raw:
            try:
                data = serializer.loads(data_raw)
            except (BadSignature, BadData):
                data = None

        if data:
            conf['USER'] = data['username']

        request.session = data or {}

        try:
            return callback(*args, **kwargs)
        finally:
            if request.session:
                save(request.session)
            elif not data_raw:
                pass
            else:
                response.delete_cookie(cookie_name)

    def save(session):
        cookie_opts = {
            # keep session for 3 days
            'max_age': 3600 * 24 * 3,

            # for security
            'httponly': True,
            'secure': request.headers.get('X-Forwarded-Proto') == 'https',
        }
        data = serializer.dumps(session)
        response.set_cookie(cookie_name, data, **cookie_opts)
    return inner


def auth(callback):
    def inner(*args, **kwargs):
        if request.session:
            return callback(*args, **kwargs)
        return abort(403)
    return inner


app.install(session)
app.install(auth)


def jsonify(fn):
    @ft.wraps(fn)
    def inner(*a, **kw):
        response.content_type = 'application/json'
        try:
            data = fn(*a, **kw)
        except HTTPError as e:
            response.status = e.status_code
            data = {'errors': [e.body]}
        except schema.Error as e:
            response.status = 400
            data = {'errors': e.errors, 'schema': e.schema}
        except Exception as e:
            log.exception(e)
            response.status = 500
            data = {'errors': [str(e)]}
        return json.dumps(data or {}, indent=2, ensure_ascii=False)
    return inner


def endpoint(callback):
    @jsonify
    @local.using(local.SYS, name=None, parent=True)
    @ft.wraps(callback)
    def inner(*args, **kwargs):
        try:
            return callback(*args, **kwargs)
        finally:
            imap.clean_pool()
    return inner


@app.get('/', skip=[auth], name='index')
def index():
    theme = request.query.get('theme')
    if not request.session:
        args = {'theme': theme} if theme else {}
        login_url = app.get_url('login', **args)
        return redirect(login_url)

    theme = theme or request.session['theme']
    return render_tpl(theme, 'index', preload_data())


@app.get('/index-data')
@endpoint
def index_data():
    return preload_data()


@app.get('/login', skip=[auth], name='login')
def login_html(theme=None):
    theme = request.query.get('theme') or request.session.get('theme')
    return render_tpl(theme, 'login', {
        'themes': themes(),
        'timezones': list(common_timezones),
    })


@app.post('/login', skip=[auth])
@jsonify
def login():
    data = schema.validate(request.json, {
        'type': 'object',
        'properties': {
            'username': {'type': 'string'},
            'password': {'type': 'string'},
            'timezone': {'type': 'string', 'enum': common_timezones},
            'theme': {'type': 'string', 'default': 'base'}
        },
        'required': ['username', 'password', 'timezone']
    })

    try:
        local.connect(data['username'], data['password'])
    except imap.Error as e:
        response.status = 400
        return {'errors': ['Authentication failed.'], 'details': str(e)}

    del data['password']
    request.session.update(data)
    return {}


@app.get('/logout')
def logout():
    theme = request.session.get('theme')
    args = {'theme': theme} if theme else {}
    login_url = app.get_url('login', **args)
    request.session.clear()
    return redirect(login_url)


@app.get('/nginx', skip=[auth])
def nginx():
    h = request.headers
    try:
        login, pw = h['Auth-User'], h['Auth-Pass']
        protocol = h['Auth-Protocol']
    except KeyError as e:
        return abort(400, repr(e))

    if login in conf['IMAP_OFF']:
        response.set_header('Auth-Status', 'Disabled')
        response.set_header('Auth-Wait', 3)
        return ''

    port = {'imap': '143', 'smtp': '25'}[protocol]

    try:
        local.connect(login, pw)
        response.set_header('Auth-Status', 'OK')
        response.set_header('Auth-Server', '127.0.0.1')
        response.set_header('Auth-Port', port)
    except imap.Error as e:
        response.set_header('Auth-Status', str(e))
        response.set_header('Auth-Wait', 3)
    return ''


@app.post('/tag')
@endpoint
def tag():
    data = schema.validate(request.json, {
        'type': 'object',
        'properties': {
            'name': {
                'type': 'string',
                'pattern': r'^[^\\#]'
            },
        },
        'required': ['name']
    })
    tag = local.get_tag(data['name'])
    return wrap_tags({tag['id']: tag})['info'][tag['id']]


@app.post('/tag/expunge')
@endpoint
def expunge_tag():
    data = schema.validate(request.json, {
        'type': 'object',
        'properties': {
            'name': {
                'type': 'string',
                'enum': ['#trash', '#spam']
            },
        },
        'required': ['name']
    })
    local.msgs_expunge(data['name'])


@app.post('/filters')
@endpoint
def filters():
    def run():
        query, opts = parse_query(data['query'])
        if opts.get('thread') and opts.get('uids'):
            uids = opts['uids']
            oids = uids and local.pair_parsed_uids(uids)
            query = 'uid %s' % imap.pack_uids(oids)
        try:
            local.sieve_run(query, data['body'])
        except imap.Error as e:
            abort(400, e.args[0].decode())
        local.sync_flags_to_all()

    data = schema.validate(request.json, {
        'type': 'object',
        'properties': {
            'action': {'type': 'string', 'enum': ['save', 'run']},
            'name': {'type': 'string', 'enum': ['auto', 'manual']},
            'body': {'type': 'string'},
            'query': {'type': 'string'},
        },
        'required': ['action', 'name', 'body', 'query']
    })
    if data['action'] == 'save':
        run()
        local.data_filters({data['name']: data['body']})
        return local.sieve_scripts()

    body = data['body']
    if not body:
        return

    run()


@app.post('/search')
@endpoint
def search():
    preload = request.json.get('preload')
    q, opts = parse_query(request.json['q'])
    if opts.get('thread'):
        return thread(q, opts, preload)

    if opts.get('threads'):
        uids = local.search_thrs(opts.get('parts', q))
        info = ft.partial(local.thrs_info, tags=opts.get('tags'))
        info_url = app.get_url('thrs_info')
    else:
        uids = local.search_msgs(q)
        info = local.msgs_info
        info_url = app.get_url('msgs_info')

    msgs = {}
    preload = preload or 200
    tags = opts.get('tags', [])
    if preload and uids:
        msgs = wrap_msgs(info(uids[:preload]), tags)

    extra = {
        'threads': opts.get('threads', False),
        'tags': tags
    }
    return dict({
        'uids': uids,
        'msgs': msgs,
        'msgs_info': info_url
    }, **{k: v for k, v in extra.items() if v})


@app.post('/thrs/info', name='thrs_info')
@endpoint
def thrs_info():
    uids = request.json['uids']
    hide_tags = request.json.get('hide_tags', [])
    if not uids:
        return abort(400)
    return wrap_msgs(local.thrs_info(uids, hide_tags), hide_tags)


@app.post('/msgs/info', name='msgs_info')
@endpoint
def msgs_info():
    uids = request.json['uids']
    hide_tags = request.json.get('hide_tags', [])
    if not uids:
        return abort(400)
    return wrap_msgs(local.msgs_info(uids), hide_tags)


@app.post('/msgs/body', name='msgs_body')
@endpoint
def msgs_body():
    uids = request.json['uids']
    read = request.json.get('read', True)
    fix_privacy = request.json.get('fix_privacy', True)
    if not uids:
        return abort(400)
    if read:
        unread = local.search_msgs('uid %s unseen' % ','.join(uids))
        if unread:
            local.msgs_flag(unread, [], ['\\Seen'])
    return dict(local.msgs_body(uids, fix_privacy))


@app.post('/thrs/link')
@endpoint
def thrs_link():
    uids = request.json['uids']
    if not uids:
        return {}
    return {'uids': local.link_threads(uids)}


@app.post('/thrs/unlink')
@endpoint
def thrs_unlink():
    uids = request.json['uids']
    if not uids:
        return {}
    uids = local.unlink_threads(uids)
    return {'query': ':threads uid:%s' % ','.join(uids)}


@app.post('/msgs/flag')
@endpoint
def msgs_flag():
    data = schema.validate(request.json, {
        'type': 'object',
        'properties': {
            'uids': {'type': 'array'},
            'old': {'type': 'array', 'default': []},
            'new': {'type': 'array', 'default': []}
        },
        'required': ['uids']
    })
    local.msgs_flag(**data)


@app.post('/editor')
@endpoint
def editor():
    draft_id = request.forms['draft_id']
    with lock.user_scope('editor:%s' % draft_id, wait=5):
        if request.forms.get('delete'):
            local.data_drafts({draft_id: None})
            uids = local.data_msgids.key(draft_id)
            uid = uids[0] if uids else None
            if uid:
                local.msgs_flag([uid], [], ['#trash'])
            return {}

        files = request.files.getall('files')

        draft, related = compose(draft_id)
        updated = {
            k: v for k, v in draft.items()
            if k in ('draft_id', 'parent', 'forward')
        }
        updated.update({
            k: v.strip() for k, v in request.forms.items()
            if k in ('from', 'to')
        })
        updated.update({
            k: v for k, v in request.forms.items()
            if k in ('subject', 'txt')
        })
        updated['time'] = time.time()
        local.data_drafts({draft_id: updated})
        draft.update(updated)
        if files:
            if not related:
                related = message.new()
                related.make_mixed()
            for f in files:
                maintype, subtype = f.content_type.split('/')
                related.add_attachment(
                    f.file.read(), filename=f.filename,
                    maintype=maintype, subtype=subtype
                )
        uid = draft['uid']
        if not uid or files:
            draft['flags'] = draft.get('flags') or '\\Draft \\Seen'
            msg = message.new_draft(draft, related)
            oid, _ = local.new_msg(msg, draft['flags'], no_parse=True)
            if uid:
                local.del_msg(uid)
            local.parse()
            uid = local.pair_origin_uids([oid])[0]
        else:
            oid = local.pair_parsed_uids([uid])[0]
    return {'uid': uid}


@app.get('/compose')
@app.get('/reply/<uid>', name='reply')
def reply(uid=None):
    forward = uid and request.query.get('forward')
    draft_id = message.gen_draftid()
    local.data_drafts({draft_id: {
        'draft_id': draft_id,
        'parent': uid,
        'forward': forward,
        'time': time.time(),
    }})
    return {
        'draft_id': draft_id,
        'query_edit': 'draft:%s' % draft_id,
        'url_send': app.get_url('send', draft_id=draft_id),
    }


@app.get('/send/<draft_id>', name='send')
@jsonify
def send(draft_id):
    draft, related = compose(draft_id)
    schema.validate(draft, {
        'type': 'object',
        'properties': {
            'from': {'type': 'string', 'format': 'email'},
            'to': {'type': 'string', 'format': 'email'},
        },
        'required': ['from', 'to']
    })

    msgid = message.gen_msgid()
    msg = message.new_draft(draft, related, msgid)
    try:
        remote.send(msg)
    except lock.Error as e:
        log.warn(e)
        time.sleep(5)

    uids = local.search_msgs('HEADER X-Draft-ID %s KEYWORD #sent' % draft_id)
    if uids:
        local.data_drafts({draft_id: None})
        local.del_msg(draft['uid'])
        uid = uids[0]
        return {'query': 'thread:%s' % uid}
    return {'query': ':threads mid:%s' % msgid}


@app.get('/raw/<uid:int>')
@app.get('/raw/<uid:int>/original-msg.eml', name='raw')
def raw(uid):
    box = request.query.get('box', local.SRC)
    uid = str(uid)
    if request.query.get('parsed') or request.query.get('p'):
        box = local.ALL
        uid = local.pair_origin_uids([uid])[0]

    msg = local.raw_msg(uid, box)
    if msg is None:
        return abort(404)
    response.content_type = 'text/plain'
    return msg


@app.get('/raw/<uid:int>/<part>')
@app.get('/raw/<uid:int>/<part>/<filename>')
def raw_part(uid, part, filename=None):
    box = request.query.get('box', local.SRC)
    uid = str(uid)
    msg, content_type = local.raw_part(uid, box, part)
    if msg is None:
        return abort(404)
    response.content_type = content_type
    return msg


@app.post('/markdown')
def markdown():
    txt = request.json.get('txt')
    return html.markdown(txt)


@app.get('/avatars.css')
def avatars():
    hashes = set(request.query['hashes'].split(','))
    size = request.query.get('size', 20)
    default = request.query.get('default', 'identicon')
    cls = request.query.get('cls', '.pic-%s')

    response.content_type = 'text/css'
    return '\n'.join((
        '%s {background-image: url(data:image/gif;base64,%s);}'
        % ((cls % h), i.decode())
    ) for h, i in fetch_avatars(hashes, size, default))


@app.get('/refresh/metadata')
def refresh_metadata():
    local.update_metadata('1:*')
    return 'Done.'


@app.get('/proxy')
def proxy():
    url = request.query.get('url')
    if not url:
        return abort(400)

    # further serve by nginx
    url = '/.proxy?url=%s' % url
    response.set_header('X-Accel-Redirect', url)
    return ''


@app.get('/assets/<path:path>', skip=[auth])
def serve_assets(path):
    """"Real serving is done by nginx, this is just stub"""
    from bottle import static_file
    return static_file(path, root=assets)


# Helpers bellow
tpl = '''
<!DOCTYPE html>
<html>
<head>
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1.0, maximum-scale=1.0"
  />
  <meta charset="utf-8" />
  <title>Mailur: {{title}}</title>
  <link rel="shortcut icon" href="/assets/favicon.png" />
  <link href="/assets/{{css}}?{{mtime}}" rel="stylesheet" />
  <script>
    window.data={{!data}};
  </script>
</head>
<body>
  <div id="app"/>
  <script type="text/javascript" src="/assets/vendor.js?{{mtime}}"></script>
  <script type="text/javascript" src="/assets/{{js}}?{{mtime}}"></script>
</body>
</html>
'''

quote_tpl = '''

```
---------- {{type}} message ----------
Subject: {{msg['subject']}}
Date: {{msg['date']}}
From: {{!msg['from']}}
To: {{!msg['to']}}
% if msg['cc']:
CC: {{!msg['cc']}}
% end
```
'''


@ft.lru_cache(maxsize=None)
def themes():
    pkg = json.loads((root / 'package.json').read_text())
    return sorted(pkg['mailur']['themes'])


def render_tpl(theme, page, data={}):
    theme = theme if theme in themes() else 'base'
    data.update(current_theme=theme)
    title = {'index': 'welcome', 'login': 'login'}[page]
    css = assets / ('theme-%s.css' % theme)
    js = assets / ('%s.js' % page)
    mtime = max(i.stat().st_mtime for i in [css, js])
    params = {
        'data': json.dumps(data, sort_keys=True),
        'css': css.name,
        'js': js.name,
        'mtime': mtime,
        'title': title,
    }
    return template(tpl, **params)


def preload_data():
    addrs_from, addrs_to = local.data_addresses.get()
    sort = ft.partial(sorted, key=lambda a: a['time'], reverse=True)
    addrs_from = sort(addrs_from.values())
    addrs_to = sort(addrs_to.values())
    return {
        'user': request.session['username'],
        'tags': wrap_tags(local.tags_info()),
        'addrs_from': [a['title'] for a in addrs_from],
        'addrs_to': [a['title'] for a in addrs_to],
        'filters': local.sieve_scripts(),
    }


def redirect(url, code=None):
    if not code:
        code = 303 if request.get('SERVER_PROTOCOL') == 'HTTP/1.1' else 302
    response.status = code
    response.body = ''
    response.set_header('Location', urllib.parse.urljoin(request.url, url))
    return response


def parse_query(q):
    def escape(val):
        return json.dumps(val, ensure_ascii=False)

    def replace(match):
        info = match.groupdict()
        q = match.group()
        flags = {'flagged', 'unflagged', 'seen', 'unseen', 'draft'}
        flags = {k for k in flags if info.get(k)}
        if flags:
            opts.setdefault('flags', [])
            opts['flags'].extend(flags)
            q = ''
        elif info.get('shortcut'):
            opts.setdefault('tags', [])
            opts['tags'].append('#%s' % info['shortcut_tag'])
            q = ''
        elif info.get('tag'):
            opts.setdefault('tags', [])
            opts['tags'].append(info['tag_id'])
            q = ''
        elif info.get('raw'):
            q = info['raw_val']
        elif info.get('thread'):
            opts['thread'] = True
            opts['uid'] = info['thread_id']
            q = ''
        elif info.get('uid'):
            q = 'uid %s' % info['uid_val']
        elif info.get('from'):
            q = 'from %s' % escape(info['from_val'])
        elif info.get('to'):
            q = 'to %s' % escape(info['to_val'])
        elif info.get('mid'):
            val = info['mid_val']
            uids = local.data_msgids.key(val)
            if uids:
                opts['thread'] = True
                opts['uids'] = uids
                q = 'uid %s' % ','.join(uids)
            else:
                q = 'header message-id %s' % val
        elif info.get('ref'):
            opts['thread'] = True
            q = (
                'or header message-id {0} header references {0}'
                .format(info['ref_val'])
            )
        elif info.get('subj'):
            val = info['subj_val'].strip('"')
            q = 'header subject %s' % escape(val)
        elif info.get('threads'):
            opts['threads'] = True
            q = ''
        elif info.get('draft_edit'):
            mid = info['draft_val']
            opts['thread'] = True
            opts['draft'] = mid
            uids = local.data_msgids.key(mid)
            draft = local.data_drafts.key(mid, {})
            if uids:
                opts['uid'] = uids[0]
                q = ''
            elif draft.get('parent'):
                opts['uid'] = draft['parent']
                q = ''
            else:
                q = 'header message-id %s' % mid
        elif info.get('date'):
            val = info['date_val']
            count = val.count('-')
            if not count:
                date = dt.datetime.strptime(val, '%Y')
                dates = [date, date.replace(year=date.year+1)]
            elif count == 1:
                date = dt.datetime.strptime(val, '%Y-%m')
                dates = [date, date.replace(month=date.month+1)]
            else:
                date = dt.datetime.strptime(val, '%Y-%m-%d')
                dates = [date]

            dates = tuple(i.strftime('%d-%b-%Y') for i in dates)
            if len(dates) == 1:
                q = 'on %s' % dates
            else:
                q = 'since %s before %s' % dates
        if q:
            parts.append(q)
        return ' '

    opts = {}
    parts = []
    q = re.sub(
        r'(?i)[ ]?('
        r'(?P<raw>:raw)(?P<raw_val>.*)'
        r'|(?P<thread>thr(ead)?:)(?P<thread_id>\d+)'
        r'|(?P<threads>:threads)'
        r'|(?P<tag>(tag|in|has):)(?P<tag_id>[^ ]+)'
        r'|(?P<subj>subj(ect)?:)(?P<subj_val>("[^"]*"|[\S]*))'
        r'|(?P<from>from:)(?P<from_val>[^ ]+)'
        r'|(?P<to>to:)(?P<to_val>[^ ]+)'
        r'|(?P<mid>(message_id|mid):)(?P<mid_val>[^ ]+)'
        r'|(?P<ref>ref:)(?P<ref_val>[^ ]+)'
        r'|(?P<uid>uid:)(?P<uid_val>[\d,-]+)'
        r'|(?P<date>date:)(?P<date_val>\d{4}(-\d{2}(-\d{2})?)?)'
        r'|(?P<shortcut>:(?P<shortcut_tag>inbox|sent|trash|spam))'
        r'|(?P<draft>:(draft))'
        r'|(?P<unseen>:(unread|unseen))'
        r'|(?P<seen>:(read|seen))'
        r'|(?P<flagged>:(pin(ned)?|flagged))'
        r'|(?P<unflagged>:(unpin(ned)?|unflagged))'
        r'|(?P<draft_edit>draft:(?P<draft_val>\<[^>]+\>))'
        r')( |$)',
        replace, q
    )
    q = re.sub('[ ]+', ' ', q).strip()
    if q:
        q = 'text %s' % json.dumps(q, ensure_ascii=False)
        parts.append(q)

    uid = opts.get('uid')
    if uid:
        thrids, thrs = local.data_threads.get()
        thrid = thrids.get(uid)
        if thrid:
            uids = thrs[thrids[thrid]]
            opts['uids'] = uids
            q = 'uid %s' % ','.join(uids)
        else:
            q = 'uid %s' % uid
        parts.insert(0, q)

    flags = opts.get('flags', [])
    if flags:
        parts.extend(flags)

    tags = opts.get('tags', [])
    if tags:
        parts.extend('keyword %s' % t for t in tags)

    if not parts:
        parts.append('')

    if '#trash' not in tags:
        parts[-1] = ' '.join([parts[-1], 'unkeyword #trash'])
    if '#spam' not in tags and '#trash' not in tags:
        parts[-1] = ' '.join([parts[-1], 'unkeyword #spam'])

    if len(parts) > 1 and opts.get('threads'):
        opts['parts'] = parts
    q = ' '.join(parts).strip() or 'all'
    return q, opts


def compose(draft_id):
    draft = local.data_drafts.key(draft_id, {}).copy()
    draft.update({
        'query_thread': (
            'thread:%(parent)s' % draft
            if draft.get('parent') else
            'mid:%s' % draft_id
        ),
        'url_send': app.get_url('send', draft_id=draft_id),
    })

    uids = local.data_msgids.key(draft_id)
    uid = uids[0] if uids else None

    addrs, _ = local.data_addresses.get()
    addr = {}
    if addrs:
        addr = sorted(addrs.values(), key=lambda i: i['time'])[-1]
    defaults = {
        'draft_id': draft_id,
        'uid': uid,
        'from': addr.get('title', ''),
        'to': '',
        'subject': '',
        'txt': '',
        'files': [],
    }
    parent = draft.get('parent')
    forward = parent and draft.get('forward')
    if parent:
        flags, head, meta, htm = local.fetch_msg(parent)
        subj = meta['subject']
        subj = re.sub(r'(?i)^(re|fwd)(\[\d+\])?: ?', '', subj)
        prefix = 'Fwd:' if forward else 'Re:'
        subj = ' '.join(i for i in (prefix, subj) if i)
        to = [head['reply-to'] or head['from'], head['to'], head['cc']]
        to_all = message.addresses(','.join(a for a in to if a))
        for a in to_all:
            if a['addr'] in addrs:
                addr = a
                to_all.remove(a)
        to = [a['title'] for a in to_all]
        if not to:
            to = [to_all[0]['title']]
        msgs = local.data_msgs.get()
        refs = [i for i in [msgs[parent].get('parent'), meta['msgid']] if i]
        defaults.update({
            'subject': subj,
            'to': '' if forward else ', '.join(to),
            'in-reply-to': meta['msgid'],
            'references': ' '.join(refs),
        })
    inner = None
    if forward:
        inner = local.raw_msg(meta['origin_uid'], local.SRC, parsed=True)
        for name, val in inner.items():
            if not name.lower().startswith('content-'):
                del inner[name]
        defaults['txt'] = template(quote_tpl, type='Forwarded', msg=head)
        defaults['quoted'] = local.fetch_msg(parent)[-1]
        defaults['files'] = meta['files']

    if uid:
        flags, head, meta, txt = local.fetch_msg(uid, draft=True)
        defaults.update({
            i: head.get(i, '') for i in (
                'from', 'to', 'cc', 'subject', 'in-reply-to', 'references'
            )
        })
        defaults.update({
            'time': meta['arrived'],
            'files': meta['files'],
            'txt': txt,
            'flags': flags,
        })
        if meta['files']:
            orig = local.raw_msg(meta['origin_uid'], local.SRC, parsed=True)
            _, parts = message.parse_draft(orig)
            if parts:
                inner = message.new()
                inner.make_mixed()
                for p in parts:
                    inner.attach(p)
    return dict(defaults, **draft), inner


def thread(q, opts, preload=None):
    preload = preload or 7
    uids = local.search_msgs(q, '(ARRIVAL)')
    edit = None
    draft_id = opts.get('draft')
    if draft_id:
        edit, _ = compose(draft_id)
    if not uids:
        return {
            'edit': edit,
            'uids': [],
            'msgs': {},
            'msgs_info': app.get_url('msgs_info'),
            'thread': True,
            'tags': [],
            'same_subject': []
        }

    tags = opts.get('tags', [])
    msgs = wrap_msgs(local.msgs_info(uids), tags)

    tags = set(tags)
    for m in msgs.values():
        tags.update(m.pop('tags'))
        m['tags'] = []
    tags = clean_tags(tags)

    same_subject = []
    for num, uid in enumerate(uids[1:], 1):
        prev = uids[num-1]
        subj = msgs[uid]['subject']
        prev_subj = msgs[prev]['subject']
        if subj == prev_subj:
            same_subject.append(uid)

    has_link = False
    parents = []
    mids = local.data_msgids.get()
    for i, m in msgs.items():
        if m['is_link']:
            has_link = True

        if not m['is_draft']:
            continue

        parent = m['parent']
        parent = parent and mids.get(parent, [None])[0]
        if not parent or parent not in uids:
            continue
        uids.remove(m['uid'])
        uids.insert(uids.index(parent) + 1, m['uid'])
        parents.append(parent)

    if preload is not None and len(uids) > preload * 2:
        msgs_few = {
            i: m for i, m in msgs.items()
            if any((
                m['is_unread'],
                m['is_pinned'],
                m['is_draft'],
                m['uid'] in parents
            ))
        }
        uids_few = [uids[0]] + uids[-preload+1:]
        for i in uids_few:
            if i in msgs_few:
                continue
            msgs_few[i] = msgs[i]
        msgs = msgs_few

    return {
        'uids': uids,
        'msgs': msgs,
        'msgs_info': app.get_url('msgs_info'),
        'thread': True,
        'tags': tags,
        'same_subject': same_subject,
        'edit': edit,
        'has_link': has_link,
    }


def wrap_tags(tags, whitelist=None):
    def trancate(val, max=14, end='…'):
        return val[:max] + end if len(val) > max else val

    def sort(key):
        tag = tags[key]
        weight = 10 - (
            int(key not in ('#spam', '#trash')) and
            (tag.get('pinned', 0) or int(tag.get('unread', 0) > 0))
        )
        return weight, tags[key]['name']

    ids = sorted(tags, key=sort)
    ids_edit = sorted(clean_tags(ids), key=lambda t: tags[t]['name'])
    info = {
        t: dict(tags[t], short_name=trancate(tags[t]['name']))
        for t in ids
    }
    return {'ids': ids, 'ids_edit': ids_edit, 'info': info}


def clean_tags(tags, whitelist=None, blacklist=None):
    whitelist = whitelist or []
    blacklist = '|'.join(re.escape(i) for i in blacklist) if blacklist else ''
    blacklist = blacklist and '|%s' % blacklist
    ignore = re.compile(r'(^\\|#unread|#all|#sent|#err%s)' % blacklist)
    return sorted(i for i in tags if i in whitelist or not ignore.match(i))


def wrap_msgs(items, hide_tags=None):
    def query_header(name, value):
        value = json.dumps(value, ensure_ascii=False)
        return ':threads %s:%s' % (name, value)

    base_q = ''
    if not hide_tags:
        pass
    elif '#trash' in hide_tags:
        base_q = 'tag:#trash '
    elif '#spam' in hide_tags:
        base_q = 'tag:#spam '

    mids = local.data_msgids.get()
    linked_uids = (
        sum((mids.get(mid, []) for mid in link), [])
        for link in local.data_links.get()
    )
    linked_uids = sum(linked_uids, [])

    tz = request.session['timezone']
    msgs = {}
    for uid, txt, flags, addrs in items:
        if isinstance(txt, bytes):
            txt = txt.decode()
        if isinstance(txt, str):
            info = json.loads(txt)
        else:
            info = txt

        info.update({
            'is_unread': '\\Seen' not in flags,
            'is_pinned': '\\Flagged' in flags,
            'is_draft': '\\Draft' in flags,
            'is_link': uid in linked_uids,
        })

        if info['is_draft']:
            info['query_edit'] = base_q + 'draft:%s' % info['draft_id']
            draft = local.data_drafts.key(info['draft_id'], {})
            if draft.get('from'):
                info['from'] = message.addresses(draft['from'])[0]
            if draft.get('to'):
                info['to'] = message.addresses(draft['to'])
            subj = draft.get('subject')
            if subj:
                info['subject'] = subj
            txt = draft.get('txt')
            if txt:
                htm = html.markdown(txt)
                info['preview'] = message.preview(htm, info['files'])
        else:
            info['url_reply'] = app.get_url('reply', uid=uid)

        if addrs is None:
            addrs = [info['from']] if 'from' in info else []
        if info.get('from'):
            info['from'] = wrap_addresses([info['from']], base_q=base_q)[0]
        if info.get('to'):
            info['to'] = wrap_addresses(info['to'], field='to', base_q=base_q)

        info.update({
            'uid': uid,
            'count': len(addrs),
            'tags': clean_tags(flags, blacklist=hide_tags),
            'from_list': wrap_addresses(addrs, max=3, base_q=base_q),
            'query_thread': base_q + 'thread:%s' % uid,
            'query_subject': base_q + query_header('subj', info['subject']),
            'query_msgid': base_q + 'ref:%s' % info['msgid'],
            'url_raw': app.get_url('raw', uid=info['origin_uid']),
            'time_human': humanize_dt(info['arrived'], tz=tz),
            'time_title': format_dt(info['arrived'], tz=tz),
        })
        styles, ext_images = info.get('styles'), info.get('ext_images')
        if styles or ext_images:
            richer = ['styles'] if styles else []
            if ext_images:
                richer.append('%s external images' % ext_images)
            richer = ('Show %s' % ' and '.join(richer)) if richer else ''
            info['richer'] = richer
        msgs[uid] = info
    return msgs


def wrap_addresses(addrs, field='from', max=None, base_q=''):
    if isinstance(addrs, str):
        addrs = [addrs]

    addrs_uniq = []
    addrs_list = []
    for a in reversed(addrs):
        if not a or a['addr'] in addrs_uniq:
            continue
        addrs_uniq.append(a['addr'])
        query = base_q + ':threads %s:%s' % (field, a['addr'])
        addrs_list.append(dict(a, query=query))

    addrs_list = list(reversed(addrs_list))
    if not max or len(addrs_list) <= max:
        return addrs_list

    addr_end = addrs[-1]
    if addr_end and addr_end['addr'] != addrs_list[-1]['addr']:
        addrs_list.pop(addrs_list.index(addr_end))
        addrs_list.append(addr_end)

    if addr_end['addr'] == addrs[0]['addr']:
        expander_index = 0
        addrs_few = addrs_list[-max+1:]
    else:
        expander_index = 1
        addrs_few = [addrs_list[0]] + addrs_list[-max+2:]

    addrs_few.insert(
        expander_index,
        {'expander': len(addrs_list) - len(addrs_few)}
    )
    return addrs_few


def localize_dt(val, tz=utc):
    if isinstance(val, (float, int)):
        val = dt.datetime.fromtimestamp(val)
    if not val.tzinfo:
        val = utc.localize(val)
    if isinstance(tz, str):
        tz = timezone(tz)
    if tz != utc:
        val = val.astimezone(tz)
    return val


def format_dt(value, tz=utc, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(value, tz).strftime(fmt)


def humanize_dt(val, tz=utc, secs=False):
    val = localize_dt(val, tz)
    now = localize_dt(dt.datetime.utcnow(), tz)
    if (now - val).total_seconds() < 12 * 60 * 60:
        fmt = '%H:%M' + (':%S' if secs else '')
    elif now.year == val.year:
        fmt = '%b %d'
    else:
        fmt = '%b %d, %Y'
    return val.strftime(fmt)


def fetch_avatars(hashes, size=20, default='identicon', b64=True):
    def _avatar(hash):
        if hash in cache:
            return cache[hash]
        res = urllib.request.urlopen(
            'https://www.gravatar.com/avatar/{hash}?d={default}&s={size}'
            .format(hash=hash, size=size, default=default)
        )
        result = hash, res.read() if res.status == 200 else None
        cache[hash] = result
        return result

    if not hasattr(fetch_avatars, 'cache'):
        fetch_avatars.cache = {}
    key = (size, default)
    fetch_avatars.cache.setdefault(key, {})
    cache = fetch_avatars.cache[key]

    pool = ThreadPool(20)
    res = pool.map(_avatar, hashes)
    return [(i[0], base64.b64encode(i[1]) if b64 else i[1]) for i in res if i]
