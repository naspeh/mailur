import re

from mailur import local
from mailur.message import addresses, binary


def test_binary_msg():
    assert binary('Ответ: 42').as_bytes() == '\n'.join([
        'MIME-Version: 1.0',
        'Content-Transfer-Encoding: binary',
        'Content-Type: text/plain; charset="utf-8"',
        '',
        'Ответ: 42'
    ]).encode()

    assert binary('Ответ: 42').as_string() == '\n'.join([
        'MIME-Version: 1.0',
        'Content-Transfer-Encoding: base64',
        'Content-Type: text/plain; charset="utf-8"',
        '',
        '0J7RgtCy0LXRgjogNDI=\n'
    ])


def test_parsed_msg(clean_users, gm_client, load_file, latest):
    gm_client.add_emails([{'flags': '\\Flagged'}])
    msg = latest()
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
    msg = latest()['body']
    assert msg['to'].startswith('primary discussion list')

    # should be decoding of headers during parsing
    gm_client.add_emails([
        {'raw': load_file('msg-header-with-encoding.txt')}
    ], parse=False)
    local.parse(batch=1)
    msg = latest(raw=True)['body'].decode()
    expect = '\r\n'.join([
        'X-UID: <4>',
        'Message-Id: <with-encoding@test>',
        'Subject: Re: не пора ли подкрепиться?',
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: Grisha <grrr@example.com>',
    ])
    assert msg.startswith(expect)

    gm_client.add_emails([
        {'raw': load_file('msg-header-with-no-encoding.txt')}
    ], parse=False)
    local.parse(batch=1)
    msg = latest(raw=True)['body'].decode()
    expect = '\r\n'.join([
        'X-UID: <5>',
        'Message-Id: <with-no-encoding@test>',
        'Subject: Re: не пора ли подкрепиться?',
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: Гриша <grrr@example.com>',
    ])
    assert msg.startswith(expect)


def test_encoding_aliases(gm_client, load_file, latest):
    gm_client.add_emails([
        {'raw': load_file('msg-subject-gb2312.txt')}
    ])
    msg = latest(parsed=True)
    assert msg['body']['subject'] == (
        'Почта Gmail – особенная. Вот что Вам нужно знать.'
    )


def test_addresses():
    res = addresses('test <test@example.com>')
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test <test@example.com>'
    }]

    res = addresses('test <TEST@example.com>')
    assert res == [{
        'name': 'test',
        'addr': 'TEST@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test <TEST@example.com>'
    }]

    res = addresses('test@example.com')
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test@example.com'
    }]

    res = addresses('test@example.com, test2 <test2@example.com>')
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
