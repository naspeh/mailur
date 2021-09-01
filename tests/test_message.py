import re
from email.message import MIMEPart

from mailur import local
from mailur.message import addresses, binary


def test_binary():
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


def test_general(gm_client, load_file, latest, load_email):
    gm_client.add_emails([{'flags': '\\Flagged'}])
    msg = latest()
    assert 'X-UID' in msg['body']
    assert re.match(r'<\d+>', msg['body']['X-UID'])
    assert '\\Flagged' in msg['flags']

    # `email.policy.default` is not working with long addresses.
    # Exits with: "segmentation fault (core dumped)"
    # when running in threads.
    gm_client.add_emails([
        {'txt': 'some text'},
        {'raw': load_file('msg-header-with-long-addresses.txt')}
    ])
    msg = latest()['body']
    assert msg['to'].startswith('"primary discussion list')

    # should be decoding of headers during parsing
    gm_client.add_emails([
        {'raw': load_file('msg-header-with-encoding.txt')}
    ], parse=False)
    local.parse(batch=1)
    msg = latest(raw=True)['body'].decode()
    expect = '\r\n'.join([
        'X-UID: <4>',
        'Message-ID: <with-encoding@test>',
        'Subject: Re: не пора ли подкрепиться?',
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: "Grisha" <grrr@example.com>',
    ])
    assert msg.startswith(expect), '%s\n\n%s' % (expect, msg)

    gm_client.add_emails([
        {'raw': load_file('msg-header-with-no-encoding.txt')}
    ], parse=False)
    local.parse(batch=1)
    msg = latest(raw=True)['body'].decode()
    expect = '\r\n'.join([
        'X-UID: <5>',
        'Message-ID: <with-no-encoding@test>',
        'Subject: Re: не пора ли подкрепиться?',
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: "Катя К." <katya@example.com>',
        'To: "Гриша" <grrr@example.com>',
    ])
    assert msg.startswith(expect), '%s\n\n%s' % (expect, msg)

    # msg with UnicodeDecodeError
    raw = b'\r\n'.join([
        b'Message-ID: <with-bad-symbol@test>',
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
    assert msg['body'] == '<p>возможн�\r\n �сти,</p>'
    assert msg['meta']['errors']
    assert (
        "error on 'text/html()': [UnicodeDecodeError] 'utf-8' codec can't "
        'decode byte 0xd0 in position 16: invalid continuation byte'
        in msg['meta']['errors'][0]
    )

    m = load_email('msg-lookup-error.txt', parsed=True)
    assert m['meta']['preview'] == 'test'
    assert m['body'] == '<p>test</p>'
    assert m['meta']['errors']
    assert (
        '[LookupError] unknown encoding: iso-2022-int-1'
        in m['meta']['errors'][0]
    )

    # date can't be parsed
    raw = b'\r\n'.join([
        b'Message-ID: <with-bad-symbol@test>',
        b'Subject: bad symbol?',
        b'Date: 15.06.2018 09:24:13 +0800',
        b'From: katya@example.com',
        b'To: grrr@example.com',
        b'Content-type: text/html; charset=utf-8',
        b'Content-Transfer-Encoding: 8bit',
        b'MIME-Version: 1.0',
        b'',
        b'',
        b'Hello!'
    ])
    gm_client.add_emails([{'raw': raw}])
    msg = latest(parsed=True)
    assert msg['meta']['date'] == msg['meta']['arrived']
    assert msg['meta']['errors'] == [
        'error on date: val=\'15.06.2018 09:24:13 +0800\' '
        'err=TypeError("\'NoneType\' object is not iterable",)'
    ]

    # ending @ symbol and address without @ symbol at all
    # TODO: investigate python 3.6.8
    # m = load_email('msg-from-ending-snail.txt', parsed=True)
    # assert m['meta']['from'] == {
    #     'addr': 'grrr@', 'name': 'grrr', 'title': 'grrr@',
    #     'hash': '8ea2bc312c94c9596ad95772d6cd579c',
    # }
    # assert m['meta']['reply-to'] == [{
    #     'addr': 'grrr', 'name': 'grrr', 'title': 'grrr',
    #     'hash': 'd4468c0c805f9a0e200c0e916824547a',
    # }]
    # assert m['meta']['to']
    # assert m['meta']['reply-to']
    # assert m['body_full']['to'] == 'katya@'
    # assert m['body_full']['from'] == 'grrr@'
    # assert m['body_full']['reply-to'] == 'grrr'

    raw = load_email('msg-from-rss2email.txt', parsed=True)['raw'].decode()
    assert 'From: "БлоGнот: Gray" <feeds@yadro.org>' in raw, raw

    # test links
    m = load_email('msg-links.txt', parsed=True)
    link = '<a href="{0}" target="_blank">'
    l1 = link.format('https://github.com/naspeh/mailur')
    # l2 = link.format('http://bottlepy.org/docs/dev/routing.html#rule-syntax')
    l2 = link.format('http://bottlepy.org/docs/dev/routing.html')
    assert m['body'].count(l1) == 3, '%s\n%s' % (l1, m['body'])
    assert m['body'].count(l2) == 2, '%s\n%s' % (l2, m['body'])


def test_richer(gm_client, latest, login):
    web = login()

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
        'Message-ID: <richer-styles@test>',
        'Subject: styles',
        ''
        '<p style="color:red;@import">test html</p>',
    ])
    gm_client.add_emails([{'raw': raw.encode()}])
    m = latest(parsed=True)
    assert m['body'] == '<p style="color:red;">test html</p>'
    assert m['meta']['styles']
    assert 'ext_images' not in m['meta']
    info = web.search({'q': 'uid:%s' % m['uid']})['msgs'][m['uid']]
    assert info['richer'] == 'Show styles'
    body = web.body(m['uid'])
    assert body == '<p data-style="color:red;">test html</p>'

    raw = '\r\n'.join([
        headers,
        'Message-ID: <richer-ext-imgs@test>',
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
    assert m['meta']['ext_images'] == 3
    assert 'styles' not in m['meta']
    assert m['body'].count('<img src="') == 4
    info = web.search({'q': 'uid:%s' % m['uid']})['msgs'][m['uid']]
    assert info['richer'] == 'Show 3 external images'
    body = web.body(m['uid'])
    assert body == (
        '<span><img data-src="/proxy?url=https://github.com/favicon.ico">\r\n'
        '<img data-src="/proxy?url=http://github.com/favicon.ico">\r\n'
        '<img data-src="/proxy?url=https://github.com/favicon.ico">\r\n'
        '<img src="data:image/gif;base64,R0lGODlhEAA"></span>'
    )

    raw = '\r\n'.join([
        headers,
        'Message-ID: <richer-styles-and-imgs@test>',
        'Subject: styles and images',
        ''
        '<p style="color:red">test html</p>',
        '<img src="https://github.com/favicon.ico" />'
    ])
    gm_client.add_emails([{'raw': raw.encode()}])
    m = latest(parsed=True)
    assert m['meta']['ext_images'] == 1
    assert m['meta']['styles']
    assert m['body'].count('<img src="') == 1
    assert m['body'].count('<p style="') == 1
    info = web.search({'q': 'uid:%s' % m['uid']})['msgs'][m['uid']]
    assert info['richer'] == 'Show styles and 1 external images'
    body = web.body(m['uid'])
    assert 'data-src="/proxy?url=https://github.com' in body
    assert ' style="color:red"' not in body
    assert 'data-style="color:red"' in body


def test_encodings(gm_client, load_email):
    m = load_email('msg-encoding-empty-charset.txt', parsed=True)
    assert m['body'] == '<p>test</p>'

    m = load_email('msg-encoding-parts-in-koi8r.txt', 'koi8-r', parsed=True)
    assert m['meta']['subject'] == 'Тестим кодировку KOI8-R'
    assert m['body'] == '<p>тест</p>'

    m = load_email('msg-encoding-saved-in-koi8r.txt', 'koi8-r', parsed=True)
    assert m['meta']['subject'] == 'Тестим кодировку KOI8-R'
    assert m['body'] == '<p>тест</p>'

    # aliases
    m = load_email('msg-encoding-subject-gb2312.txt', parsed=True)
    assert m['meta']['subject'] == (
        'Почта Gmail – особенная. Вот что Вам нужно знать.'
    )

    m = load_email('msg-encoding-cp1251-alias.txt', 'cp1251', parsed=True)
    assert m['meta']['subject'] == 'Обновления музыки на сайте JeTune.ru'
    assert m['body'] == '<p>Здравствуйте.<br></p>'

    m = load_email('msg-encoding-cp1251-chardet.txt', 'cp1251', parsed=True)
    assert 'Уважаемый Гриша&nbsp;&nbsp;!' in m['body']
    # subject shoud be decoded properly using charset detected in body
    assert m['meta']['subject'] == 'Оплатите, пожалуйста, счет'


def test_addresses():
    res = addresses('test <test@example.com>')
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': '"test" <test@example.com>'
    }]

    res = addresses('test <TEST@example.com>')
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': '"test" <TEST@example.com>'
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
            'title': '"test2" <test2@example.com>'
        },
    ]


def test_parts(gm_client, latest, load_email):
    gm_client.add_emails([{'raw': binary('').as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == ''
    assert m['body'] == ''
    assert m['body_txt'] is None

    raw = '<?xml version="1.0" encoding="UTF-8"?>'
    gm_client.add_emails([{'raw': binary(raw, 'text/html').as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['preview'] == ''
    assert m['body'] == ''

    gm_client.add_emails([{'raw': binary(' a  b\n   c d').as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == ' a b c d'
    assert m['body'] == '<p>&nbsp;a&nbsp;&nbsp;b<br>&nbsp;&nbsp;&nbsp;c d</p>'

    raw = (
        '<p>'
        '<img data-style="test" />'
        '<img data-src="test" />'
        '<img data-style="color:blue" style="color:red" />'
        '<img src="test" />'
        '</p>'
    )
    gm_client.add_emails([{'raw': binary(raw, 'text/html').as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['preview'] == ''
    assert m['body'] == '<p><img><img><img style="color:red"><img></p>'

    msg = binary('', 'application/json')
    msg.add_header('Content-Disposition', 'attachment; filename="1/f/ /.json"')
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {
            'filename': '1-f---.json',
            'path': '',
            'size': 0,
            'url': '/raw/5/1-f---.json',
        }
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
    assert m['body_txt'] is None

    msg = MIMEPart()
    msg.make_alternative()
    msg.attach(binary('plain', 'text/plain'))
    msg.attach(binary('<p>html</p>', 'text/html'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == 'html'
    assert m['body'] == '<p>html</p>'
    assert m['body_txt'] == 'plain'

    msg = MIMEPart()
    msg.make_alternative()
    msg.attach(binary('plain', 'text/plain'))
    htm = MIMEPart()
    htm.make_related()
    htm.attach(binary('<p>html</p>', 'text/html'))
    msg.attach(htm)
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == 'html'
    assert m['body'] == '<p>html</p>'
    assert m['body_txt'] == 'plain'

    msg1 = MIMEPart()
    msg1.make_mixed()
    msg1.attach(msg)
    msg1.attach(binary('<p>html2</p>', 'text/html'))
    gm_client.add_emails([{'raw': msg1.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == 'html html2'
    assert m['body'] == '<p>html</p><hr><p>html2</p>'
    assert m['body_txt'] is None

    msg = MIMEPart()
    msg.make_mixed()
    msg.attach(binary('<br>plain', 'text/plain'))
    msg.attach(binary('<p>html</p>', 'text/html'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert not m['meta']['files']
    assert m['meta']['preview'] == '&lt;br&gt;plain html'
    assert m['body'] == '<p>&lt;br&gt;plain</p><hr><p>html</p>'
    assert m['body_txt'] is None

    msg = MIMEPart()
    msg.make_mixed()
    msg.attach(binary('1', 'application/json'))
    msg.attach(binary('2', 'application/json'))
    gm_client.add_emails([{'raw': msg.as_bytes()}])
    m = latest(parsed=True)
    assert m['meta']['files'] == [
        {
            'filename': 'unknown-%s.json' % p,
            'path': p,
            'size': 1,
            'url': '/raw/%s/%s/unknown-%s.json' % (m['uid'], p, p),
        } for p in ('1', '2')
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
        {
            'filename': 'unknown-%s.json' % p,
            'path': p,
            'size': 1,
            'url': '/raw/%s/%s/unknown-%s.json' % (m['uid'], p, p),
        } for p in ('2.1', '2.2')
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
        {
            'filename': 'unknown-%s.json' % p,
            'path': p,
            'size': 1,
            'url': '/raw/%s/%s/unknown-%s.json' % (m['uid'], p, p),
        } for p in ('1.1', '1.2', '3.2.1', '3.2.2')
    ]
    assert m['body'] == '<p>0<br><br>1</p>'

    # test some real emails with attachments
    m = load_email('msg-attachments-one-gmail.txt', 'koi8-r', parsed=True)
    assert m['meta']['files'] == [
        {
            'filename': '20.png',
            'image': True,
            'path': '2',
            'size': 544,
            'url': '/raw/16/2/20.png',
        }
    ]
    assert '<hr>' not in m['body']
    assert 'ответ на тело' in m['body']

    m = load_email('msg-attachments-two-gmail.txt', 'koi8-r', parsed=True)
    assert m['meta']['files'] == [
        {
            'filename': '08.png',
            'image': True,
            'path': '2',
            'size': 553,
            'url': '/raw/17/2/08.png',
        },
        {
            'filename': '09.png',
            'image': True,
            'path': '3',
            'size': 520,
            'url': '/raw/17/3/09.png',
        }
    ]
    assert '<hr>' not in m['body']
    assert 'ответ на тело' in m['body']

    m = load_email('msg-attachments-two-yandex.txt', 'koi8-r', parsed=True)
    assert m['meta']['files'] == [
        {
            'filename': '49.png',
            'image': True,
            'path': '2',
            'size': 482,
            'url': '/raw/18/2/49.png',
        },
        {
            'filename': '50.png',
            'image': True,
            'path': '3',
            'size': 456,
            'url': '/raw/18/3/50.png',
        }
    ]
    assert 'ответ на тело' in m['body']

    m = load_email('msg-attachments-textfile.txt', 'koi8-r', parsed=True)
    assert m['meta']['files'] == [
        {
            'filename': 'Дополнение4.txt',
            'path': '2',
            'size': 11,
            'url': '/raw/19/2/Дополнение4.txt',
        }
    ]
    assert m['body'] == '<p>тест</p>'

    m = load_email('msg-rfc822.txt', parsed=True)
    assert m['meta']['files'] == [
        {
            'filename': 'unknown-2.eml',
            'path': '2',
            'size': 463,
            'url': '/raw/20/2/unknown-2.eml',
        }
    ]

    # test embeds
    m = load_email('msg-embeds-one-gmail.txt', parsed=True)
    assert m['meta']['files'] == [{
        'content-id': '<ii_jcrlk9sk0_16122eb711c529e8>',
        'filename': '50.png',
        'image': True,
        'path': '2',
        'size': 456,
        'url': '/raw/21/2/50.png',
    }]
    src = 'src="/raw/%s/2/50.png"' % m['meta']['origin_uid']
    assert src in m['body']


def test_non_latin_in_content_id(load_email):
    m = load_email('msg-attachments-rus-content-id.txt', 'utf-8', parsed=True)
    assert m['meta']['files'] == [{
        'content-id': '<черная точка.png>',
        'filename': 'черная-точка.png',
        'image': True,
        'path': '2',
        'size': 68,
        'url': '/raw/1/2/черная-точка.png'
    }]
