from collections import namedtuple

from . import read_file
from mailr import imap


def gen_response(filename, query):
    import imaplib
    import pickle
    from conf import username, password
    from tests import open_file

    im = imaplib.IMAP4_SSL('imap.gmail.com')
    im.login(username, password)
    im.select('&BEIENQRBBEI-')

    ids = im.uid('search', None, 'all')[1][0].decode().split()
    res = im.uid('fetch', ','.join(ids), query)
    with open_file(filename, mode='bw') as f:
        f.write(pickle.dumps((ids, res)))


def test_fetch():
    filename = 'files_imap/fetch-header-and-other.pickle'
    query = '(UID X-GM-MSGID FLAGS X-GM-LABELS RFC822.HEADER RFC822.HEADER)'
    #gen_response(filename, query)

    ids, data = read_file(filename)

    im = namedtuple('_', 'uid')(lambda *a, **kw: data)
    rows = imap.fetch(im, ids, query)
    import pprint as _; _.pprint(rows)
    assert len(ids) == len(rows)
    assert ids == list(str(k) for k in rows.keys())
    for id in ids:
        for key in query[1:-1].split():
            assert key in rows[int(id)]
