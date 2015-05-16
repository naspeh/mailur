import asyncio
import json

from aiohttp import web, request as http

from . import log


@asyncio.coroutine
def wshandler(request):
    ws = web.WebSocketResponse()
    ws.start(request)

    cookies = request.cookies

    while True:
        msg = yield from ws.receive()
        if msg.tp == web.MsgType.text:
            log.debug(msg.data)
            data = json.loads(msg.data)
            resp = yield from http('GET', data['url'], cookies=cookies.items())
            log.debug('%s %s', resp.status, msg.data)
            if resp.status == 200:
                cookies = dict(cookies, **resp.cookies)
                resp = (yield from resp.read()).decode()
                ws.send_str(json.dumps({'uid': data['uid'], 'data': resp}))
        elif msg.tp == web.MsgType.close:
            log.info('websocket connection closed')
            yield from ws.close()
            break
        elif msg.tp == web.MsgType.error:
            log.exception(ws.exception())
    return ws


@asyncio.coroutine
def init(loop, host, port):
    app = web.Application(loop=loop)
    app.router.add_route('GET', '/', wshandler)

    handler = app.make_handler()
    srv = yield from loop.create_server(handler, host, port)
    log.info('Server started at http://%s:%s', host, port)
    return app, srv, handler


@asyncio.coroutine
def finish(app, srv, handler):
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
