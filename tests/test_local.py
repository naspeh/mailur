from mailur import local


def test_uidpairs(gm_client, msgs, patch, call):
    gm_client.add_emails([{}, {}], parse=False)
    assert ['1', '2'] == [i['uid'] for i in msgs(local.SRC)]

    assert local.pair_origin_uids(['1', '2']) == ()
    assert local.pair_parsed_uids(['1', '2']) == ()

    local.parse()
    assert local.data_uidpairs.get() == {'1': '1', '2': '2'}
    assert local.pair_origin_uids(['1', '2']) == ('1', '2')
    assert local.pair_parsed_uids(['1', '2']) == ('1', '2')

    local.parse('uid 1')
    assert ['2', '3'] == [i['uid'] for i in msgs()]
    assert local.data_uidpairs.get() == {'1': '3', '2': '2'}
    assert local.pair_origin_uids(['1', '2']) == ('3', '2')
    assert local.pair_parsed_uids(['2', '3']) == ('2', '1')

    local.parse('all')
    assert ['4', '5'] == [i['uid'] for i in msgs()]
    assert local.data_uidpairs.get() == {'1': '4', '2': '5'}
    assert local.pair_origin_uids(['1', '2']) == ('4', '5')
    assert local.pair_parsed_uids(['4', '5']) == ('1', '2')
    assert local.pair_origin_uids(['2']) == ('5',)
    assert local.pair_parsed_uids(['5']) == ('2',)

    # warm cache up
    local.data_addresses.get()
    local.data_uidpairs.get()
    local.data_threads.get()
    local.data_msgids.get()
    with patch('imaplib.IMAP4.uid') as m:
        m.return_value = 'OK', []
        local.update_metadata('4')
        assert m.called
        assert m.call_args_list == [
            call('FETCH', '4', '(FLAGS BINARY.PEEK[1])'),
            call('FETCH', '1:*', '(UID BODY[HEADER.FIELDS (Subject)])'),
            call('THREAD', 'REFS UTF-8 INTHREAD REFS UID 4'),
        ]

    patched = {'wraps': local.update_metadata}
    with patch('mailur.local.update_metadata', **patched) as m:
        local.parse('uid 1')
        assert m.called
        assert m.call_args == call('6')

        m.reset_mock()
        local.parse('all')
        assert m.called
        assert m.call_args == call('1:*')

        m.reset_mock()
        local.parse()
        assert not m.called

        m.reset_mock()
        gm_client.add_emails([{}])
        assert m.called
        assert m.call_args == call('9')


def test_data_threads(gm_client):
    gm_client.add_emails([{'subj': 'new subj'}])
    assert local.data_threads.get()[1] == {'1': ['1']}
    assert local.search_thrs('all') == ['1']

    local.parse('all')
    assert local.data_threads.get()[1] == {'2': ['2']}
    assert local.search_thrs('all') == ['2']

    gm_client.add_emails([{'subj': 'new subj'}])
    assert local.data_threads.get()[1] == {'3': ['2', '3']}
    assert local.search_thrs('all') == ['3']

    gm_client.add_emails([{'in_reply_to': '<101@mlr>'}])
    assert local.data_threads.get()[1] == {'4': ['2', '3', '4']}
    assert local.search_thrs('all') == ['4']

    gm_client.add_emails([{'refs': '<101@mlr> <102@mlr>'}])
    assert local.data_threads.get()[1] == {'5': ['2', '3', '4', '5']}
    assert local.search_thrs('all') == ['5']

    local.parse('all')
    assert local.data_threads.get()[1] == {'9': ['6', '7', '8', '9']}
    assert local.search_thrs('all') == ['9']

    local.parse('uid *')
    assert local.data_threads.get()[1] == {'10': ['6', '7', '8', '10']}
    assert local.search_thrs('all') == ['10']

    local.update_threads('1:*')
    assert local.data_threads.get()[1] == {'10': ['6', '7', '8', '10']}
    assert local.search_thrs('all') == ['10']

    local.update_threads('1')
    assert local.data_threads.get()[1] == {'10': ['6', '7', '8', '10']}
    assert local.search_thrs('all') == ['10']

    local.update_threads('1:*')
    assert local.data_threads.get()[1] == {'10': ['6', '7', '8', '10']}
    assert local.search_thrs('all') == ['10']

    gm_client.add_emails([
        {'refs': '<non-exist@mlr>'},
        {'refs': '<non-exist@mlr> <101@mlr>'}
    ])
    assert local.data_threads.get()[1] == {
        '11': ['11'],
        '12': ['6', '7', '8', '10', '12']
    }
    assert local.search_thrs('all') == ['12', '11']

    gm_client.add_emails([{'labels': 't1'}, {'labels': 't2'}], parse=False)
    local.parse('UID 6:*')
    assert local.data_threads.get()[1] == {
        '11': ['11'],
        '13': ['6', '7', '8', '10', '13'],
        '14': ['14'],
        '15': ['15']
    }
    assert local.search_thrs('all') == ['15', '14', '13', '11']

    local.update_threads('*')
    assert local.data_threads.get()[1] == {
        '11': ['11'],
        '13': ['6', '7', '8', '10', '13'],
        '14': ['14'],
        '15': ['15']
    }
    assert local.search_thrs('all') == ['15', '14', '13', '11']


def test_link_threads_part1(gm_client, msgs):
    gm_client.add_emails([{}, {}])
    refs = [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>'
    ]
    assert local.data_threads.get()[1] == {'2': ['2'], '1': ['1']}
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    local.link_threads(['1', '2'])
    assert local.data_threads.get()[1] == {'2': ['1', '2']}
    res = msgs(local.SRC)
    assert [i['body']['references'] for i in res] == [None, None]

    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    local.parse('all')
    assert local.data_threads.get()[1] == {'4': ['3', '4']}
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    gm_client.add_emails([{}])
    refs += ['<ee1464274aa3795844800274f6a7dcdf@mailur.link>']
    assert local.search_thrs('all') == ['5', '4']
    assert local.data_threads.get()[1] == {'4': ['3', '4'], '5': ['5']}
    local.link_threads(['4', '5'])
    assert local.search_thrs('all') == ['5']
    assert local.data_threads.get()[1] == {'5': ['3', '4', '5']}
    res = msgs(local.SRC)
    assert [i['body']['references'] for i in res] == [None, None, None]
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    gm_client.add_emails([{'refs': '<101@mlr>'}])
    refs += ['<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <101@mlr>']
    assert local.search_thrs('all') == ['6']
    assert local.data_threads.get()[1] == {'6': ['3', '4', '5', '6']}
    res = msgs(local.SRC)
    assert [i['body']['references'] for i in res] == [
        None, None, None, '<101@mlr>'
    ]
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    assert local.search_thrs('uid 4') == [i[0] for i in local.thrs_info(['4'])]


def test_link_threads_part2(gm_client, msgs):
    gm_client.add_emails([
        {}, {'refs': '<101@mlr>'}, {}, {'refs': '<103@mlr>'}]
    )
    assert local.search_thrs('all') == ['4', '2']
    assert local.data_threads.get()[1] == {'2': ['1', '2'], '4': ['3', '4']}
    refs = [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <101@mlr>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <103@mlr>'
    ]
    res = msgs(local.SRC)
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>'
    ]
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    local.link_threads(['1', '3'])
    assert local.search_thrs('all') == ['4']
    assert local.data_threads.get()[1] == {'4': ['1', '2', '3', '4']}
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    gm_client.add_emails([{'refs': '<none@mlr> <102@mlr>'}])
    refs.append(
        '<dffb90273b253002d4357a0c75e05e73@mailur.link> <none@mlr> <102@mlr>'
    )
    assert local.search_thrs('all') == ['5']
    assert local.data_threads.get()[1] == {'5': ['1', '2', '3', '4', '5']}
    res = msgs(local.SRC)
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>', '<none@mlr> <102@mlr>'
    ]
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    assert local.search_thrs('uid 1') == [i[0] for i in local.thrs_info(['1'])]


def test_link_threads_part3(gm_client, msgs):
    gm_client.add_emails([
        {},
        {'refs': '<none-two@mlr>'},
        {'refs': '<none@mlr>'},
        {'refs': '<none@mlr> <102@mlr>'}
    ])
    refs = [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <none-two@mlr>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <none@mlr>',
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <none@mlr> <102@mlr>'
    ]
    assert local.search_thrs('all') == ['4', '3', '1']
    assert local.data_threads.get()[1] == {
        '1': ['1'], '3': ['3'], '4': ['2', '4']
    }
    res = msgs(local.SRC)
    assert [i['body']['references'] for i in res] == [
        None,
        '<none-two@mlr>',
        '<none@mlr>',
        '<none@mlr> <102@mlr>',
    ]
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    local.link_threads(['1', '3', '4'])
    assert local.search_thrs('all') == ['4']
    assert local.data_threads.get()[1] == {'4': ['1', '2', '3', '4']}
    res = msgs()
    assert [i['body']['references'] for i in res] == refs

    assert local.search_thrs('uid 1') == [i[0] for i in local.thrs_info(['1'])]


def test_msgids(gm_client, msgs, some, load_file, latest):
    gm_client.add_emails([{'mid': '<zero@mlr>'} for i in range(0, 8)])
    gm_client.add_emails([
        {'mid': '<42@mlr>'},
        {'mid': '<42@mlr>'},
    ])
    res = msgs(local.SRC)[-2:]
    assert [i['uid'] for i in res] == ['9', '10']
    assert [i['body']['message-id'] for i in res] == ['<42@mlr>', '<42@mlr>']
    assert local.data_msgids.get() == {
        '<zero@mlr>': ['1', '2', '3', '4', '5', '6', '7', '8'],
        '<42@mlr>': ['9', '10']
    }
    res = msgs()[-2:]
    assert [i['uid'] for i in res] == ['9', '10']
    assert [i['body']['message-id'] for i in res] == ['<42@mlr>', '<42@mlr>']

    gm_client.add_emails([
        {'raw': load_file('msg-header-with-no-msgid.txt')}
    ])
    msg = latest(local.SRC)
    assert msg['body']['message-id'] is None
    msg = latest()
    assert msg['body']['message-id'] == '<mailur@noid>'

    gm_client.add_emails([
        {'raw': load_file('msg-header-with-nospace-in-msgid.txt')}
    ])
    msg = latest(local.SRC)
    assert msg['body']['message-id'] == '<with-no-space-in-msgid@test>'
    msg = latest()
    assert msg['body']['message-id'] == '<with-no-space-in-msgid@test>'

    assert local.data_msgids.get() == {
        '<zero@mlr>': ['1', '2', '3', '4', '5', '6', '7', '8'],
        '<42@mlr>': ['9', '10'],
        '<mailur@noid>': ['11'],
        '<with-no-space-in-msgid@test>': ['12']
    }

    # message-id's should be used in lower case
    gm_client.add_emails([{'refs': '<42@MLR>', 'mid': '<109@MLR>'}])
    msg = latest(parsed=True)
    assert msg['body_full']['message-id'] == '<109@mlr>'
    assert msg['meta']['parent'] == '<42@mlr>'
    assert msg['meta']['msgid'] == '<109@mlr>'
    assert '<109@mlr>' in local.data_msgids.get()
    assert local.data_msgids.get()['<109@mlr>'] == ['13']

    gm_client.add_emails([{'refs': '<42@mlr>  <109@MLR>'}])
    msg = latest(parsed=True)
    assert msg['meta']['parent'] == '<109@mlr>'

    gm_client.add_emails([{'in_reply_to': '<109@MLR>'}])
    msg = latest(parsed=True)
    assert msg['meta']['parent'] == '<109@mlr>'


def test_thrid_header(gm_client, msgs):
    def raw(num, refs=None):
        refs = ('\r\nReferences: %s' % refs) if refs else ''
        return '\r\n'.join([
            'X-Thread-ID: <mlr/thrid/1516806882952089676@mailur.link>',
            'Date: Wed, 07 Jan 2015 13:23:{num:02d} +0000',
            'From: katya@example.com',
            'To: grrr@example.com',
            'MIME-Version: 1.0',
            'Content-type: text/html; charset=utf-8',
            'Content-Transfer-Encoding: 8bit',
            'Message-ID: <thrid-{num:02d}@mlr>',
            'Subject: thrid' + refs,
            ''
            'thrid',
        ]).format(num=num, refs=refs).encode()
    gm_client.add_emails([{'raw': raw(i)} for i in range(3)])
    assert local.search_thrs('all') == ['3']
    assert local.data_threads.get()[1] == {'3': ['1', '2', '3']}
    assert [i[0] for i in local.thrs_info(['1'])] == ['3']

    gm_client.add_emails([{'refs': '<thrid-01@mlr> <thrid-04@mlr>'}])
    assert local.search_thrs('all') == ['4']
    assert local.data_threads.get()[1] == {'4': ['1', '2', '3', '4']}
    assert [i[0] for i in local.thrs_info(['1'])] == ['4']

    gm_client.add_emails([{'raw': raw(4)}])
    assert local.search_thrs('all') == ['5']
    assert local.data_threads.get()[1] == {'5': ['1', '2', '3', '4', '5']}
    assert [i[0] for i in local.thrs_info(['1'])] == ['5']

    gm_client.add_emails([{'raw': raw(5, '<thrid-03@mlr> <thrid-06@mlr>')}])
    assert local.search_thrs('all') == ['6']
    assert local.data_threads.get()[1] == {'6': ['1', '2', '3', '4', '5', '6']}
    assert [i[0] for i in local.thrs_info(['1'])] == ['6']

    gm_client.add_emails([
        {'from': 't@t.com', 'to': 'Test <t@t.com>', 'subj': 'Same aubject'}
    ] * 2)
    assert local.search_thrs('all') == ['8', '6']
    assert local.data_threads.get()[1] == {
        '6': ['1', '2', '3', '4', '5', '6'],
        '8': ['7', '8'],
    }
    assert [i['body']['X-Thread-ID'] for i in msgs()][-2:] == [
        '<6355a01321452677ff71ea4899836a52@mailur.link>'
    ] * 2


def test_sieve_run(gm_client, msgs, some):
    gm_client.add_emails([
        {'from': 'me@t.com', 'to': 'a@t.com', 'labels': '\\Sent'},
        {'from': 'me@t.com', 'to': 'b@t.com', 'labels': '\\Sent'},
        {'from': 'o_O <spam@t.com>', 'to': 'me@t.com', 'labels': '\\Junk'},
    ])

    assert local.data_addresses.get() == [
        {'me@t.com': some},
        {'a@t.com': some, 'b@t.com': some, 'me@t.com': some}
    ]

    gm_client.add_emails([
        {'from': 'me@t.com', 'to': 'a@t.com', 'labels': '\\Sent'},
        {'from': 'a@t.com', 'labels': '\\Inbox'},
        {'from': 'b@t.com', 'labels': '\\Inbox'},
        {'from': 'c@t.com', 'labels': '\\Inbox'},
        {'from': 'd@t.com', 'labels': '\\Inbox'},
        {'from': 'spam@t.com', 'labels': '\\Inbox'},
    ])

    assert [m['flags'] for m in msgs(local.SRC)] == [
        '#sent', '#sent', '#spam',
        '#sent #personal', '#inbox #personal', '#inbox #personal',
        '#inbox', '#inbox', '#spam #inbox'
    ]
    assert [m['flags'] for m in msgs()] == [
        '#sent', '#sent', '#spam',
        '#sent #personal', '#personal #inbox', '#personal #inbox',
        '#inbox', '#inbox', '#spam #inbox'
    ]
