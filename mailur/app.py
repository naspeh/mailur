import json
import pathlib
import re

from geventwebsocket import WebSocketError
from webob import Response, dec, exc

from . import log, local

static = pathlib.Path(__file__).parent / 'static'
routes = re.compile('^/(%s)$' % '|'.join((
    r'(?P<index>)',
    r'(?P<emails>emails)',
    r'(?P<threads>threads)',
    r'(?P<origin>origin/(?P<oid>\d+))',
    r'(?P<parsed>parsed/(?P<pid>\d+))',
)))


@dec.wsgify
def application(req):
    ws = req.environ.get("wsgi.websocket")
    if ws:
        websocket(ws)
        return

    route = routes.match(req.path)
    if not route:
        raise exc.HTTPNotFound

    route = route.groupdict()
    if route['index'] is not None:
        return (static / 'index.htm').read_text()
    elif route['origin']:
        return msg(route['oid'])
    elif route['parsed']:
        return msg(route['pid'], local.ALL)
    elif route['emails']:
        return emails(req.GET.get('q'))
    elif route['threads']:
        return threads(req.GET.get('q'))

    raise ValueError('No handler for %r' % route)


def threads(query):
    con = local.client()
    thrs = con.thread(b'REFS UTF-8 INTHREAD REFS %s' % query.encode())
    log.debug('query: %r; threads: %s', query, len(thrs))
    if not thrs:
        return '{}'

    all_flags = {}
    res = con.fetch(sum(thrs, []), 'FLAGS')
    for line in res:
        uid, flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', line.decode()).groups()
        )
        all_flags[uid] = flags

    flags = {}
    max_uid = min_uid = None
    for uids in thrs:
        thrid = None
        thr_flags = []
        for uid in uids:
            msg_flags = all_flags[uid]
            if not msg_flags:
                continue
            thr_flags.append(msg_flags)
            if '#latest' in msg_flags:
                thrid = uid
        if thrid is None:
            continue
        flags[thrid] = list(set(' '.join(thr_flags).split()))
        thrid_int = int(thrid)
        if not max_uid or thrid_int > max_uid:
            max_uid = thrid_int
        if not min_uid or thrid_int < min_uid:
            min_uid = thrid_int

    uid_range = 'UID %s:%s' % (min_uid, max_uid)
    res = con.sort('(REVERSE DATE)', '%s KEYWORD #latest' % uid_range)
    uids = [i for i in res[0].decode().split() if i in flags]

    msgs = {}
    res = con.fetch(uids, '(BINARY.PEEK[2])')
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        data = json.loads(res[i][1].decode())
        msgs[uid] = data
    return json.dumps({'msgs': msgs, 'flags': flags, 'uids': uids})


def emails(query):
    con = local.client()
    res = con.sort('(REVERSE DATE)', query.encode())
    uids = res[0].decode().split()
    log.debug('query: %r; messages: %s', query, len(uids))
    if not uids:
        return '{}'
    res = con.fetch(uids, '(UID FLAGS BINARY.PEEK[2])')
    msgs = {}
    flags = {}
    for i in range(0, len(res), 2):
        uid, msg_flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode())
            .groups()
        )
        flags[uid] = msg_flags
        data = json.loads(res[i][1].decode())
        msgs[uid] = data

    return json.dumps({'msgs': msgs, 'flags': flags, 'uids': uids})


def msg(uid, box=local.SRC):
    con = local.client(box)
    res = con.fetch(uid, 'body[]')
    if not res:
        raise exc.HTTPNotFound
    txt = res[0][1]
    return Response(txt, content_type='text/plain')


def websocket(ws):
    try:
        message = ws.receive()
        ws.send(message)
    except WebSocketError as e:
        log.exception(e)
