import functools as ft
import json
import pathlib
import re

from gevent.lock import RLock
from geventwebsocket import WebSocketError
from webob import Response, dec, exc

from . import log, local, imap

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


ws_handlers = {}


def ws_send(ws, lock, uid, body):
    msg = json.dumps({'uid': uid, 'body': body})
    log.debug(msg)
    with lock:
        return ws.send(msg)


def ws_handler(fn):
    ws_handlers[fn.__name__] = fn
    return fn


def websocket(ws):
    lock = RLock()
    try:
        while True:
            msg = ws.receive()
            log.debug(msg)
            if msg is None:
                break

            msg = json.loads(msg)
            target = msg['target']
            handler = ws_handlers['ws_%s' % target]
            send = ft.partial(ws_send, ws, lock, msg['uid'])
            handler(send, **msg['params'])
    except WebSocketError as e:
        log.exception(e)


@ws_handler
def ws_ping(send):
    return send('pong')


@ws_handler
def ws_threads(send, q):
    con = local.client()
    thrs = con.thread('REFS UTF-8 INTHREAD REFS %s' % q)
    log.debug('query: %r; threads: %s', q, len(thrs))
    if not thrs:
        send([])
        return
    thrs = sum(thrs, [])
    res = con.sort('(REVERSE DATE)', 'KEYWORD #latest')
    latest = res[0].decode().split()
    log.debug('latest %s', len(latest))
    thrs = [uid for uid in latest if uid in thrs]
    send(thrs)

    def inner(uids):
        con = local.client()
        thrs = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % uids.str)

        all_flags = {}
        res = con.fetch(sum(thrs, []), 'FLAGS')
        for line in res:
            uid, flags = re.search(
                r'UID (\d+) FLAGS \(([^)]*)\)', line.decode()
            ).groups()
            all_flags[uid] = flags

        msgs = {}
        for thr in thrs:
            thrid = None
            thr_flags = []
            for uid in thr:
                msg_flags = all_flags[uid]
                if not msg_flags:
                    continue
                thr_flags.append(msg_flags)
                if '#latest' in msg_flags:
                    thrid = uid
            if thrid is None:
                continue
            msgs[thrid] = {'flags': list(set(' '.join(thr_flags).split()))}

        log.debug('%s threads', len(msgs))
        res = con.fetch(msgs, '(BINARY.PEEK[2])')
        for i in range(0, len(res), 2):
            uid = res[i][0].decode().split()[2]
            data = json.loads(res[i][1].decode())
            msgs[uid].update(data)
        return send({'msgs': msgs})

    uids = imap.Uids(thrs[:5000], size=1000)
    uids.call_async(inner, uids)


@ws_handler
def ws_emails(send, q):
    con = local.client()
    res = con.sort('(REVERSE DATE)', q)
    uids = res[0].decode().split()
    log.debug('query: %r; messages: %s', q, len(uids))
    if not uids:
        return []
    send(uids)

    res = con.fetch(uids[:5000], '(UID FLAGS BINARY.PEEK[2])')
    msgs = {}
    for i in range(0, len(res), 2):
        uid, flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode())
            .groups()
        )
        data = json.loads(res[i][1].decode())
        msgs[uid] = data
        msgs[uid]['flags'] = flags
    send({'msgs': msgs})
