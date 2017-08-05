import pathlib
import re

import ujson as json
from sanic import Sanic, response
from sanic.config import LOGGING

from . import log, imap

LOGGING['loggers']['mailur'] = {
    'level': 'DEBUG',
    'handlers': ['internal', 'errorStream']
}


async def threads(request):
    query = request.raw_args['q']
    con = imap.Local(None)
    con.select(con.PARSED)
    res = con.thread('REFS UTF-8 INTHREAD REFS %s' % query)
    thrs = imap.parse_thread(res[0].decode())
    log.debug('query: %r; threads: %s', query, len(thrs))
    if not thrs:
        return response.text('{}')

    msgs = {}
    thrids = []
    all_flags = {}
    res = con.fetch(sum(thrs, []), 'FLAGS')
    for line in res:
        uid, flags = (
            re.search(r'UID (\d+) FLAGS \(([^)]*)\)', line.decode()).groups()
        )
        flags = flags.split()
        if '#latest' in flags:
            thrids.append(uid)
        all_flags[uid] = flags
    flags = {}
    for uids in thrs:
        thrid = set(uids).intersection(thrids)
        if not thrid:
            continue
        flags[thrid.pop()] = set(sum((all_flags[uid] for uid in uids), []))

    res = con.sort('(REVERSE DATE)', 'UTF-8', 'UID %s' % ','.join(flags))
    uids = res[0].decode().strip().split()
    res = con.fetch(uids, '(BINARY.PEEK[2])')
    msgs = {}
    for i in range(0, len(res), 2):
        uid = res[i][0].decode().split()[2]
        data = json.loads(res[i][1].decode())
        msgs[uid] = data

    txt = json.dumps({'msgs': msgs, 'flags': flags, 'uids': uids})
    return response.text(txt)


async def emails(request):
    query = request.raw_args['q']
    con = imap.Local(None)
    con.select(con.PARSED)
    res = con.sort('(REVERSE DATE)', 'UTF-8', query)
    uids = res[0].decode().strip().split()
    log.debug('query: %r; messages: %s', query, len(uids))
    if not uids:
        return response.text('{}')
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

    txt = json.dumps({'msgs': msgs, 'flags': flags, 'uids': uids})
    return response.text(txt)


async def origin(request, uid):
    con = imap.Local()
    res = con.fetch(uid, 'body[]')
    return response.text(res[0][1].decode())


async def parsed(request, uid):
    con = imap.Local(None)
    con.select(con.PARSED)
    res = con.fetch(uid, 'body[]')
    return response.text(res[0][1].decode())


def get_app():
    app = Sanic()
    r = app.add_route
    r(emails, '/emails')
    r(threads, '/threads')
    r(origin, '/origin/<uid>')
    r(parsed, '/parsed/<uid>')

    static = str(pathlib.Path(__file__).parent / 'static')
    app.static('/', static + '/index.htm')
    app.static('/', static)
    return app


if __name__ == '__main__':
    get_app().run(host="0.0.0.0", port=5000, log_config=LOGGING)
