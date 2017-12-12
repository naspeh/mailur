import base64
import datetime as dt
import json
import pathlib
import re

from bottle import Bottle, abort, request, response, static_file

from gevent.pool import Pool

from geventhttpclient import HTTPClient

from . import local

assets_path = pathlib.Path(__file__).parent / '../assets/dist'
app = Bottle()


@app.post('/init')
def init():
    if request.json:
        response.set_cookie('offset', str(request.json['offset']))

    return {'tags': wrap_tags(local.tags_info())}


@app.post('/search')
def search():
    q = request.json['q']
    preload = request.json['preload']

    if q.startswith(':threads'):
        q = q[8:]
        uids = local.search_thrs(q)
        info = 'thrs_info'
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
    if not uids:
        return abort(400)
    return wrap_msgs(local.thrs_info(uids))


@app.post('/msgs/info', name='msgs_info')
def msgs_info():
    uids = request.json['uids']
    if not uids:
        return abort(400)
    return wrap_msgs(local.msgs_info(uids))


@app.post('/thrs/link')
def thrs_link():
    uids = request.json['uids']
    if not uids:
        return {}
    return local.link_threads(uids)


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


@app.get('/')
@app.get('/<filepath:path>')
def assets(filepath='index.html'):
    themes = [t.name for t in assets_path.glob('*') if t.is_dir()]
    themes = '|'.join('%s/' % t for t in themes)
    theme, filepath = re.match('^(%s|)(.*)' % themes, filepath).groups()
    if theme and not filepath:
        filepath = theme + 'index.html'
    return static_file(filepath, root=assets_path)


# Helpers bellow
def wrap_tags(tags):
    def query(tag):
        if tag.startswith('\\'):
            q = tag[1:]
        else:
            q = 'keyword %s' % json.dumps(tag)
        return ':threads %s' % q

    def trancate(val, max=14, end='…'):
        return val[:max] + end if len(val) > max else val

    return {
        tag: dict(i, query=query(tag), short_name=trancate(i['name']))
        for tag, i in tags.items()
    }


def wrap_msgs(items):
    def query_header(name, value):
        value = json.dumps(value, ensure_ascii=False)
        return ':threads header %s %s' % (name, value)

    offset = int(request.cookies.get('offset', 0))
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
            'flags': [f for f in flags if not f.startswith('\\')],
            'from_list': from_list(addrs, max=3),
            'query_thread': 'inthread refs uid %s' % uid,
            'query_subject': query_header('subject', info['subject']),
            'query_msgid': query_header('message-id', info['msgid']),
            'url_raw': app.get_url('raw', uid=info['origin_uid']),
            'time_human': humanize_dt(info['date'], offset=offset),
            'time_title': format_dt(info['date'], offset=offset),
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


def localize_dt(val, offset=None):
    if isinstance(val, (float, int)):
        val = dt.datetime.fromtimestamp(val)
    return val + dt.timedelta(hours=(offset or 0))


def format_dt(value, offset=None, fmt='%a, %d %b, %Y at %H:%M'):
    return localize_dt(value, offset).strftime(fmt)


def humanize_dt(val, offset=None, secs=False):
    val = localize_dt(val, offset)
    now = localize_dt(dt.datetime.utcnow(), offset)
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
