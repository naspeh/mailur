import json
import pathlib
import re

from sanic import Sanic, response

from .parse import connect, parsed_uids, BOX_ALL, BOX_PARSED


async def emails(request):
    query = request.raw_args['q']
    con = connect()
    con.select(BOX_ALL)
    ok, res = con.uid('SORT', '(REVERSE DATE)', 'UTF-8', query)
    if ok != 'OK':
        raise ValueError(res)
    print('query: %r; uids: %s' % (query, res[0]))
    uids = res[0].strip().split()
    if not uids:
        return response.text('{}')
    ok, res = con.uid('FETCH', b','.join(uids), '(UID FLAGS)')
    if ok != 'OK':
        raise ValueError(res)
    flags = dict(
        re.search(r'UID (\d+) FLAGS \(([^)]*)\)', i.decode()).groups()
        for i in res
    )
    con.select(BOX_PARSED)
    puids = b','.join(parsed_uids(con, uids))
    print('Parsed uids:', puids)
    ok, res = con.uid('FETCH', puids, '(FLAGS BINARY.PEEK[TEXT])')
    if ok != 'OK':
        raise ValueError(res)
    msgs = {
        re.search(br'FLAGS \([^)]*?(\d+)', res[i][0]).group(1):
        res[i][1].decode()[:-1]
        for i in range(0, len(res), 2)
    }
    missing = set(uids) - set(msgs)
    if missing:
        raise ValueError('Missing parsed emails: %s', missing)
    msgs = '\n,'.join(msgs[i] for i in uids)
    flags = json.dumps(flags)
    return response.text('{"emails": [%s], "flags": %s}' % (msgs, flags))


def get_app():
    app = Sanic()
    static = str(pathlib.Path(__file__).parent / 'static')
    app.static('/', static + '/index.htm')
    app.static('/', static)

    r = app.add_route
    r(emails, '/emails')
    return app


if __name__ == '__main__':
    get_app().run(host="0.0.0.0", port=5000)
