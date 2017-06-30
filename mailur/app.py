import json
import imaplib
import pathlib
import re

from sanic import Sanic, response

from .parse import connect


async def emails(request):
    query = request.raw_args['q']
    con = connect()
    con.select('All')
    ok, res = con.search(None, query)
    print(query, ok, res)
    ids = res[0].strip().replace(b' ', b',')
    ok, res = con.fetch(ids, '(UID FLAGS)')
    if ok != 'OK':
        raise ValueError(res)
    flags = dict(
        re.search(r'UID (\d+) FLAGS \(([^)]*)\)', i.decode()).groups()
        for i in res
    )
    flags = json.dumps(flags)
    #print(flags)
    con.select('Parsed')
    ok, res = con.fetch(ids, '(FLAGS BINARY.PEEK[TEXT])')
    if ok != 'OK':
        raise ValueError(res)
    msgs = ',\n'.join(
        '"%s": %s' % (
            re.search(br'FLAGS \(([^)]*)\)', res[i][0])[0].decode(),
            res[i][1].decode()[:-1])
        for i in range(0, len(res), 2)
    )
    return response.text('{"emails": {%s}, "flags": %s}' % (msgs, flags))


def get_app():
    app = Sanic()
    app.static('/', str(pathlib.Path(__file__).parent / 'static'))

    r = app.add_route
    r(emails, '/emails')
    return app


if __name__ == '__main__':
    get_app().run(host="0.0.0.0", port=5000)
