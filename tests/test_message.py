import re
from email.message import MIMEPart

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


def test_encoding_aliases(gm_client, load_email):
    msg = load_email('msg-subject-gb2312.txt', parsed=True)
    assert msg['meta']['subject'] == (
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


def test_parts(gm_client, latest, load_email):
    msg = binary('1')
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']

    msg = MIMEPart()
    msg.make_mixed()
    msg.attach(binary('1', 'application/json'))
    msg.attach(binary('2', 'application/json'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {'path': p, 'size': 1} for p in ('1', '2')
    ]

    msg1 = MIMEPart()
    msg1.make_mixed()
    msg1.attach(binary('1'))
    msg1.attach(msg)
    gm_client.add_emails([{'raw': msg1.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {'path': p, 'size': 1} for p in ('2.1', '2.2')
    ]

    msg2 = MIMEPart()
    msg2.make_mixed()
    msg2.attach(msg)
    msg2.attach(binary('2'))
    msg2.attach(msg1)
    gm_client.add_emails([{'raw': msg2.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {'path': p, 'size': 1} for p in ('1.1', '1.2', '3.2.1', '3.2.2')
    ]

    # test some real emails with attachments
    m = load_email('msg-attachments-one-gmail.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': '20.png', 'path': '2', 'size': 544}
    ]

    m = load_email('msg-attachments-two-gmail.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': '08.png', 'path': '2', 'size': 553},
        {'filename': '09.png', 'path': '3', 'size': 520}
    ]

    m = load_email('msg-attachments-two-yandex.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': '49.png', 'path': '2', 'size': 482},
        {'filename': '50.png', 'path': '3', 'size': 456}
    ]

    # test embeds
    m = load_email('msg-embeds-one-gmail.txt', parsed=True)
    assert m['meta']['files'] == [{
        'content-id': '<ii_jcrlk9sk0_16122eb711c529e8>',
        'filename': '50.png',
        'path': '2',
        'size': 456
    }]
    url = '/raw/%s/2' % m['meta']['origin_uid']
    assert url in m['body']

    m = load_email('msg-embeds-external.txt', parsed=True)
    assert m['meta']['files'] == []
    assert 'data-src="/proxy?url=%2F%2Fwww.gravatar.com' in m['body']
    assert 'data-src="/proxy?url=http%3A%2F%2Fwww.gravatar.com' in m['body']
    assert 'data-src="/proxy?url=https%3A%2F%2Fwww.gravatar.com' in m['body']
