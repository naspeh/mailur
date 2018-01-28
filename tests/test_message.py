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
        '0J7RgtCy0LXRgjogNDI=',
        ''
    ])


def test_general(clean_users, gm_client, load_file, latest, load_email):
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
        'From: Катя К. <katya@example.com>',
        'To: Grisha <grrr@example.com>',
    ])
    assert msg.startswith(expect), '%s\n\n%s' % (expect, msg)

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
    assert msg.startswith(expect), '%s\n\n%s' % (expect, msg)

    # msg with UnicodeDecodeError
    raw = b'\r\n'.join([
        b'Message-Id: <with-bad-symbol@test>',
        b'Subject: bad symbol?',
        b'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        b'From: katya@example.com',
        b'To: grrr@example.com',
        b'Content-type: text/html; charset=utf-8',
        b'Content-Transfer-Encoding: 8bit',
        b'MIME-Version: 1.0',
        b'',
        b'',
        b'\xd0\xb2\xd0\xbe\xd0\xb7\xd0\xbc\xd0\xbe\xd0\xb6\xd0\xbd\xd0\r\n '
        b'\xbe\xd1\x81\xd1\x82\xd0\xb8,'
    ])
    gm_client.add_emails([{'raw': raw}])
    msg = latest(parsed=True)
    assert msg['meta']['preview'] == 'возможн� �сти,'
    assert msg['body'] == '<p>возможн�&#13;\r\n �сти,</p>'
    assert msg['meta']['errors']
    assert (
        "error on 'text/html()': [UnicodeDecodeError] 'utf-8' codec can't "
        'decode byte 0xd0 in position 16: invalid continuation byte'
        in msg['meta']['errors'][0]
    )

    m = load_email('msg-from-ending-snail.txt', parsed=True)
    assert m['meta']['from'] == {
        'addr': 'grrr@', 'name': 'grrr', 'title': 'grrr@',
        'hash': '8ea2bc312c94c9596ad95772d6cd579c',
    }
    assert m['meta']['to']
    assert m['meta']['reply-to']
    assert m['body_full']['to'] == 'katya@'
    assert m['body_full']['from'] == 'grrr@'
    assert m['body_full']['reply-to'] == 'grrr@'

    m = load_email('msg-from-rss2email.txt', parsed=True)
    assert 'From: БлоGнот: Gray <feeds@yadro.org>' in m['raw'].decode()

    # test links
    m = load_email('msg-links.txt', parsed=True)
    link = '<a href="{0}" target="_blank">'
    l1 = link.format('https://github.com/naspeh/mailur')
    # l2 = link.format('http://bottlepy.org/docs/dev/routing.html#rule-syntax')
    l2 = link.format('http://bottlepy.org/docs/dev/routing.html')
    assert m['body'].count(l1) == 3
    assert m['body'].count(l2) == 2


def test_richer(gm_client, latest):
    headers = '\r\n'.join([
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: katya@example.com',
        'To: grrr@example.com',
        'MIME-Version: 1.0',
        'Content-type: text/html; charset=utf-8',
        'Content-Transfer-Encoding: 8bit',
    ])

    raw = '\r\n'.join([
        headers,
        'Message-Id: <richer-styles@test>',
        'Subject: styles',
        ''
        '<p style="color:red;@import">test html</p>',
    ])
    gm_client.add_emails([{'raw': raw.encode()}])
    m = latest(parsed=True)
    assert m['body'] == '<p data-style="color:red;">test html</p>'
    assert m['meta']['richer'] == 'Show styles'

    raw = '\r\n'.join([
        headers,
        'Message-Id: <richer-ext-imgs@test>',
        'Subject: external images',
        '',
        '<img src="https://github.com/favicon.ico" />',
        '<img src="http://github.com/favicon.ico" />',
        '<img src="//github.com/favicon.ico" />',
        '<img src="data:image/gif;base64,R0lGODlhEAA">'
    ])
    gm_client.add_emails([{'raw': raw.encode()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == []
    assert 'src="data:image/gif' in m['body']
    assert 'data-src="/proxy?url=%2F%2Fgithub.com' in m['body']
    assert 'data-src="/proxy?url=http%3A%2F%2Fgithub.com' in m['body']
    assert 'data-src="/proxy?url=https%3A%2F%2Fgithub.com' in m['body']
    assert m['meta']['richer'] == 'Show 3 external images'

    raw = '\r\n'.join([
        headers,
        'Message-Id: <richer-styles-and-imgs@test>',
        'Subject: styles and images',
        ''
        '<p style="color:red">test html</p>',
        '<img src="https://github.com/favicon.ico" />'
    ])
    gm_client.add_emails([{'raw': raw.encode()}])
    m = latest(parsed=True)
    assert 'data-src="/proxy?url=https%3A%2F%2Fgithub.com' in m['body']
    assert ' style="color:red"' not in m['body']
    assert 'data-style="color:red"' in m['body']
    assert m['meta']['richer'] == 'Show styles and 1 external images'


def test_encodings(gm_client, load_email):
    m = load_email('msg-encoding-empty-charset.txt', parsed=True)
    assert m['body'] == '<p>test</p>'

    m = load_email('msg-encoding-parts-in-koi8r.txt', parsed=True)
    assert m['meta']['subject'] == 'Тестим кодировку KOI8-R'
    assert m['body'] == '<p>тест</p>'

    m = load_email('msg-encoding-saved-in-koi8r.txt', parsed=True)
    assert m['meta']['subject'] == 'Тестим кодировку KOI8-R'
    assert m['body'] == '<p>тест</p>'

    # aliases
    m = load_email('msg-encoding-subject-gb2312.txt', parsed=True)
    assert m['meta']['subject'] == (
        'Почта Gmail – особенная. Вот что Вам нужно знать.'
    )

    m = load_email('msg-encoding-cp1251-alias.txt', parsed=True)
    assert m['meta']['subject'] == 'Обновления музыки на сайте JeTune.ru'
    assert m['body'] == '<p>Здравствуйте.<br></p>'

    m = load_email('msg-encoding-cp1251-chardet.txt', parsed=True)
    assert 'Уважаемый Гриша  !' in m['body']
    # subject shoud be decoded properly using charset detected in body
    assert m['meta']['subject'] == 'Оплатите, пожалуйста, счет'


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
    gm_client.add_emails([{'raw': binary('').as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == ''
    assert m['body'] == ''

    msg = binary('', 'application/json')
    msg.add_header('Content-Disposition', 'attachment; filename="1/f/ /.json"')
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {'filename': '1-f---.json', 'path': '', 'size': 0}
    ]
    assert m['meta']['preview'] == '[1-f---.json]'
    assert m['body'] == ''

    msg = MIMEPart()
    msg.make_related()
    msg.attach(binary(' ', 'text/plain'))
    msg.attach(binary(' ', 'text/html'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == ''
    assert m['body'] == ''

    msg = MIMEPart()
    msg.make_alternative()
    msg.attach(binary(' ', 'text/plain'))
    msg.attach(binary(' ', 'text/html'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == ''
    assert m['body'] == ''

    msg = MIMEPart()
    msg.make_mixed()
    msg.attach(binary('plain', 'text/plain'))
    msg.attach(binary('<p>html</p>', 'text/html'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == 'plain html'
    assert m['body'] == '<p>plain</p><hr><p>html</p>'

    msg = MIMEPart()
    msg.make_alternative()
    msg.attach(binary('plain', 'text/plain'))
    msg.attach(binary('<p>html</p>', 'text/html'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == 'html'
    assert m['body'] == '<p>html</p>'

    msg1 = MIMEPart()
    msg1.make_mixed()
    msg1.attach(msg)
    msg1.attach(binary('<p>html2</p>', 'text/html'))
    gm_client.add_emails([{'raw': msg1.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == 'html html2'
    assert m['body'] == '<p>html</p><hr><p>html2</p>'

    msg = MIMEPart()
    msg.make_mixed()
    msg.attach(binary('<br>plain', 'text/plain'))
    msg.attach(binary('<p>html</p>', 'text/html'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == '&lt;br&gt;plain html'
    assert m['body'] == '<p>&lt;br&gt;plain</p><hr><p>html</p>'

    msg = MIMEPart()
    msg.make_mixed()
    msg.attach(binary('1', 'application/json'))
    msg.attach(binary('2', 'application/json'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {'path': p, 'filename': 'unknown-%s.json' % p, 'size': 1}
        for p in ('1', '2')
    ]
    assert m['body'] == ''
    assert m['meta']['preview'] == '[unknown-1.json, unknown-2.json]'

    msg1 = MIMEPart()
    msg1.make_mixed()
    msg1.attach(binary('1'))
    msg1.attach(msg)
    gm_client.add_emails([{'raw': msg1.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {'path': p, 'filename': 'unknown-%s.json' % p, 'size': 1}
        for p in ('2.1', '2.2')
    ]
    assert m['body'] == '<p>1</p>'
    assert m['meta']['preview'] == '1 [unknown-2.1.json, unknown-2.2.json]'

    msg2 = MIMEPart()
    msg2.make_mixed()
    msg2.attach(msg)
    msg2.attach(binary('0'))
    msg2.attach(msg1)
    gm_client.add_emails([{'raw': msg2.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {'path': p, 'filename': 'unknown-%s.json' % p, 'size': 1}
        for p in ('1.1', '1.2', '3.2.1', '3.2.2')
    ]
    assert m['body'] == '<p>0</p><hr><p>1</p>'

    # test some real emails with attachments
    m = load_email('msg-attachments-one-gmail.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': '20.png', 'image': True, 'path': '2', 'size': 544}
    ]
    assert '<hr>' not in m['body']

    m = load_email('msg-attachments-two-gmail.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': '08.png', 'image': True, 'path': '2', 'size': 553},
        {'filename': '09.png', 'image': True, 'path': '3', 'size': 520}
    ]
    assert '<hr>' not in m['body']

    m = load_email('msg-attachments-two-yandex.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': '49.png', 'image': True, 'path': '2', 'size': 482},
        {'filename': '50.png', 'image': True, 'path': '3', 'size': 456}
    ]

    m = load_email('msg-attachments-textfile.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': 'Дополнение4.txt', 'path': '2', 'size': 11}
    ]
    assert m['body'] == '<p>тест</p>'

    m = load_email('msg-rfc822.txt', parsed=True)
    assert m['meta']['files'] == [
        {'filename': 'unknown-2.eml', 'path': '2', 'size': 463}
    ]

    # test embeds
    m = load_email('msg-embeds-one-gmail.txt', parsed=True)
    assert m['meta']['files'] == [{
        'content-id': '<ii_jcrlk9sk0_16122eb711c529e8>',
        'filename': '50.png',
        'image': True,
        'path': '2',
        'size': 456
    }]
    url = '/raw/%s/2' % m['meta']['origin_uid']
    assert url in m['body']
