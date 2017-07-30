import pathlib
import re

import ujson as json
from sanic import Sanic, response
from sanic.config import LOGGING

from . import log, imap
from .parse import parsed_uids

LOGGING['handlers'].pop('accessTimedRotatingFile')
LOGGING['handlers'].pop('errorTimedRotatingFile')
LOGGING['loggers']['mailur'] = {
    'level': 'DEBUG',
    'handlers': ['internal', 'errorStream']
}


async def threads(request):
    query = request.raw_args['q']
    con = imap.Local(None)
    con.select(con.PARSED)
    res = con.thread('REFS UTF-8 INTHREAD REFS %s' % query)
    log.debug('query: %r; uids: %s', query, res[0])
    uids = [i for i in re.split('[)( ]+', res[0].decode()) if i]
    if not uids:
        return response.text('{}')

    msgs = {}
    flags = {}
    res = con.fetch(','.join(uids), 'FLAGS')
    for line in res:
        fs = re.search(r'FLAGS \(([^)]*)\)', line.decode()).group(1).split()
        thrid = [f for f in fs if f.startswith('T:')]
        if not thrid:
            continue
        thrid = thrid[0][2:].encode()
        flags.setdefault(thrid, set())
        flags[thrid].update(fs)

    puids_map = parsed_uids(flags)
    puids = b','.join(puids_map)
    res = con.sort('(REVERSE DATE)', 'UTF-8', b'UID %s' % puids)
    uids = [puids_map[i] for i in res[0].strip().split()]
    res = con.fetch(puids, '(BINARY.PEEK[2])')
    msgs = {}
    for i in range(0, len(res), 2):
        data = json.loads(res[i][1].decode())
        msgs[data['uid']] = data

    txt = json.dumps({'msgs': msgs, 'flags': flags, 'uids': uids})
    return response.text(txt)


async def emails(request):
    query = request.raw_args['q']
    con = imap.Local()
    res = con.sort('(REVERSE DATE)', 'UTF-8', query)
    log.debug('query: %r; uids: %s', query, res[0])
    uids = res[0].strip().split()
    if not uids:
        return response.text('{}')
    res = con.fetch(b','.join(uids), '(UID FLAGS)')
    flags = dict(
        re.search(r'UID (\d+) FLAGS \(([^)]*)\)', i.decode()).groups()
        for i in res
    )
    con.select(con.PARSED)
    puids = b','.join(parsed_uids(uids))
    log.debug('parsed uids: %s', puids)
    res = con.fetch(puids, '(BINARY.PEEK[2])')
    msgs = {}
    for i in range(0, len(res), 2):
        data = json.loads(res[i][1].decode())
        msgs[data['uid']] = data
    missing = set(i.decode() for i in uids) - set(msgs)
    if missing:
        raise ValueError('Missing parsed emails: %s', missing)
    txt = json.dumps({'msgs': msgs, 'flags': flags, 'uids': uids})
    return response.text(txt)


async def origin(request, uid):
    con = imap.Local()
    res = con.fetch(uid, 'body[]')
    return response.text(res[0][1].decode())


def get_app():
    app = Sanic()
    r = app.add_route
    r(emails, '/emails')
    r(threads, '/threads')
    r(origin, '/origin/<uid>')

    static = str(pathlib.Path(__file__).parent / 'static')
    app.static('/', static + '/index.htm')
    app.static('/', static)
    return app


if __name__ == '__main__':
    get_app().run(host="0.0.0.0", port=5000, log_config=LOGGING)
