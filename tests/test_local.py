from mailur import local


def test_uid_pairs(gm_client, msgs, patch):
    gm_client.add_emails([{}, {}], parse=False)
    assert ['1', '2'] == [i['uid'] for i in msgs(local.SRC)]

    assert local.pair_origin_uids(['1', '2']) == ()
    assert local.pair_parsed_uids(['1', '2']) == ()

    local.parse()
    assert local.uid_pairs() == ({'1': '1', '2': '2'}, {'1': '1', '2': '2'})
    assert local.pair_origin_uids(['1', '2']) == ('1', '2')
    assert local.pair_parsed_uids(['1', '2']) == ('1', '2')

    local.parse('uid 1')
    assert ['2', '3'] == [i['uid'] for i in msgs()]
    assert local.uid_pairs() == ({'1': '3', '2': '2'}, {'3': '1', '2': '2'})
    assert local.pair_origin_uids(['1', '2']) == ('3', '2')
    assert local.pair_parsed_uids(['2', '3']) == ('2', '1')

    local.parse('all')
    assert ['4', '5'] == [i['uid'] for i in msgs()]
    assert local.uid_pairs() == ({'1': '4', '2': '5'}, {'4': '1', '5': '2'})
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
        assert m.called
        assert m.call_args[0][0] == '9'


def test_update_threads(gm_client, msgs):
    gm_client.add_emails([{'subj': 'new subj'}])
    res = msgs()
    assert ['#latest'] == [i['flags'] for i in res]

    local.parse('all')
    res = msgs()
    assert ['#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([{'subj': 'new subj'}])
    res = msgs()
    assert ['', '#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([{'in_reply_to': '<101@mlr>'}])
    res = msgs()
    assert ['', '', '#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([{'refs': '<101@mlr> <102@mlr>'}])
    res = msgs()
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.parse('all')
    res = msgs()
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.parse('uid *')
    res = msgs()
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    con = local.client()
    local.update_threads(con, 'all')
    res = msgs()
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.update_threads(con, 'UID 1')
    res = msgs()
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    local.update_threads(con)
    res = msgs()
    assert ['', '', '', '#latest'] == [i['flags'] for i in res]

    gm_client.add_emails([
        {'refs': '<non-exist@mlr>'},
        {'refs': '<non-exist@mlr> <101@mlr>'}
    ])
    res = msgs()
    assert [i['flags'] for i in res] == [
        '', '', '', '', '#latest', '#latest'
    ]

    gm_client.add_emails([{'labels': 't1'}, {'labels': 't2'}], parse=False)
    local.parse('UID 6:*')
    res = msgs()
    assert [i['flags'] for i in res] == [
        '', '', '', '', '#latest', '#latest', '#latest t1', '#latest t2'
    ]

    local.update_threads(con, 'UID *')
    res = msgs()
    assert [i['flags'] for i in res] == [
        '', '', '', '', '#latest', '#latest', '#latest t1', '#latest t2'
    ]


def thread(box=local.SRC, criteria='ALL'):
    with local.client(box) as con:
        return con.thread('REFS UTF-8 %s' % criteria)


def test_link_threads_part1(gm_client, msgs):
    gm_client.add_emails([{}, {}])
    res = msgs()
    assert ['1', '2'] == [i['uid'] for i in res]
    assert ['#latest', '#latest'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>'
    ]

    local.link_threads(['1', '2'])
    res = msgs(local.SRC)
    assert (('1', '2', '3'),) == thread()
    assert ['', '', '\\Seen #link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [None, None, (
        '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr>'
    )]

    res = msgs()
    assert ['1', '2', '3'] == [i['uid'] for i in res]
    assert ['', '#latest', '\\Seen #link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr>'
        )
    ]

    local.parse('all')
    res = msgs(local.SRC)
    assert (('1', '2', '3'),) == thread()
    assert ['', '', '\\Seen #link'] == [i['flags'] for i in res]
    res = msgs()
    assert ['4', '5', '6'] == [i['uid'] for i in res]
    assert ['', '#latest', '\\Seen #link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr>'
        )
    ]

    gm_client.add_emails([{}])
    local.link_threads(['4', '7'])
    res = msgs(local.SRC)
    assert (('1', '2', '4', '5'),) == thread()
    assert ['1', '2', '4', '5'] == [i['uid'] for i in res]
    assert [i['flags'] for i in res] == [
        '', '', '', '\\Seen #link'
    ]
    assert [i['body']['references'] for i in res] == [
        None, None, None,
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr>'
        )
    ]
    res = msgs()
    assert ['4', '5', '7', '8'] == [i['uid'] for i in res]
    assert ['', '', '#latest', '\\Seen #link'] == [i['flags'] for i in res]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr>'
        )
    ]

    gm_client.add_emails([{'refs': '<101@mlr>'}])
    res = msgs(local.SRC)
    assert (('1', '2', '4', '5', '6'),) == thread()
    assert ['1', '2', '4', '5', '6'] == [i['uid'] for i in res]
    assert [i['flags'] for i in res] == [
        '', '', '', '\\Seen #link', ''
    ]
    assert [i['body']['references'] for i in res] == [
        None, None, None,
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr>'
        ),
        '<101@mlr>'
    ]
    res = msgs()
    assert ['4', '5', '7', '8', '9'] == [i['uid'] for i in res]
    assert [i['flags'] for i in res] == [
        '', '', '', '\\Seen #link', '#latest'
    ]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr>'
        ),
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <101@mlr>'
    ]
    assert local.search_thrs('uid 4') == [i[0] for i in local.thrs_info(['4'])]

    local.update_links()
    res = msgs(local.SRC)
    assert (('1', '2', '4', '6', '7'),) == thread()
    assert ['1', '2', '4', '6', '7'] == [i['uid'] for i in res]
    assert [i['flags'] for i in res] == [
        '', '', '', '', '\\Seen #link'
    ]
    res = msgs()
    assert ['4', '5', '7', '9', '10'] == [i['uid'] for i in res]
    assert [i['flags'] for i in res] == [
        '', '', '', '#latest', '\\Seen #link'
    ]


def test_link_threads_part2(gm_client, msgs):
    gm_client.add_emails([
        {}, {'refs': '<101@mlr>'}, {}, {'refs': '<103@mlr>'}]
    )
    res = msgs(local.SRC)
    assert thread() == (('1', '2'), ('3', '4'))
    assert [i['flags'] for i in res] == ['', '', '', '']
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>'
    ]
    res = msgs()
    assert [i['uid'] for i in res] == ['1', '2', '3', '4']
    assert [i['flags'] for i in res] == [
        '', '#latest', '', '#latest'
    ]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <101@mlr>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <103@mlr>'
    ]
    local.link_threads(['1', '3'])
    res = msgs(local.SRC)
    assert thread() == (('1', '2', '3', '4', '5'),)
    assert [i['flags'] for i in res] == ['', '', '', '', '\\Seen #link']
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr> '
            '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <104@mlr>'
        )
    ]
    res = msgs()
    assert [i['uid'] for i in res] == ['1', '2', '3', '4', '5']
    assert [i['flags'] for i in res] == [
        '', '', '', '#latest', '\\Seen #link'
    ]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <101@mlr>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <103@mlr>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr> '
            '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <104@mlr>'
        )
    ]

    gm_client.add_emails([{'refs': '<non-exist@mlr> <102@mlr>'}])
    res = msgs(local.SRC)
    assert thread() == (('1', '2', '3', '4', '5', '6'),)
    assert [i['flags'] for i in res] == ['', '', '', '', '\\Seen #link', '']
    assert [i['body']['references'] for i in res] == [
        None, '<101@mlr>', None, '<103@mlr>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr> '
            '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <104@mlr>'
        ),
        '<non-exist@mlr> <102@mlr>'
    ]
    res = msgs()
    assert [i['uid'] for i in res] == ['1', '2', '3', '4', '5', '6']
    assert [i['flags'] for i in res] == [
        '', '', '', '', '\\Seen #link', '#latest'
    ]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <101@mlr>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <103@mlr>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr> '
            '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <104@mlr>'
        ),
        '<dffb90273b253002d4357a0c75e05e73@mailur.link> <102@mlr>'
    ]
    assert local.search_thrs('uid 1') == [i[0] for i in local.thrs_info(['1'])]


def test_link_threads_part3(gm_client, msgs):
    gm_client.add_emails([
        {},
        {'refs': '<non-exist-two@mlr>'},
        {'refs': '<non-exist@mlr>'},
        {'refs': '<non-exist@mlr> <102@mlr>'}
    ])
    res = msgs(local.SRC)
    assert thread() == (('1',), ('3',), ('2', '4'),)
    assert [i['flags'] for i in res] == ['', '', '', '']
    assert [i['body']['references'] for i in res] == [
        None,
        '<non-exist-two@mlr>',
        '<non-exist@mlr>',
        '<non-exist@mlr> <102@mlr>',
    ]
    res = msgs()
    assert [i['uid'] for i in res] == ['1', '2', '3', '4']
    assert [i['flags'] for i in res] == [
        '#latest', '', '#latest', '#latest'
    ]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <102@mlr>'
    ]

    local.link_threads(['1', '3', '4'])
    res = msgs(local.SRC)
    assert [i['flags'] for i in res] == ['', '', '', '', '\\Seen #link']
    assert [i['body']['references'] for i in res] == [
        None,
        '<non-exist-two@mlr>',
        '<non-exist@mlr>',
        '<non-exist@mlr> <102@mlr>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr> '
            '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <104@mlr>'
        )
    ]
    res = msgs()
    assert [i['uid'] for i in res] == ['1', '2', '3', '4', '5']
    assert [i['flags'] for i in res] == [
        '', '', '', '#latest', '\\Seen #link'
    ]
    assert [i['body']['references'] for i in res] == [
        '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
        '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
        '<ee1464274aa3795844800274f6a7dcdf@mailur.link>',
        '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <102@mlr>',
        (
            '<9a500e323280b62c3476c27b9d23274a@mailur.link> <101@mlr> '
            '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link> <102@mlr> '
            '<ee1464274aa3795844800274f6a7dcdf@mailur.link> <103@mlr> '
            '<5ae1f76f370a3d4708a10285fcf18cbc@mailur.link> <104@mlr>'
        )
    ]
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
    assert local.msgids() == {
        '<zero@mlr>': ['1', '2', '3', '4', '5', '6', '7', '8'],
        '<42@mlr>': ['9', '10']
    }
    res = msgs()[-2:]
    assert [i['uid'] for i in res] == ['9', '10']
    assert [i['body']['message-id'] for i in res] == ['<42@mlr>', some]
    assert some.value.endswith('@mailur.dup>')
    msg = latest(parsed=True)
    assert msg['meta']['duplicate'] == '<42@mlr>'
    assert '#dup' in msg['flags']

    res = msgs()
    assert len(set([i['body']['message-id'] for i in res])) == 10

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

    assert local.msgids() == {
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
    assert '<109@mlr>' in local.msgids()
    assert local.msgids()['<109@mlr>'] == ['13']

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
    assert thread(local.ALL) == (('1', '2', '3'),)
    assert [i['flags'] for i in msgs()] == ['', '', '#latest']
    assert [i[0] for i in local.thrs_info(['1'])] == ['3']

    gm_client.add_emails([{'refs': '<thrid-01@mlr> <thrid-04@mlr>'}])
    assert thread(local.ALL) == (('1', '2', '4', '3'),)
    assert [i['flags'] for i in msgs()] == ['', '', '', '#latest']
    assert [i[0] for i in local.thrs_info(['1'])] == ['4']

    gm_client.add_emails([{'raw': raw(4)}])
    assert thread(local.ALL) == (('1', '2', '4', '3', '5'),)
    assert [i['flags'] for i in msgs()] == ['', '', '', '#latest', '']
    assert [i[0] for i in local.thrs_info(['1'])] == ['4']

    gm_client.add_emails([{'raw': raw(5, '<thrid-03@mlr> <thrid-06@mlr>')}])
    assert thread(local.ALL) == (('1', '2', '4', '3', '5', '6'),)
    assert [i['flags'] for i in msgs()] == ['', '', '', '#latest', '', '']
    assert [i[0] for i in local.thrs_info(['1'])] == ['4']

    gm_client.add_emails([
        {'from': 't@t.com', 'to': 't@t.com', 'subj': 'Same aubject'}
    ] * 2)
    assert thread(local.ALL, 'from t@t.com') == (('7', '8'),)
    assert [i['body']['X-Thread-ID'] for i in msgs()][-2:] == [
        '<ae5e0031d8e169ce266d123f56546087@mailur.link>'
    ] * 2
