import json
import pathlib

from bottle import Bottle, request, response, static_file, abort

from . import local, helpers

assets_path = pathlib.Path(__file__).parent / '../assets/dist'
app = Bottle()


@app.post('/init')
def init():
    response.set_cookie('offset', str(request.json['offset']))
    return {'tags': local.tags_info()}


@app.post('/search')
def search():
    q = request.json['q']
    preload = request.json['preload']

    if q.startswith(':threads'):
        q = q[8:]
        uids = local.search_thrs(q)
        msgs_url = '/thrs/info'
        msgs = local.thrs_info
    else:
        uids = local.search_msgs(q)
        msgs_url = '/msgs/info'
        msgs = local.msgs_info

    if preload and uids:
        msgs = wrap_msgs(msgs(uids[:preload]))
    else:
        msgs = {}
    return {'uids': uids, 'msgs': msgs, 'msgs_info': msgs_url}


@app.post('/thrs/info')
def thrs_info():
    uids = request.json['uids']
    if not uids:
        return abort(400)
    return wrap_msgs(local.thrs_info(uids))


@app.post('/msgs/info')
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


@app.get('/raw/<uid:int>')
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
    ) for h, i in helpers.fetch_avatars(hashes, size, default))


@app.get('/')
@app.get('/<filepath:path>')
def assets(filepath='index.html'):
    return static_file(filepath, root=assets_path)


def wrap_msgs(items):
    offset = int(request.cookies['offset'])
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
            'flags': [f for f in flags if not f.startswith('\\')],
            'from_list': from_list(addrs),
            'url_raw': '/raw/%s' % info['origin_uid'],
            'time_human': helpers.humanize_dt(info['date'], offset=offset),
            'time_title': helpers.format_dt(info['date'], offset=offset),
            'is_unread': '\\Seen' not in flags,
            'is_pinned': '\\Flagged' in flags,
        })
        msgs[uid] = info
    return msgs


def from_list(addrs, max=3):
    if isinstance(addrs, str):
        addrs = [addrs]

    addrs = [a for a in addrs if a]
    if len(addrs) <= 4:
        return addrs

    return [
        addrs[0],
        {'expander': len(addrs[1:-2])},
    ] + addrs[-2:]
