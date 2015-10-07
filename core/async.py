import asyncio
import json
import aiohttp
import aiohttp.web as web

from . import Env, log


@asyncio.coroutine
def get_env(request):
    resp = yield from aiohttp.request(
        'GET', 'http://localhost:8000/check-auth/',
        headers=request.headers,
        cookies=request.cookies.items(),
        allow_redirects=False
    )
    if resp.status == 200:
        data = yield from resp.json()
        username = data.get('username')
        if username:
            return Env(username), None
        else:
            return None, web.Response(body=b'403 Forbidden', status=403)

    body = yield from resp.read()
    return None, web.Response(body=body, status=resp.status)


@asyncio.coroutine
def wshandler(request):
    env, error = yield from get_env(request)
    if error:
        return error

    ws = web.WebSocketResponse()
    ws.start(request)

    request.app['sockets'].append((env.username, ws))
    session = request.cookies.get('session')
    while True:
        msg = yield from ws.receive()
        if msg.tp == web.MsgType.text:
            log.debug(msg.data)
            data = json.loads(msg.data)
            payload = data.get('payload')
            if payload:
                payload = json.dumps(payload)
            resp = yield from aiohttp.request(
                'POST' if payload else 'GET',
                data['url'],
                headers={
                    'X-Requested-With': 'XMLHttpRequest',
                    'Cookie': data['cookie']
                },
                data=payload,
            )
            log.debug('%s %s', resp.status, msg.data)
            if resp.status == 200:
                p = (yield from resp.read()).decode()
                ws.send_str(json.dumps({'uid': data['uid'], 'payload': p}))
                new_session = resp.cookies.get('session')
                if new_session and session != new_session:
                    session = new_session.value
                    msg = {'session': new_session.output(header='').strip()}
                    ws.send_str(json.dumps(msg))
                    log.debug('sent new session')
        elif msg.tp == web.MsgType.close:
            log.debug('ws closed')
            yield from ws.close()
            break
        elif msg.tp == web.MsgType.error:
            log.exception(ws.exception())

    request.app['sockets'].remove((env.username, ws))
    return ws


@asyncio.coroutine
def notify(request):
    env, error = yield from get_env(request)
    if error:
        return error

    yield from request.post()
    msg = json.dumps({'updated': request.POST.getall('ids')})
    for username, ws in request.app['sockets']:
        if username == env.username:
            ws.send_str(msg)
    return web.Response(body=b'OK')


def create_app():
    app = web.Application()
    app.router.add_route('GET', '/', wshandler)
    app.router.add_route('POST', '/notify/', notify)

    app['sockets'] = []
    return app
