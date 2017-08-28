import pathlib
import re
from concurrent import futures

import ujson as json
from aiohttp import web, WSMsgType

from . import log, local

static = pathlib.Path(__file__).parent / 'static'
pool = futures.ProcessPoolExecutor()


def get_app():
    app = web.Application()
    r = app.router.add_route

    r('GET', '/ws', ws_client)
    r('GET', '/emails', emails)
    r('GET', '/threads', threads)
    r('GET', '/origin/{uid}', origin)
    r('GET', '/parsed/{uid}', parsed)

    bind_static(app.router)
    return app


def bind_static(router):
    async def index(request):
        return web.FileResponse(static / 'index.htm')

    router.add_get('/', index)
    router.add_static('/', static)


def match_info(handler):
    def inner(request):
        return handler(request, **request.match_info)
    return inner


async def run_sync(request, *a, **kw):
    return await request.app.loop.run_in_executor(pool, *a, **kw)


def threads_sync(query):
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
        flags[thrid] = set(' '.join(thr_flags).split())
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


async def threads(request):
    query = request.query['q']
    txt = await run_sync(request, threads_sync, query)
    return web.Response(text=txt)


def emails_sync(query):
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


async def emails(request):
    query = request.query['q']
    txt = await run_sync(request, emails_sync, query)
    return web.Response(text=txt)


def msg_sync(uid, box=local.SRC):
    con = local.client(box)
    res = con.fetch(uid, 'body[]')
    return res[0][1].decode()


@match_info
async def origin(request, uid):
    txt = await run_sync(request, msg_sync, uid)
    return web.Response(text=txt)


@match_info
async def parsed(request, uid):
    txt = await run_sync(request, msg_sync, uid, local.ALL)
    return web.Response(text=txt)


async def ws_client(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            if msg.data == 'close':
                await ws.close()
            elif msg.data == 'ping':
                await ws.send_str('pong')
            else:
                await ws.send_str(msg.data + '/answer')
        elif msg.type == WSMsgType.ERROR:
            log.error('ws connection closed with exception %s', ws.exception())

    log.info('ws connection closed')
    return ws


if __name__ == '__main__':
    web.run_app(get_app(), port=5000)
