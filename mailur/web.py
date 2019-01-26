import base64
import datetime as dt
import functools as ft
import pathlib
import re
import smtplib
import time
import urllib.parse
import urllib.request
from multiprocessing.pool import ThreadPool

from itsdangerous import BadData, BadSignature, URLSafeSerializer
from pytz import common_timezones, timezone, utc

from bottle import Bottle, abort, request, response, static_file, template

from . import LockError, conf, html, imap, json, local, log, message
from .schema import validate

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
        data = fn(*a, **kw)
        return json.dumps(data or {}, indent=2, ensure_ascii=False)
    return inner


def endpoint(callback):
    @jsonify
    @ft.wraps(callback)
    def inner(*args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except Exception as e:
            log.exception(e)
            response.status = 500
            return {'errors': [repr(e)]}
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
    return render_tpl(theme, 'index', {
        'user': request.session['username'],
        'tags': wrap_tags(local.tags_info())
    })


@app.get('/login', skip=[auth], name='login')
def login_html(theme=None):
    theme = request.query.get('theme') or request.session.get('theme')
    return render_tpl(theme, 'login', {
        'themes': themes(),
        'timezones': common_timezones,
    })


@app.post('/login', skip=[auth])
@endpoint
def login():
    schema = {
        'type': 'object',
        'properties': {
            'username': {'type': 'string'},
            'password': {'type': 'string'},
            'timezone': {'type': 'string', 'enum': common_timezones},
            'theme': {'type': 'string', 'default': 'base'}
        },
        'required': ['username', 'password', 'timezone']
    }
    errs, data = validate(request.json, schema)
    if errs:
        response.status = 400
        return {'errors': errs, 'schema': schema}

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


@app.get('/tags')
@endpoint
def tags():
    return wrap_tags(local.tags_info())


@app.post('/tag')
@endpoint
def tag():
    schema = {
        'type': 'object',
        'properties': {
            'name': {
                'type': 'string',
                'pattern': r'^[^\\#]'
            },
        },
        'required': ['name']
    }
    errs, data = validate(request.json, schema)
    if errs:
        response.status = 400
        return {'errors': errs, 'schema': schema}
    tag = local.get_tag(data['name'])
    return wrap_tags({tag['id']: tag})['info'][tag['id']]


@app.post('/search')
@endpoint
def search():
    preload = request.json.get('preload')
    q, opts = parse_query(request.json['q'])
    if opts.get('thread'):
        return thread(q, opts, preload or 4)

    if opts.get('threads'):
        uids = local.search_thrs(q)
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
    schema = {
        'type': 'object',
        'properties': {
            'uids': {'type': 'array'},
            'old': {'type': 'array', 'default': []},
            'new': {'type': 'array', 'default': []}
        },
        'required': ['uids']
    }
    errs, data = validate(request.json, schema)
    if errs:
        response.status = 400
        return {'errors': errs, 'schema': schema}
    local.msgs_flag(**data)


@app.post('/editor')
@endpoint
def editor():
    uid = request.forms['uid']
    files = request.files.getall('files')

    draft, related = draft_info(uid)
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
    msg = message.new_draft(draft, request.forms, related)
    oid, _ = local.new_msg(msg, draft['flags'], no_parse=True)
    local.del_msg(draft['uid'])
    local.parse()
    pid = local.pair_origin_uids([oid])[0]
    return {'uid': pid, 'url_send': app.get_url('send', uid=oid)}


@app.get('/compose')
@app.get('/reply/<uid>', name='reply')
def reply(uid=None):
    forward = uid and request.query.get('forward')
    draft_id = message.gen_draftid()
    addrs, _ = local.data_addresses.get()
    addr = {}
    if addrs:
        addr = sorted(addrs.values(), key=lambda i: i['time'])[-1]
    draft = {
        'draft_id': draft_id,
        'subject': '',
        'to': '',
        'from': addr.get('title', ''),
    }
    if uid:
        flags, head, meta, htm = local.fetch_msg(uid)
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
        draft.update({
            'subject': subj,
            'to': ','.join(to),
            'in-reply-to': meta['msgid'],
            'references': meta['msgid'],
        })
    inner = None
    if forward:
        inner = local.raw_msg(meta['origin_uid'], local.SRC, parsed=True)
        for name, val in inner.items():
            if not name.lower().startswith('content-'):
                del inner[name]
        draft['txt'] = template(quote_tpl, type='Forwarded', msg=head)
    msg = message.new_draft(draft, {}, inner)
    _, new_uid = local.new_msg(msg, '\\Draft \\Seen')
    return {'uid': new_uid, 'query_edit': 'draft:%s' % draft_id}


@app.get('/send/<uid:int>', name='send')
@jsonify
def send(uid):
    from . import gmail

    # TODO: send emails over gmail for now
    uid = str(uid)
    raw = local.raw_msg(uid, local.SRC)
    try:
        params, msgid = message.sending(raw)
    except ValueError as e:
        response.status = 400
        return {'errors': [str(e)]}

    login, pwd = gmail.data_credentials.get()
    con = smtplib.SMTP('smtp.gmail.com', 587)
    con.ehlo()
    con.starttls()
    con.login(login, pwd)
    con.sendmail(*params)
    try:
        gmail.fetch_folder()
        local.parse()
    except LockError as e:
        log.warn(e)
        time.sleep(5)

    uids = local.search_msgs('HEADER Message-ID %s KEYWORD #sent' % msgid)
    if uids:
        local.del_msg(uid)
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
    """Real proxing is done by nginx, this is just stub"""
    url = request.query.get('url')
    if not url:
        return abort(400)

    return redirect(url)


@app.get('/assets/<path:path>', skip=[auth])
def serve_assets(path):
    """"Real serving is done by nginx, this is just stub"""
    return static_file(path, root=assets)


# Helpers bellow
tpl = '''
<!DOCTYPE html>
<html>
<head>
  <meta
    name="viewport"
    content="width=device-width; initial-scale=1.0; maximum-scale=1.0;"
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
            q = 'header message-id %s' % info['mid_val']
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
            opts['thread'] = True
            mid = info['draft_val']
            opts['draft'] = mid
            mids = local.data_msgids.get()
            uid = mids.get(mid)
            if uid:
                opts['uid'] = uid[0]
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

    flags = opts.get('flags', [])
    if flags:
        parts.append(' '.join(flags))

    tags = opts.get('tags', [])
    if tags:
        parts.append(' '.join('keyword %s' % t for t in tags))
    if '#trash' not in tags:
        parts.append('unkeyword #trash')
    if '#spam' not in tags and '#trash' not in tags:
        parts.append('unkeyword #spam')

    uid = opts.get('uid')
    if uid:
        thrids, thrs = local.data_threads.get()
        thrid = thrids.get(uid)
        if thrid:
            uids = thrs[thrids[thrid]]
            q = 'uid %s' % ','.join(uids)
        else:
            q = 'uid %s' % uid
        parts.insert(0, q)

    if parts:
        q = ' '.join(parts)
    q = q.strip()
    q = q if q else 'all'
    return q, opts


def thread(q, opts, preload=4):
    uids = local.search_msgs(q, '(ARRIVAL)')
    if not uids:
        return {
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

    edit = None
    has_link = False
    parents = []
    mids = local.data_msgids.get()
    for i, m in msgs.items():
        if m['is_link']:
            has_link = True
            uids.remove(m['uid'])

        if not m['is_draft']:
            continue
        if m['draft_id'] == opts.get('draft'):
            edit = draft_info(m['uid'])[0]

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
    def query(tag):
        if tag.startswith('\\'):
            q = {'\\Draft': ':draft', '\\Flagged': ':pinned'}.get(tag)
            if not q:
                q = ':raw %s' % tag[1:]
        else:
            q = 'tag:%s' % tag.lower()
        return ':threads %s' % q

    def trancate(val, max=14, end='…'):
        return val[:max] + end if len(val) > max else val

    def sort(key):
        tag = tags[key]
        first = (
            key not in ('#spam', '#trash') and
            (tag.get('unread', 0) or tag.get('pinned', 0))
        )
        return 0 if first else 1, tags[key]['name']

    ids = sorted(clean_tags(tags, whitelist), key=sort)
    info = {
        t: dict(tags[t], query=query(t), short_name=trancate(tags[t]['name']))
        for t in ids
    }
    return {'ids': ids, 'info': info}


def clean_tags(tags, whitelist=None, blacklist=None):
    whitelist = whitelist or []
    blacklist = '|'.join(re.escape(i) for i in blacklist) if blacklist else ''
    blacklist = blacklist and '|%s' % blacklist
    ignore = re.compile(r'(^\\|#sent|#latest|#link|#dup|#err%s)' % blacklist)
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

    tz = request.session['timezone']
    msgs = {}
    for uid, txt, flags, addrs in items:
        if isinstance(txt, bytes):
            txt = txt.decode()
        if isinstance(txt, str):
            info = json.loads(txt)
        else:
            info = txt

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
            'is_unread': '\\Seen' not in flags,
            'is_pinned': '\\Flagged' in flags,
            'is_draft': '\\Draft' in flags,
            'is_link': '#link' in flags,
        })
        if info['is_draft']:
            info['query_edit'] = base_q + 'draft:%s' % info['draft_id']
        else:
            info['url_reply'] = app.get_url('reply', uid=uid)

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


def draft_info(uid):
    flags, headers, meta, txt = local.fetch_msg(uid, draft=True)
    orig = local.raw_msg(meta['origin_uid'], local.SRC, parsed=True)
    related = quoted = None
    _, parts = message.parse_draft(orig)
    if parts:
        related = message.new()
        related.make_mixed()
        for p in parts:
            related.attach(p)
        htm_, txt_ = message.parse_mime(related, uid)[:2]
        quoted = html.clean(htm_)[0] if htm_ else html.from_text(txt_)

    info = {
        i: headers.get(i, '')
        for i in ('from', 'to', 'cc', 'subject', 'in-reply-to', 'references')
    }
    info.update({
        'uid': uid,
        'txt': txt,
        'quoted': quoted,
        'flags': flags,
        'draft_id': meta['draft_id'],
        'origin_uid': meta['origin_uid'],
        'files': meta['files'],
        'url_send': app.get_url('send', uid=meta['origin_uid']),
        'time': meta['date'],
    })
    return info, related
