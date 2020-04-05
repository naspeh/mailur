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
    msg.add_header('Message-Id', message.gen_msgid())
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
    assert fn('(1)(2 3)') == (['1'], ['2', '3'])
    assert fn('(11)(21 31)') == (['11'], ['21', '31'])
    assert fn('(1)(2 3 (4 5))') == (['1'], ['2', '3', '4', '5'])
    assert fn('(130 131 (132 133 134 (138)(139)(140)))') == (
        ['130', '131', '132', '133', '134', '138', '139', '140'],
    )
    assert fn(b'(1)(2)(3)') == (['1'], ['2'], ['3'])


def test_fn_pack_uids():
    fn = imap.pack_uids
    assert fn(['1', '2', '3', '4']) == '1:4'
    assert fn(['1', '3', '4']) == '1,3:4'
    assert fn(['100', '1', '4', '3', '10', '9', '8', '7']) == '1,3:4,7:10,100'


def test_literal_size_limit(gm_client, raises):
    # for query like "UID 1,2,...,150000" should be big enough
    gm_client.add_emails([{} for i in range(0, 20)], parse=False)
    c = local.client(local.SRC)
    all_uids = c.search('ALL')

    uids = ','.join(str(i) for i in range(1, 150000))
    assert all_uids == c.search('UID %s' % uids)

    uid = ',%i' % (10 ** 6)
    uids += (uid * 20000)
    with raises(imap.Error) as e:
        c.search('UID %s' % uids)
    assert 'Too long argument' in str(e.value)


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


def test_idle():
    def handler(res):
        if handler.first:
            handler.first = False
            return
        raise ValueError

    handler.first = True
    con = local.client()
    # just check if timeout works
    assert not con.idle({'EXISTS': handler}, timeout=1)


def test_sieve(gm_client, msgs, raises, some):
    gm_client.add_emails([
        {'from': '"A" <A@t.com>'},
        {'from': '"B" <B@t.com>'}
    ])
    con = local.client(readonly=False)

    with raises(imap.Error) as e:
        res = con.sieve('ALL', 'addflag "#0";')
    assert e.value.args == (some,)
    assert some.value.startswith(b'script: line 1: error: unknown command')

    res = con.sieve('ALL', '''
    require ["imap4flags"];

    if header :contains "Subject" "Subj" {
        setflag "#subj";
    }
    ''')
    assert [m['flags'] for m in msgs()] == ['#subj', '#subj']

    res = con.sieve('UID *', 'require ["imap4flags"];addflag "#2";')
    assert res == [some]
    assert some.value.endswith(b'UID 2 OK')
    assert [m['flags'] for m in msgs()] == ['#subj', '#subj #2']

    res = con.sieve('UID 3', 'require ["imap4flags"];addflag "#2";')
    assert res == []
    assert [m['flags'] for m in msgs()] == ['#subj', '#subj #2']

    res = con.sieve('ALL', '''
    require ["imap4flags"];

    if address :is :all "from" "a@t.com" {
        addflag "#1";
    }
    ''')
    assert res == [some]
    assert [m['flags'] for m in msgs()] == ['#subj #1', '#subj #2']

    res = con.sieve('ALL', '''
    require ["imap4flags"];

    if address :is "from" ["a@t.com", "b@t.com"] {
        addflag "#ab";
    }
    ''')
    assert res == [some, some]
    assert [m['flags'] for m in msgs()] == ['#subj #1 #ab', '#subj #2 #ab']
