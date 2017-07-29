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
    res = con.search('INTHREAD REFS %s' % query)
    log.debug('query: %r; uids: %s', query, res[0])
    uids = res[0].strip().decode().split()
    if not uids:
        return response.text('{}')

    msgs = {}
    flags = {}
    processed = []
    for uid in uids:
        if uid in processed:
            continue
        res = con.thread('REFS UTF-8 INTHREAD REFS UID %s' % uid)
        thr_uids = [i for i in re.split('[)( ]*', res[0].decode()) if i]
        processed.extend(thr_uids)
        res = con.sort('(DATE)', 'UTF-8', 'UID %s' % ','.join(thr_uids))
        latest = res[0].decode().rsplit(' ', 1)[-1]
        if latest in msgs:
            continue
        res = con.fetch(','.join(thr_uids), 'FLAGS')
        thr_flags = set(sum((
            re.search(r'FLAGS \(([^)]*)\)', i.decode()).group(1).split()
            for i in res
        ), []))
        flags[latest] = thr_flags
        log.debug(
            'thrid=%s flags=%r uids=%r',
            latest,
            ' '.join(thr_flags),
            ','.join(thr_uids),
        )
        res = con.fetch(uid, '(BINARY.PEEK[2])')
        msgs[latest] = json.loads(res[0][1].decode())
    txt = json.dumps({'msgs': msgs, 'flags': flags, 'uids': flags.keys()})
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
    r(threads, '/threads')
    r(origin, '/origin/<uid>')

    static = str(pathlib.Path(__file__).parent / 'static')
    app.static('/', static + '/index.htm')
    app.static('/', static)
    return app


if __name__ == '__main__':
    get_app().run(host="0.0.0.0", port=5000, log_config=LOGGING)
