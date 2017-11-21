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

    con = local.client()
    assert local.pair_origin_uids(con, ['1', '2']) == ()
    assert local.pair_parsed_uids(con, ['1', '2']) == ()

    local.parse()
    con = local.client()
    assert local.uid_pairs(con) == {'1': '1', '2': '2'}
    assert local.pair_origin_uids(con, ['1', '2']) == ('1', '2')
    assert local.pair_parsed_uids(con, ['1', '2']) == ('1', '2')

    local.parse('uid 1')
    con = local.client()
    assert ['2', '3'] == [i['uid'] for i in msgs(local.ALL)]
    assert local.uid_pairs(con) == {'1': '3', '2': '2'}
    assert local.pair_origin_uids(con, ['1', '2']) == ('3', '2')
    assert local.pair_parsed_uids(con, ['2', '3']) == ('1', '2')

    local.parse('all')
    con = local.client()
    assert ['4', '5'] == [i['uid'] for i in msgs(local.ALL)]
    assert local.uid_pairs(con) == {'1': '4', '2': '5'}
    assert local.pair_origin_uids(con, ['1', '2']) == ('4', '5')
    assert local.pair_parsed_uids(con, ['4', '5']) == ('1', '2')
    assert local.pair_origin_uids(con, ['2']) == ('5',)
    assert local.pair_parsed_uids(con, ['5']) == ('2',)

    with patch.object(con, 'fetch') as m:
        m.return_value = []
        local.save_uid_pairs(con, '4')
        assert m.called
        assert m.call_args[0][0] == '4'

    def parse(criteria=None):
        try:
            local.parse(criteria)
        except ValueError:
            pass

    with patch.object(local, 'save_uid_pairs') as m:
        m.side_effect = ValueError
        parse('uid 1')
        assert m.called
        assert m.call_args[0][1] == '6'

        m.reset_mock()
        parse('all')
        assert m.called
        assert m.call_args[0][1] == '1:*'

        m.reset_mock()
        parse()
        assert not m.called

        m.reset_mock()
        gm_client.add_emails([{}])
        parse()
        assert m.called
        assert m.call_args[0][1] == '9'


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
    assert ['', '#latest', '#latest', '#link'] == [i['flags'] for i in res]

    gm_client.add_emails([{'refs': '<101@mlr> <102@mlr>'}])
    local.parse()
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#link'] == [i['flags'] for i in res]

    local.parse('all')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#link'] == [i['flags'] for i in res]

    local.parse('uid *')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#link'] == [i['flags'] for i in res]

    con = local.client()
    local.update_threads(con, 'all')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#link'] == [i['flags'] for i in res]

    local.update_threads(con, 'UID 1')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#link'] == [i['flags'] for i in res]

    local.update_threads(con)
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#link'] == [i['flags'] for i in res]

    gm_client.add_emails([{'labels': 'test1'}, {'labels': 'test2'}])
    local.parse('UID 4:*')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#latest #t1', '#latest #t2', '#link'] == [
        i['flags'] for i in res
    ]

    local.update_threads(con, 'UID *')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest', '#latest #t1', '#latest #t2', '#link'] == [
        i['flags'] for i in res
    ]


def thread(box=local.SRC):
    with local.client(box) as con:
        return con.thread('REFS UTF-8 ALL')


def test_link_threads_part1(clean_users, gm_client, msgs, some):
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
    assert ['1', '2', '3', '4'] == [i['uid'] for i in res]
    assert ['', '#latest', '#link', '#link'] == [i['flags'] for i in res]
    assert [i['body'].get('references', '').split() for i in res] == [
        [], [], ['<101@mlr>', '<102@mlr>'], ['<101@mlr>', '<102@mlr>', some]
    ]
    assert some.value.endswith('@mailur.link>')

    local.parse('all')
    res = msgs(local.SRC)
    assert (('1', '2', '3'),) == thread()
    assert ['', '', '#link'] == [i['flags'] for i in res]
    res = msgs(local.ALL)
    assert ['5', '6', '7', '8'] == [i['uid'] for i in res]
    assert ['', '#latest', '#link', '#link'] == [i['flags'] for i in res]
    assert [i['body'].get('references', '').split() for i in res] == [
        [], [], ['<101@mlr>', '<102@mlr>'], ['<101@mlr>', '<102@mlr>', some]
    ]
    assert some.value.endswith('@mailur.link>')

    gm_client.add_emails([{}])
    local.parse()
    local.link_threads(['5', '9'])
    res = msgs(local.SRC)
    assert (('1', '2', '4', '5'),) == thread()
    assert ['', '', '', '#link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        None, None, None, '<101@mlr> <102@mlr> <103@mlr>'
    ]
    res = msgs(local.ALL)
    assert ['5', '6', '9', '10', '11'] == [i['uid'] for i in res]
    assert ['', '', '#latest', '#link', '#link'] == [i['flags'] for i in res]
    assert [i['body'].get('references', '').split() for i in res] == [
        [], [], [], ['<101@mlr>', '<102@mlr>', '<103@mlr>'],
        ['<101@mlr>', '<102@mlr>', '<103@mlr>', some]
    ]
    assert some.value.endswith('@mailur.link>')

    gm_client.add_emails([{'refs': '<101@mlr>'}])
    local.parse()
    res = msgs(local.SRC)
    assert (('1', '2', '4', '5', '6'),) == thread()
    assert ['', '', '', '#link', ''] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        None, None, None, '<101@mlr> <102@mlr> <103@mlr>', '<101@mlr>'
    ]
    res = msgs(local.ALL)
    assert ['5', '6', '9', '10', '12', '13'] == [i['uid'] for i in res]
    assert [i['body'].get('references', '').split() for i in res] == [
        [], [], [], ['<101@mlr>', '<102@mlr>', '<103@mlr>'], [],
        ['<101@mlr>', '<102@mlr>', '<103@mlr>', some, '<104@mlr>']
    ]
    assert ['', '', '', '#link', '#latest', '#link'] == [
        i['flags'] for i in res
    ]


def test_link_threads_part2(clean_users, gm_client, msgs, some):
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
    assert [i['uid'] for i in res] == [
        '1', '2', '3', '4', '5', '6'
    ]
    assert [i['flags'] for i in res] == [
        '', '#latest', '', '#latest', '#link', '#link'
    ]
    assert [i['body'].get('references', '').split() for i in res] == [
        [], [], [], [], ['<101@mlr>', '<102@mlr>'], ['<103@mlr>', '<104@mlr>']
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
    assert [i['uid'] for i in res] == [
        '1', '2', '3', '4', '7', '8'
    ]
    assert [i['flags'] for i in res] == [
        '', '', '', '#latest', '#link', '#link'
    ]
    assert [i['body'].get('references', '').split() for i in res] == [
        [], [], [], [], ['<101@mlr>', '<102@mlr>', '<103@mlr>', '<104@mlr>'],
        ['<101@mlr>', '<102@mlr>', '<103@mlr>', '<104@mlr>', some]
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
    msg = latest(local.ALL, raw=True)['body']
    expect = '\r\n'.join([
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: Grisha <grrr@example.com>',
        'X-UID: <4>',
        'X-Subject: Re: не пора ли подкрепиться?'
    ])
    assert msg.decode().startswith(expect)

    gm_client.add_emails([
        {'raw': load_file('msg-header-with-no-encoding.txt')}
    ])

    local.parse(batch=1)
    msg = latest(local.ALL, raw=True)['body']
    expect = '\r\n'.join([
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: Гриша <grrr@example.com>',
        'X-UID: <5>',
        'X-Subject: Re: не пора ли подкрепиться?'
    ])
    assert msg.decode().startswith(expect)


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
