import base64
import datetime as dt
import functools as ft
import json
import os
import pathlib
import re

from bottle import (
    Bottle, abort, redirect, request, response, static_file, template
)

from gevent.pool import Pool

from geventhttpclient import HTTPClient

from pytz import common_timezones, timezone, utc

from . import imap, local
from .schema import validate

secret = os.environ.get('MLR_SECRET', 'secret')
root = pathlib.Path(__file__).parent.parent
assets = (root / 'assets/dist').resolve()
app = Bottle()


def session(callback):
    def inner(*args, **kwargs):
        session = request.get_cookie('session', secret=secret)
        if session:
            local.USER = session['username']
        request.session = session
        return callback(*args, **kwargs)
    return inner


def auth(callback):
    def inner(*args, **kwargs):
        if request.session:
            return callback(*args, **kwargs)
        return abort(403)
    return inner


def theme_filter(config):
    regexp = r'(%s)?' % '|'.join(re.escape(t) for t in themes())

    def to_python(t):
        return t

    def to_url(t):
        return t
    return regexp, to_python, to_url


app.install(session)
app.install(auth)
app.router.add_filter('theme', theme_filter)


@app.get('/', skip=[auth], name='index')
@app.get('/<theme>/', skip=[auth])
def index(theme=None):
    if not request.session:
        prefix = ('/' + theme) if theme else ''
        login_url = '%s%s' % (prefix, app.get_url('login'))
        return redirect(login_url)

    return render_tpl(theme or request.session['theme'], 'index', {
        'tags': wrap_tags(local.tags_info())
    })


@app.get('/login', skip=[auth], name='login')
@app.get('/<theme>/login', skip=[auth])
def login_html(theme=None):
    return render_tpl(theme or 'base', 'login', {
        'themes': themes(),
        'timezones': common_timezones,
    })


@app.post('/login', skip=[auth])
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
    response.set_cookie('session', data, secret)
    return {}


@app.get('/logout')
def logout():
    response.delete_cookie('session')
    return redirect('/login')


@app.get('/tags')
def tags():
    return wrap_tags(local.tags_info())


@app.post('/search')
def search():
    q = request.json['q']
    preload = request.json.get('preload', 200)

    if q.startswith(':threads'):
        q = q[8:]
        uids = local.search_thrs(q)
        info = 'thrs_info'
    elif q.startswith(':thread'):
        q = q[7:]
        preload = request.json.get('preload', 4)
        return thread(q, preload)
    else:
        uids = local.search_msgs(q)
        info = 'msgs_info'

    if preload and uids:
        msgs = getattr(local, info)
        msgs = wrap_msgs(msgs(uids[:preload]))
    else:
        msgs = {}
    return {
        'uids': uids,
        'msgs': msgs,
        'msgs_info': app.get_url(info),
        'threads': info == 'thrs_info'
    }


@app.post('/thrs/info', name='thrs_info')
def thrs_info():
    uids = request.json['uids']
    hide_tags = request.json.get('hide_tags', [])
    if not uids:
        return abort(400)
    return wrap_msgs(local.thrs_info(uids, hide_tags))


@app.post('/msgs/info', name='msgs_info')
def msgs_info():
    uids = request.json['uids']
    hide_tags = request.json.get('hide_tags', [])
    if not uids:
        return abort(400)
    return wrap_msgs(local.msgs_info(uids, hide_tags))


@app.post('/thrs/link')
def thrs_link():
    uids = request.json['uids']
    if not uids:
        return {}
    return local.link_threads(uids)


@app.post('/msgs/flag')
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


@app.get('/raw/<uid:int>', name='raw')
def raw(uid):
    box = request.query.get('box', local.SRC)
    msg = local.raw_msg(str(uid), box)
    if msg is None:
        return abort(404)

    response.content_type = 'text/plain'
    return msg


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


@app.get('/<filepath:path>', skip=[auth])
def serve_assets(filepath):
    return static_file(filepath, root=assets)


# Helpers bellow
tpl = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Mailur: {{title}}</title>
  <link rel="shortcut icon" href="/favicon.png">
  <link href="/{{css}}?{{mtime}}" rel="stylesheet">
  <script>
    window.data={{!data}};
  </script>
</head>
<body>
  <div id="app"/>
  <script type="text/javascript" src="/vendor.js?{{mtime}}"></script>
  <script type="text/javascript" src="/{{js}}?{{mtime}}"></script>
</body>
</html>
'''


def render_tpl(theme, page, data={}):
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


@ft.lru_cache(maxsize=None)
def themes():
    pkg = json.loads((root / 'package.json').read_text())
    return sorted(pkg['mailur']['themes'])


def thread(uid, preload=4):
    uids = local.search_msgs('INTHREAD REFS UID %s' % uid, '(DATE)')
    if not uids:
        return {}

    msgs = wrap_msgs(local.msgs_info(uids))

    tags = set()
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

    if preload is not None and len(uids) > preload:
        msgs_few = {
            i: m for i, m in msgs.items() if m['is_unread'] or m['is_pinned']
        }
        uids_few = [uids[0]] + uids[-3:]
        for i in uids_few:
            if i in msgs_few:
                continue
            msgs_few[i] = msgs[i]
        msgs = msgs_few

    return {
        'uids': uids,
        'msgs': msgs,
        'msgs_info': app.get_url('msgs_info'),
        'tags': tags,
        'same_subject': same_subject
    }


def wrap_tags(tags):
    def query(tag):
        if tag.startswith('\\'):
            q = tag[1:]
        else:
            q = 'keyword %s' % json.dumps(tag)
        return ':threads %s' % q

    def trancate(val, max=14, end='…'):
        return val[:max] + end if len(val) > max else val

    ids = sorted(clean_tags(tags), key=lambda i: tags[i]['name'])
    info = {
        t: dict(tags[t], query=query(t), short_name=trancate(tags[t]['name']))
        for t in ids
    }
    return {'ids': ids, 'info': info}


def clean_tags(tags):
    ignore = re.compile(r'(^\\|#sent|#latest|#link)')
    return sorted(i for i in tags if not ignore.match(i))


def wrap_msgs(items):
    def query_header(name, value):
        value = json.dumps(value, ensure_ascii=False)
        return ':threads header %s %s' % (name, value)

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
        info.update({
            'uid': uid,
            'count': len(addrs),
            'tags': clean_tags(flags),
            'from_list': from_list(addrs, max=3),
            'query_thread': ':thread %s' % uid,
            'query_subject': query_header('subject', info['subject']),
            'query_msgid': query_header('message-id', info['msgid']),
            'url_raw': app.get_url('raw', uid=info['origin_uid']),
            'time_human': humanize_dt(info['date'], tz=tz),
            'time_title': format_dt(info['date'], tz=tz),
            'is_unread': '\\Seen' not in flags,
            'is_pinned': '\\Flagged' in flags,
        })
        msgs[uid] = info
    return msgs


def from_list(addrs, max=4):
    if isinstance(addrs, str):
        addrs = [addrs]

    addrs_uniq = []
    addrs_list = []
    for a in reversed(addrs):
        if not a or a['addr'] in addrs_uniq:
            continue
        addrs_uniq.append(a['addr'])
        addrs_list.append(dict(a, query=':threads from %s' % a['addr']))

    addrs_list = list(reversed(addrs_list))
    if len(addrs_list) <= max:
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
        res = http.get(
            '/avatar/{hash}?d={default}&s={size}'
            .format(hash=hash, size=size, default=default)
        )
        result = hash, res.read() if res.status_code == 200 else None
        cache[hash] = result
        return result

    if not hasattr(fetch_avatars, 'cache'):
        fetch_avatars.cache = {}
    key = (size, default)
    fetch_avatars.cache.setdefault(key, {})
    cache = fetch_avatars.cache[key]

    http = HTTPClient.from_url('https://www.gravatar.com/')
    pool = Pool(20)
    res = pool.map(_avatar, hashes)
    return [(i[0], base64.b64encode(i[1]) if b64 else i[1]) for i in res if i]
