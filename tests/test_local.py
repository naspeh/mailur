import re

from mailur import local


def test_binary_msg():
    assert local.binary_msg('Ответ: 42').as_bytes() == '\n'.join([
        'MIME-Version: 1.0',
        'Content-Transfer-Encoding: binary',
        'Content-Type: text/plain; charset="utf-8"',
        '',
        'Ответ: 42'
    ]).encode()

    assert local.binary_msg('Ответ: 42').as_string() == '\n'.join([
        'MIME-Version: 1.0',
        'Content-Transfer-Encoding: base64',
        'Content-Type: text/plain; charset="utf-8"',
        '',
        '0J7RgtCy0LXRgjogNDI=\n'
    ])


def test_uid_pairs(clean_users, gm_client, msgs, patch):
    gm_client.add_emails([{}, {}])
    assert ['1', '2'] == [i['uid'] for i in msgs(local.SRC)]

    assert local.pair_origin_uids(['1', '2']) == ()
    assert local.pair_parsed_uids(['1', '2']) == ()

    local.parse()
    assert local.uid_pairs() == {'1': '1', '2': '2'}
    assert local.pair_origin_uids(['1', '2']) == ('1', '2')
    assert local.pair_parsed_uids(['1', '2']) == ('1', '2')

    local.parse('uid 1')
    assert ['2', '3'] == [i['uid'] for i in msgs(local.ALL)]
    assert local.uid_pairs() == {'1': '3', '2': '2'}
    assert local.pair_origin_uids(['1', '2']) == ('3', '2')
    assert local.pair_parsed_uids(['2', '3']) == ('2', '1')

    local.parse('all')
    assert ['4', '5'] == [i['uid'] for i in msgs(local.ALL)]
    assert local.uid_pairs() == {'1': '4', '2': '5'}
    assert local.pair_origin_uids(['1', '2']) == ('4', '5')
    assert local.pair_parsed_uids(['4', '5']) == ('1', '2')
    assert local.pair_origin_uids(['2']) == ('5',)
    assert local.pair_parsed_uids(['5']) == ('2',)

    with patch('imaplib.IMAP4.uid') as m:
        m.return_value = 'OK', []
        local.save_uid_pairs('4')
        assert m.called
        assert m.call_args[0][1] == '4'

    with patch('mailur.local.save_uid_pairs', wraps=local.save_uid_pairs) as m:
        local.parse('uid 1')
        assert m.called
        assert m.call_args[0][0] == '6'

        m.reset_mock()
        local.parse('all')
        assert m.called
        assert m.call_args[0][0] == '1:*'

        m.reset_mock()
        local.parse()
        assert not m.called

        m.reset_mock()
        gm_client.add_emails([{}])
        local.parse()
        assert m.called
        assert m.call_args[0][0] == '9'


def test_update_threads(clean_users, gm_client, msgs):
    gm_client.add_emails([{}])
    local.parse()
    res = msgs(local.ALL)
    assert ['#latest'] == [i['flags'] for i in res]

    local.parse('all')
    res = msgs(local.ALL)
    assert ['#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([{}])
    local.parse()
    res = msgs(local.ALL)
    assert ['#latest', '#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([{'in_reply_to': '<101@mlr>'}])
    local.parse()
    res = msgs(local.ALL)
    assert ['', '#latest', '#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([{'refs': '<101@mlr> <102@mlr>'}])
    local.parse()
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.parse('all')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.parse('uid *')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    con = local.client()
    local.update_threads(con, 'all')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.update_threads(con, 'UID 1')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.update_threads(con)
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([
        {'refs': '<non-exist@mlr>'},
        {'refs': '<non-exist@mlr> <101@mlr>'}
    ])
    local.parse()
    res = msgs(local.ALL)
    assert [i['flags'] for i in res] == [
        '', '', '', '', '#latest', '#latest'
    ]

    gm_client.add_emails([{'labels': 'test1'}, {'labels': 'test2'}])
    local.parse('UID 6:*')
    res = msgs(local.ALL)
    assert [i['flags'] for i in res] == [
        '', '', '', '', '#latest', '#latest', '#latest #t1', '#latest #t2'
    ]

    local.update_threads(con, 'UID *')
    res = msgs(local.ALL)
    assert [i['flags'] for i in res] == [
        '', '', '', '', '#latest', '#latest', '#latest #t1', '#latest #t2'
    ]


def thread(box=local.SRC):
    with local.client(box) as con:
        return con.thread('REFS UTF-8 ALL')


def test_link_threads_part1(clean_users, gm_client, msgs):
    gm_client.add_emails([{}, {}])
    local.parse()
    res = msgs(local.ALL)
    assert ['1', '2'] == [i['uid'] for i in res]
    assert ['#latest', '#latest'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [None, None]

    local.link_threads(['1', '2'])
    res = msgs(local.SRC)
    assert (('1', '2', '3'),) == thread()
    assert ['', '', '#link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        None, None, '<101@mlr> <102@mlr>'
    ]

    res = msgs(local.ALL)
    assert ['1', '2', '3'] == [i['uid'] for i in res]
    assert ['', '#latest', '#link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        None, None, '<101@mlr> <102@mlr>'
    ]

    local.parse('all')
    res = msgs(local.SRC)
    assert (('1', '2', '3'),) == thread()
    assert ['', '', '#link'] == [i['flags'] for i in res]
    res = msgs(local.ALL)
    assert ['4', '5', '6'] == [i['uid'] for i in res]
    assert ['', '#latest', '#link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        None, None, '<101@mlr> <102@mlr>'
    ]

    gm_client.add_emails([{}])
    local.parse()
    local.link_threads(['4', '7'])
    res = msgs(local.SRC)
    assert (('1', '2', '4', '5', '3'),) == thread()
    assert ['1', '2', '3', '4', '5'] == [i['uid'] for i in res]
    assert [i['flags'] for i in res] == [
        '', '', '\\Deleted #link', '', '#link'
    ]
    assert [i['body']['references'] for i in res] == [
        None, None, '<101@mlr> <102@mlr>', None,
        '<101@mlr> <102@mlr> <103@mlr>'
    ]
    res = msgs(local.ALL)
    assert ['4', '5', '7', '8'] == [i['uid'] for i in res]
    assert ['', '', '#latest', '#link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        None, None, None, '<101@mlr> <102@mlr> <103@mlr>'
    ]

    gm_client.add_emails([{'refs': '<101@mlr>'}])
    local.parse()
    res = msgs(local.SRC)
    assert (('1', '2', '4', '5', '3', '6'),) == thread()
    assert ['1', '2', '3', '4', '5', '6'] == [i['uid'] for i in res]
    assert [i['flags'] for i in res] == [
        '', '', '\\Deleted #link', '', '#link', ''
    ]
    assert [i['body']['references'] for i in res] == [
        None, None, '<101@mlr> <102@mlr>', None,
        '<101@mlr> <102@mlr> <103@mlr>', '<101@mlr>'
    ]
    res = msgs(local.ALL)
    assert ['4', '5', '7', '8', '9'] == [i['uid'] for i in res]
    assert ['', '', '', '#link', '#latest'] == [
        i['flags'] for i in res
    ]
    assert [i['body']['references'] for i in res] == [
        None, None, None, '<101@mlr> <102@mlr> <103@mlr>', '<101@mlr>'
    ]


def test_link_threads_part2(clean_users, gm_client, msgs):
    gm_client.add_emails([
        {}, {'refs': '<101@mlr>'}, {}, {'refs': '<103@mlr>'}]
    )
    local.parse()
    res = msgs(local.SRC)
    assert thread() == (('1', '2'), ('3', '4'))
    assert [i['flags'] for i in res] == ['', '', '', '']
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>'
    ]
    res = msgs(local.ALL)
    assert [i['uid'] for i in res] == ['1', '2', '3', '4']
    assert [i['flags'] for i in res] == [
        '', '#latest', '', '#latest'
    ]
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>'
    ]

    local.link_threads(['1', '3'])
    res = msgs(local.SRC)
    assert thread() == (('1', '2', '3', '4', '5'),)
    assert [i['flags'] for i in res] == ['', '', '', '', '#link']
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>',
        '<101@mlr> <102@mlr> <103@mlr> <104@mlr>'
    ]
    res = msgs(local.ALL)
    assert [i['uid'] for i in res] == ['1', '2', '3', '4', '5']
    assert [i['flags'] for i in res] == [
        '', '', '', '#latest', '#link'
    ]
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>',
        '<101@mlr> <102@mlr> <103@mlr> <104@mlr>'
    ]

    gm_client.add_emails([{'refs': '<non-exist@mlr> <102@mlr>'}])
    local.parse()
    res = msgs(local.SRC)
    assert thread() == (('1', '2', '3', '4', '5', '6'),)
    assert [i['flags'] for i in res] == ['', '', '', '', '#link', '']
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>',
        '<101@mlr> <102@mlr> <103@mlr> <104@mlr>',
        '<non-exist@mlr> <102@mlr>'
    ]
    res = msgs(local.ALL)
    assert [i['uid'] for i in res] == ['1', '2', '3', '4', '5', '6']
    assert [i['flags'] for i in res] == [
        '', '', '', '', '#link', '#latest'
    ]
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>',
        '<101@mlr> <102@mlr> <103@mlr> <104@mlr>',
        '<102@mlr>'
    ]


def test_link_threads_part3(clean_users, gm_client, msgs):
    gm_client.add_emails([
        {},
        {'refs': '<non-exist-two@mlr>'},
        {'refs': '<non-exist@mlr>'},
        {'refs': '<non-exist@mlr> <102@mlr>'}
    ])
    local.parse()
    res = msgs(local.SRC)
    assert thread() == (('1',), ('3',), ('2', '4'),)
    assert [i['flags'] for i in res] == ['', '', '', '']
    assert [i['body']['references'] for i in res] == [
        None,
        '<non-exist-two@mlr>',
        '<non-exist@mlr>',
        '<non-exist@mlr> <102@mlr>',
    ]
    res = msgs(local.ALL)
    assert [i['uid'] for i in res] == ['1', '2', '3', '4']
    assert [i['flags'] for i in res] == [
        '#latest', '', '#latest', '#latest'
    ]
    assert [i['body']['references'] for i in res] == [
        None, None, None, '<102@mlr>'
    ]

    local.link_threads(['1', '3', '4'])
    res = msgs(local.SRC)
    assert [i['flags'] for i in res] == ['', '', '', '', '#link']
    assert [i['body']['references'] for i in res] == [
        None,
        '<non-exist-two@mlr>',
        '<non-exist@mlr>',
        '<non-exist@mlr> <102@mlr>',
        '<101@mlr> <102@mlr> <103@mlr> <104@mlr>'
    ]
    res = msgs(local.ALL)
    assert [i['uid'] for i in res] == ['1', '2', '3', '4', '5']
    assert [i['flags'] for i in res] == [
        '', '', '', '#latest', '#link'
    ]
    assert [i['body']['references'] for i in res] == [
        None, None, None, '<102@mlr>',
        '<101@mlr> <102@mlr> <103@mlr> <104@mlr>'
    ]


def test_parsed_msg(clean_users, gm_client, load_file, latest):
    gm_client.add_emails([{'flags': '\\Flagged'}])
    local.parse()
    msg = latest(local.ALL)
    assert 'X-UID' in msg['body']
    assert re.match('<\d+>', msg['body']['X-UID'])
    assert '\\Flagged' in msg['flags']

    # `email.policy.default` is not working with long addresses.
    # Exits with: "segmentation fault (core dumped)"
    # when running in threads.
    gm_client.add_emails([
        {'txt': 'some text'},
        {'raw': load_file('msg-header-with-long-addresses.txt')}
    ])

    local.parse()
    msg = latest(local.ALL)['body']
    assert msg['to'].startswith('primary discussion list')

    # should be decoding of headers during parsing
    gm_client.add_emails([
        {'raw': load_file('msg-header-with-encoding.txt')}
    ])

    local.parse(batch=1)
    msg = latest(local.ALL, raw=True)['body'].decode()
    expect = '\r\n'.join([
        'Message-Id: <with-encoding@test>',
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: Grisha <grrr@example.com>',
        'X-UID: <4>',
        'X-Subject: Re: не пора ли подкрепиться?'
    ])
    assert msg.startswith(expect)

    gm_client.add_emails([
        {'raw': load_file('msg-header-with-no-encoding.txt')}
    ])

    local.parse(batch=1)
    msg = latest(local.ALL, raw=True)['body'].decode()
    expect = '\r\n'.join([
        'Message-Id: <with-no-encoding@test>',
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: Гриша <grrr@example.com>',
        'X-UID: <5>',
        'X-Subject: Re: не пора ли подкрепиться?'
    ])
    assert msg.startswith(expect)


def test_addresses():
    res = local.addresses('test <test@example.com>')
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test <test@example.com>'
    }]

    res = local.addresses('test <TEST@example.com>')
    assert res == [{
        'name': 'test',
        'addr': 'TEST@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test <TEST@example.com>'
    }]

    res = local.addresses('test@example.com')
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test@example.com'
    }]

    res = local.addresses('test@example.com, test2 <test2@example.com>')
    assert res == [
        {
            'name': 'test',
            'addr': 'test@example.com',
            'hash': '55502f40dc8b7c769880b10874abc9d0',
            'title': 'test@example.com'
        },
        {
            'name': 'test2',
            'addr': 'test2@example.com',
            'hash': '43b05f394d5611c54a1a9e8e20baee21',
            'title': 'test2 <test2@example.com>'
        },
    ]
