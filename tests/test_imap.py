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
    res = im.uid('fetch', ','.join(ids), '(%s)' % query)
    with open_file(filename, mode='bw') as f:
        f.write(pickle.dumps((ids, res)))


def test_fetch_header_and_other():
    filename = 'files_imap/fetch-header-and-other.pickle'
    query = 'UID X-GM-MSGID FLAGS X-GM-LABELS RFC822.HEADER RFC822.HEADER'
    #gen_response(filename, query)

    ids, data = read_file(filename)

    im = namedtuple('_', 'uid')(lambda *a, **kw: data)
    rows = imap.fetch(im, ids, query)
    assert len(ids) == len(rows)
    assert ids == list(str(k) for k in rows.keys())
    for id in ids:
        value = rows[id]
        for key in query.split():
            assert key in value
            if key == 'X-GM-LABELS':
                continue
            labels = value['X-GM-LABELS']
            assert 'UID' in labels
            assert 'FLAGS ")\\' in labels


def test_fetch_body():
    filename = 'files_imap/fetch-header.pickle'
    query = 'RFC822.HEADER INTERNALDATE'
    #gen_response(filename, query)

    ids, data = read_file(filename)

    im = namedtuple('_', 'uid')(lambda *a, **kw: data)
    rows = imap.fetch(im, ids, query)
    assert len(ids) == len(rows)
    assert ids == list(str(k) for k in rows.keys())


def test_list():
    data = [
        b'(\\HasNoChildren) "/" "-job proposals"',
        b'(\\HasNoChildren) "/" "-social"',
        b'(\\HasNoChildren) "/" "FLAGS \\")\\\\"',
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "UID"',
        b'(\\Noselect \\HasChildren) "/" "[Gmail]"',
        b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
        b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"',
        b'(\\HasNoChildren \\Important) "/" "[Gmail]/Important"',
        b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
        b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
        b'(\\HasNoChildren \\Flagged) "/" "[Gmail]/Starred"',
        b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
        b'(\\HasNoChildren) "/" "work: 42cc"',
        b'(\\HasNoChildren) "/" "work: odesk"',
        b'(\\HasNoChildren) "/" "work: odeskps"',
        b'(\\HasNoChildren) "/" "&BEIENQRBBEI-"'
    ]

    im = namedtuple('_', 'list')(lambda *a, **kw: ('OK', data))
    rows = imap.list_(im)
    assert rows[0] == (('\\HasNoChildren',), '/', '-job proposals')
    assert rows[3] == (('\\HasNoChildren',), '/', 'INBOX')
    assert rows[5] == (('\\Noselect', '\\HasChildren'), '/', '[Gmail]')
    assert rows[-1] == (('\\HasNoChildren',), '/', '&BEIENQRBBEI-')
