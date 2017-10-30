import functools as ft
import json
import pathlib
import re

from webob import Response, dec, exc

from . import log, local, imap

static = pathlib.Path(__file__).parent / 'static'
routes = re.compile('^/(%s)$' % '|'.join((
    r'(?P<index>)',
    r'(?P<msgs>msgs)',
    r'(?P<msgs_info>msgs/info)',
    r'(?P<threads>threads)',
    r'(?P<threads_info>threads/info)',
    r'(?P<origin>origin/(?P<oid>\d+))',
    r'(?P<parsed>parsed/(?P<pid>\d+))',
)))


@dec.wsgify
def application(req):
    route = routes.match(req.path)
    if not route:
        raise exc.HTTPNotFound

    route = route.groupdict()
    if route['index'] is not None:
        return (static / 'index.htm').read_text()
    elif route['origin']:
        return msg_raw(route['oid'])
    elif route['parsed']:
        return msg_raw(route['pid'], local.ALL)
    elif route['msgs']:
        return msgs(req.json['q'], req.json['preload'])
    elif route['msgs_info']:
        return jsonify(msgs_info)(req.json['uids'])
    elif route['threads']:
        return threads(req.json['q'], req.json['preload'])
    elif route['threads_info']:
        return jsonify(threads_info)(req.json['uids'])

    raise ValueError('No handler for %r' % route)


def jsonify(fn):
    @ft.wraps(fn)
    def inner(*a, **kw):
        res = fn(*a, **kw)
        return Response(json=res)
    return inner


@jsonify
def threads(q, preload):
    con = local.client()
    res = con.sort('(REVERSE DATE)', 'INTHREAD REFS %s KEYWORD #latest' % q)
    uids = res[0].decode().split()
    log.debug('query: %r; threads: %s', q, len(uids))
    if preload and uids:
        msgs = threads_info(uids[:preload], con)
    else:
        msgs = {}
    return {'uids': uids, 'msgs': msgs}


def threads_info(uids, con=None):
    if not uids:
        return {}

    def inner(uids, con):
        if con is None:
            con = local.client()

        thrs = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % uids.str)
        all_flags = {}
        res = con.fetch(thrs.all_uids, 'FLAGS')
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
        return msgs

    uids = imap.Uids(uids, size=1000)
    msgs = {}
    for i in uids.call_async(inner, uids, con):
        msgs.update(i)
    return msgs


@jsonify
def msgs(query, preload):
    con = local.client()
    res = con.sort('(REVERSE DATE)', query.encode())
    uids = res[0].decode().split()
    log.debug('query: %r; messages: %s', query, len(uids))
    if preload and uids:
        msgs = msgs_info(uids[:preload])
    else:
        msgs = {}
    return {'uids': uids, 'msgs': msgs}


def msgs_info(uids):
    con = local.client()
    res = con.fetch(uids, '(UID FLAGS BINARY.PEEK[2])')
    msgs = {}
    for i in range(0, len(res), 2):
        uid, flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', res[i][0].decode())
            .groups()
        )
        data = json.loads(res[i][1].decode())
        msgs[uid] = data
        msgs[uid]['flags'] = flags
    return msgs


def msg_raw(uid, box=local.SRC):
    con = local.client(box)
    res = con.fetch(uid, 'body[]')
    if not res:
        raise exc.HTTPNotFound
    txt = res[0][1]
    return Response(txt, content_type='text/plain')
