from mailur import imap, local, message


def test_batched_uids(gm_client):
    con = local.client()
    bsize = 25000
    assert [] == con.fetch([str(i) for i in range(1, 100, 2)], 'FLAGS')
    assert [] == con.fetch([str(i) for i in range(1, bsize, 2)], 'FLAGS')

    con.select(local.ALL, readonly=False)
    assert [] == con.store([str(i) for i in range(1, 100, 2)], '+FLAGS', '#')
    assert [] == con.store([str(i) for i in range(1, bsize, 2)], '+FLAGS', '#')

    # with one message
    msg = message.binary('42')
    msg.add_header('Message-Id', message.gen_msgid('test'))
    con.append(local.SRC, None, None, msg.as_bytes())
    con.select(local.SRC, readonly=True)
    assert [b'1 (UID 1 FLAGS (\\Recent))'] == (
        con.fetch([str(i) for i in range(1, 100, 2)], 'FLAGS')
    )
    assert [b'1 (UID 1 FLAGS (\\Recent))'] == (
        con.fetch([str(i) for i in range(1, bsize, 2)], 'FLAGS')
    )

    con.select(local.SRC, readonly=False)
    assert [b'1 (UID 1 FLAGS (\\Recent #1))'] == (
        con.store([str(i) for i in range(1, 100, 2)], '+FLAGS', '#1')
    )
    assert [b'1 (UID 1 FLAGS (\\Recent #1 #2))'] == (
        con.store([str(i) for i in range(1, bsize, 2)], '+FLAGS', '#2')
    )

    gm_client.add_emails([{} for i in range(1, 22)], parse=False)
    assert local.parse(batch=10) is None


def test_fn_parse_thread():
    fn = imap.parse_thread
    assert fn('(1)(2 3)') == (('1',), ('2', '3'))
    assert fn('(11)(21 31)') == (('11',), ('21', '31'))
    assert fn('(1)(2 3 (4 5))') == (('1',), ('2', '3', '4', '5'))
    assert fn('(130 131 (132 133 134 (138)(139)(140)))') == (
        ('130', '131', '132', '133', '134', '138', '139', '140'),
    )
    assert fn(b'(1)(2)(3)') == (('1',), ('2',), ('3',))


def test_fn_pack_uids():
    fn = imap.pack_uids
    assert fn(['1', '2', '3', '4']) == '1:4'
    assert fn(['1', '3', '4']) == '1,3:4'
    assert fn(['100', '1', '4', '3', '10', '9', '8', '7']) == '1,3:4,7:10,100'


def test_literal_size_limit(gm_client, raises):
    gm_client.add_emails([{} for i in range(0, 20)], parse=False)
    c = local.client(local.SRC)
    res = c.search('ALL')
    uids = res[0].decode().replace(' ', ',')

    uid = ',1%.127i' % 1 * 8
    uids += (uid * 1024 * 9)
    assert res == c.search('UID %s' % uids)

    uids += (uid * 1024)
    with raises(imap.Error) as e:
        c.search('UID %s' % uids)
    assert 'Too long argument' in str(e)


def test_multiappend(patch, msgs):
    new = [
        (None, None, message.binary(str(i)).as_bytes())
        for i in range(0, 10)
    ]
    con = local.client(None)
    with patch('gevent.pool.Pool.spawn') as m:
        m.return_value.value = ''
        con.multiappend(local.SRC, new)
        assert not m.called
        assert len(msgs(local.SRC)) == 10

        con.multiappend(local.SRC, new, batch=3)
        assert m.called
        assert m.call_count
        assert m.call_args_list[0][0][2] == new[0:3]
        assert m.call_args_list[1][0][2] == new[3:6]
        assert m.call_args_list[2][0][2] == new[6:9]
        assert m.call_args_list[3][0][2] == new[9:]

        m.reset_mock()
        con.multiappend(local.SRC, new, batch=5)
        assert m.called
        assert m.call_count
        assert m.call_args_list[0][0][2] == new[0:5]
        assert m.call_args_list[1][0][2] == new[5:]

    con.multiappend(local.SRC, new, batch=3)
    assert len(msgs(local.SRC)) == 20
