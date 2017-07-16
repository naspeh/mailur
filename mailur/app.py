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
    puids = b','.join(parsed_uids(con, uids))
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
    r(origin, '/origin/<uid>')

    static = str(pathlib.Path(__file__).parent / 'static')
    app.static('/', static + '/index.htm')
    app.static('/', static)
    return app


if __name__ == '__main__':
    get_app().run(host="0.0.0.0", port=5000, log_config=LOGGING)
