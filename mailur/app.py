import json
import pathlib
import re

from sanic import Sanic, response

from .parse import connect


async def emails(request):
    query = request.raw_args['q']
    con = connect()
    con.select('All')
    ok, res = con.uid('SORT', '(DATE)', 'UTF-8', query)
    if ok != 'OK':
        raise ValueError(res)
    ids = res[0].strip().decode().split()
    print('query: %r; ids: %s' % (query, ids))
    ok, res = con.uid('FETCH', ','.join(ids), '(UID FLAGS)')
    if ok != 'OK':
        raise ValueError(res)
    flags = dict(
        re.search(r'UID (\d+) FLAGS \(([^)]*)\)', i.decode()).groups()
        for i in res
    )
    pids = [re.search(r' M:(\d*)', ' ' + flags[i]).group(1) for i in ids]
    print('Parsed uids:', pids)
    con.select('Parsed')
    ok, res = con.uid('FETCH', ','.join(pids), '(FLAGS BINARY.PEEK[TEXT])')
    if ok != 'OK':
        raise ValueError(res)
    msgs = {
        re.search(r'FLAGS \(([^)]*)\)', res[i][0].decode()).group(1):
        res[i][1].decode()[:-1]
        for i in range(0, len(res), 2)
    }
    msgs = '\n,'.join(msgs[i] for i in ids)
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
