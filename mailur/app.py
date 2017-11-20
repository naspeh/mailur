import functools as ft
import json
import pathlib
import re

from webob import Response, dec, exc, static

from . import log, local, helpers

assets = pathlib.Path(__file__).parent / '../assets/dist'
routes = re.compile('^/api/(%s)$' % '|'.join((
    r'(?P<login>login)',
    r'(?P<tags>tags)',
    r'(?P<avatars>avatars.css)',
    r'(?P<msgs>msgs)',
    r'(?P<msgs_info>msgs/info)',
    r'(?P<threads>thrs)',
    r'(?P<threads_info>thrs/info)',
    r'(?P<threads_link>thrs/link)',
    r'(?P<origin>raw/(?P<oid>\d+)/origin)',
    r'(?P<parsed>raw/(?P<pid>\d+))',
)))


@dec.wsgify
def application(req):
    route = routes.match(req.path)
    if not route:
        return static.DirectoryApp(assets)

    route = route.groupdict()
    if route['login']:
        return login(req)
    elif route['origin']:
        return msg_raw(route['oid'])
    elif route['parsed']:
        return msg_raw(route['pid'], local.ALL)
    elif route['tags']:
        return tags(req)
    elif route['avatars']:
        return avatars(req)
    elif route['msgs']:
        return msgs(req, req.json['q'], req.json['preload'])
    elif route['msgs_info']:
        return jsonify(msgs_info)(req, req.json['uids'])
    elif route['threads']:
        return threads(req, req.json['q'], req.json['preload'])
    elif route['threads_info']:
        return jsonify(threads_info)(req, req.json['uids'])
    elif route['threads_link']:
        return threads_link(req)

    raise ValueError('No handler for %r' % route)


def jsonify(fn):
    @ft.wraps(fn)
    def inner(*a, **kw):
        res = fn(*a, **kw)
        return Response(json=res)
    return inner


def login(req):
    if req.method == 'POST':
        res = Response()
        res.set_cookie('offset', str(req.json['offset']))
        return res


@jsonify
def threads(req, q, preload):
    con = local.client()
    res = con.sort('(REVERSE DATE)', 'INTHREAD REFS %s KEYWORD #latest' % q)
    uids = res[0].decode().split()
    log.debug('query: %r; threads: %s', q, len(uids))
    if preload and uids:
        msgs = threads_info(req, uids[:preload], con)
    else:
        msgs = {}
    con.logout()
    return {'uids': uids, 'msgs': msgs}


def threads_info(req, uids, con=None):
    if not uids:
        return {}

    con = local.client()
    thrs = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % ','.join(uids))
    all_flags = {}
    all_msgs = {}
    res = con.fetch(thrs.all_uids, '(FLAGS BINARY.PEEK[1])')
    for i in range(0, len(res), 2):
        uid, flags = re.search(
            r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode()
        ).groups()
        flags = flags.split()
        if '#link' in flags:
            continue
        all_flags[uid] = flags
        all_msgs[uid] = json.loads(res[i][1])

    msgs = {}
    for thr in thrs:
        thrid = None
        thr_flags = []
        thr_from = []
        unseen = False
        for uid in thr:
            if uid not in all_msgs:
                continue
            info = all_msgs[uid]
            msg_flags = all_flags[uid]
            thr_from.append((info['date'], info.get('from')))
            if not msg_flags:
                continue
            if '\\Seen' not in msg_flags:
                unseen = True
            thr_flags.extend(msg_flags)
            if '#latest' in msg_flags:
                thrid = uid
        if thrid is None:
            raise ValueError('No #latest for %s' % thr)

        flags = list(set(' '.join(thr_flags).split()))
        if unseen and '\\Seen' in flags:
            flags.remove('\\Seen')
        if '#link' in flags:
            flags.remove('#link')
        if '#latest' in flags:
            flags.remove('#latest')
        addrs = [v for k, v in sorted(thr_from, key=lambda i: i[0])]
        msgs[thrid] = msg_info(req, all_msgs[thrid], thrid, flags, addrs)

    log.debug('%s threads', len(msgs))
    con.logout()
    return msgs


@jsonify
def threads_link(req):
    uids = req.json['uids']
    return local.link_threads(uids)


@jsonify
def msgs(req, query, preload):
    con = local.client()
    res = con.sort('(REVERSE DATE)', 'UNKEYWORD #link %s' % query)
    uids = res[0].decode().split()
    log.debug('query: %r; messages: %s', query, len(uids))
    if preload and uids:
        msgs = msgs_info(req, uids[:preload])
    else:
        msgs = {}
    con.logout()
    return {'uids': uids, 'msgs': msgs}


def msgs_info(req, uids):
    con = local.client()
    res = con.fetch(uids, '(UID FLAGS BINARY.PEEK[1])')
    msgs = {}
    for i in range(0, len(res), 2):
        uid, flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode())
            .groups()
        )
        msgs[uid] = msg_info(req, res[i][1], uid, flags.split())
    con.logout()
    return msgs


def msg_raw(uid, box=local.SRC):
    con = local.client(box)
    res = con.fetch(uid, 'body[]')
    if not res:
        raise exc.HTTPNotFound
    txt = res[0][1]
    con.logout()
    return Response(txt, content_type='text/plain')


@jsonify
def tags(req):
    return local.get_tags()


def avatars(req):
    hashes = set(req.GET['hashes'].split(','))
    size = req.GET.get('size', 20)
    default = req.GET.get('default', 'identicon')
    cls = req.GET.get('cls', '.pic-%s')

    css = '\n'.join((
        '%s {background-image: url(data:image/gif;base64,%s);}'
        % ((cls % h), i.decode())
    ) for h, i in helpers.fetch_avatars(hashes, size, default))
    return Response(css, content_type='text/css')


def msg_info(req, txt, uid, flags, addrs=None):
    offset = int(req.cookies['offset'])
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
        'flags': flags,
        'from_list': from_list(addrs),
        'url_raw': '/api/raw/%s' % uid,
        'url_raw_origin': '/api/raw/%s/origin' % info['origin_uid'],
        'time_human': helpers.humanize_dt(info['date'], offset=offset),
        'time_title': helpers.format_dt(info['date'], offset=offset),
        'is_unread': '\\Seen' not in flags,
        'is_pinned': '\\Flagged' in flags,
    })
    return info


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
