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


def test_thrids(clean_users, gm_client, msgs):
    gm_client.add_emails([{}])
    local.parse()
    res = msgs(local.ALL)
    assert ['#latest'] == [i[0] for i in res]

    gm_client.add_emails([{}])
    local.parse()
    res = msgs(local.ALL)
    assert ['#latest', '#latest'] == [i[0] for i in res]

    gm_client.add_emails([{'in_reply_to': '<101@mlr>'}])
    local.parse()
    res = msgs(local.ALL)
    assert ['', '#latest', '#latest'] == [i[0] for i in res]

    gm_client.add_emails([{'refs': '<101@mlr> <102@mlr>'}])
    local.parse()
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i[0] for i in res]

    local.parse('all')
    res = msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i[0] for i in res]


def test_parsed_msg(clean_users, gm_client, load_file, latest):
    gm_client.add_emails([{'flags': '\\Flagged'}])
    local.parse()
    flags, msg = latest(local.ALL)
    assert 'X-UID' in msg
    assert re.match('<\d+>', msg['X-UID'])
    assert '\\Flagged' in flags

    # `email.policy.default` is not working with long addresses.
    # Exits with: "segmentation fault (core dumped)"
    # when running in threads.
    gm_client.add_emails([
        {'txt': 'some text'},
        {'raw': load_file('msg-header-with-long-addresses.txt')}
    ])

    local.parse()
    flags, msg = latest(local.ALL)
    assert msg['to'].startswith('primary discussion list')

    # should be decoding of headers during parsing
    gm_client.add_emails([
        {'raw': load_file('msg-header-with-encoding.txt')}
    ])

    local.parse(batch=1)
    flags, msg = latest(local.ALL, raw=True)
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
    flags, msg = latest(local.ALL, raw=True)
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
