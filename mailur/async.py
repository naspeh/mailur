import asyncio
import json

from aiohttp import web, request as http

from . import log


@asyncio.coroutine
def wshandler(request):
    ws = web.WebSocketResponse()
    ws.start(request)

    request.app['sockets'].append(ws)
    cookies = request.cookies

    while True:
        msg = yield from ws.receive()
        if msg.tp == web.MsgType.text:
            log.debug(msg.data)
            data = json.loads(msg.data)
            payload = data.get('payload')
            if payload:
                payload = json.dumps(payload)
            resp = yield from http(
                'POST' if payload else 'GET',
                data['url'],
                data=payload,
                cookies=cookies.items()
            )
            log.debug('%s %s', resp.status, msg.data)
            if resp.status == 200:
                cookies = dict(cookies, **resp.cookies)
                resp = (yield from resp.read()).decode()
                ws.send_str(json.dumps({'uid': data['uid'], 'payload': resp}))
        elif msg.tp == web.MsgType.close:
            log.debug('ws closed')
            yield from ws.close()
            break
        elif msg.tp == web.MsgType.error:
            log.exception(ws.exception())

    request.app['sockets'].remove(ws)
    return ws


@asyncio.coroutine
def notify(request):
    yield from request.post()
    msg = json.dumps({'updated': request.POST.getall('ids')})
    for ws in request.app['sockets']:
        ws.send_str(msg)
    return web.Response(body=b'OK')


@asyncio.coroutine
def init(loop, host, port):
    app = web.Application(loop=loop)
    app['sockets'] = []
    app.router.add_route('GET', '/', wshandler)
    app.router.add_route('POST', '/notify/', notify)

    handler = app.make_handler()
    srv = yield from loop.create_server(handler, host, port)
    log.info('Server started at http://%s:%s', host, port)
    return app, srv, handler


@asyncio.coroutine
def finish(app, srv, handler):
    for ws in app['sockets']:
        ws.close()
    app['sockets'].clear()
    yield from asyncio.sleep(0.1)
    srv.close()
    yield from handler.finish_connections()
    yield from srv.wait_closed()


def run(host, port):
    loop = asyncio.get_event_loop()
    app, srv, handler = loop.run_until_complete(init(loop, host, port))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(finish(app, srv, handler))
