from unittest.mock import patch, call, ANY

from mailur import imap, local, gmail


@patch('mailur.imap.select')
def test_basic_gmail(select):
    con = gmail.client()
    assert select.call_args == call(ANY, b'All', True)
    assert set(con.__dict__.keys()) == set(
        '_con logout list select select_tag status search fetch'
        .split()
    )

    con.select_tag('\\Junk')
    assert select.call_args == call(ANY, b'Spam', True)

    con.select_tag('\\Trash')
    assert select.call_args == call(ANY, b'Trash', True)

    with patch('mailur.imap.log_time') as m:
        con.list()
        assert m.called


def test_batched_uids(clean_users, gm_client):
    con = local.client()
    bsize = 25000
    assert [] == con.fetch([str(i) for i in range(1, 100, 2)], 'FLAGS')
    assert [] == con.fetch([str(i) for i in range(1, bsize, 2)], 'FLAGS')

    con.select(local.ALL, readonly=False)
    assert [] == con.store([str(i) for i in range(1, 100, 2)], '+FLAGS', '#')
    assert [] == con.store([str(i) for i in range(1, bsize, 2)], '+FLAGS', '#')

    # with one message
    con.append(local.ALL, None, None, local.binary_msg('42').as_bytes())
    con.select(local.ALL, readonly=True)
    assert [b'1 (UID 1 FLAGS ())'] == (
        con.fetch([str(i) for i in range(1, 100, 2)], 'FLAGS')
    )
    assert [b'1 (UID 1 FLAGS ())'] == (
        con.fetch([str(i) for i in range(1, bsize, 2)], 'FLAGS')
    )

    con.select(local.ALL, readonly=False)
    assert [b'1 (UID 1 FLAGS (#1))'] == (
        con.store([str(i) for i in range(1, 100, 2)], '+FLAGS', '#1')
    )
    assert [b'1 (UID 1 FLAGS (#1 #2))'] == (
        con.store([str(i) for i in range(1, bsize, 2)], '+FLAGS', '#2')
    )

    gm_client.add_emails([{} for i in range(1, 22)])
    gmail.fetch_folder()
    assert local.parse(batch=10) is None


def test_fn_parse_thread():
    fn = imap.parse_thread
    assert fn('(1)(2 3)') == [['1'], ['2', '3']]
    assert fn('(11)(21 31)') == [['11'], ['21', '31']]
    assert fn('(1)(2 3 (4 5))') == [['1'], '2 3 4 5'.split()]
    assert fn('(130 131 (132 133 134 (138)(139)(140)))') == [
        '130 131 132 133 134 138 139 140'.split()
    ]
    assert fn(b'(1)(2)(3)') == [['1'], ['2'], ['3']]


def test_fn_pack_uids():
    fn = imap.pack_uids
    assert fn(['1', '2', '3', '4']) == '1:4'
    assert fn(['1', '3', '4']) == '1,3:4'
    assert fn(['100', '1', '4', '3', '10', '9', '8', '7']) == '1,3:4,7:10,100'
