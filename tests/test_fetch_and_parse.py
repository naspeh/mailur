import email
import re

from mailur import local, gmail


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


def test_basic(clean_users, gm_client, some):
    lm = local.client()
    gmail.fetch_folder()
    local.parse()

    def gm_uidnext():
        res = lm.getmetadata(local.SRC, 'gmail/uidnext/all')
        assert res == [(b'Src (/private/gmail/uidnext/all {12}', some), b')']
        return some.value

    def mlr_uidnext():
        res = lm.getmetadata(local.ALL, 'uidnext')
        assert res == [(b'All (/private/uidnext {1}', some), b')']
        return some.value

    assert gm_uidnext().endswith(b',1')
    assert lm.getmetadata(local.ALL, 'uidnext') == [
        b'All (/private/uidnext NIL)'
    ]

    gm_client.add_emails()
    gmail.fetch_folder()
    local.parse()
    assert gm_uidnext().endswith(b',2')
    assert mlr_uidnext() == b'2'
    assert lm.select(local.SRC) == [b'1']
    assert lm.select(local.ALL) == [b'1']

    gm_client.add_emails([{'txt': '1'}, {'txt': '2'}])
    gmail.fetch_folder()
    local.parse()
    assert gm_uidnext().endswith(b',4')
    assert mlr_uidnext() == b'4'
    assert lm.select(local.SRC) == [b'3']
    assert lm.select(local.ALL) == [b'3']

    gmail.fetch_folder()
    local.parse('all')
    assert gm_uidnext().endswith(b',4')
    assert mlr_uidnext() == b'4'
    assert lm.select(local.SRC) == [b'3']
    assert lm.select(local.ALL) == [b'3']
    assert lm.status(local.ALL, '(UIDNEXT)') == [b'All (UIDNEXT 7)']


def get_latest(box=local.SRC, raw=False):
    return get_msgs(box, '*', raw=raw)[0]


def get_msgs(box=local.SRC, uids='1:*', raw=False):
    lm = local.client(box)
    res = lm.fetch(uids, '(flags body[])')
    return [(
        re.search('FLAGS \(([^)]*)\)', res[i][0].decode()).group(1),
        res[i][1] if raw else email.message_from_bytes(res[i][1])
    ) for i in range(0, len(res), 2)]


def test_fetched_msg(gm_client):
    gm_client.add_emails()
    gmail.fetch_folder('\\All')
    _, msg = get_latest()
    # headers
    sha256 = msg.get('X-SHA256')
    assert sha256 and re.match('<[a-z0-9]{64}>', sha256)
    uid = msg.get('X-GM-UID')
    assert uid and uid == '<101>'
    msgid = msg.get('X-GM-MSGID')
    assert msgid and msgid == '<10100>'
    thrid = msg.get('X-GM-THRID')
    assert thrid and thrid == '<10100>'

    lm = local.client()
    gm_client.add_emails([
        {'flags': r'\Flagged', 'labels': r'"\\Inbox" "\\Sent" label'}
    ])
    gmail.fetch_folder('\\All')
    flags, msg = get_latest()
    assert r'\Flagged \Recent #inbox #sent #t1' == flags
    assert local.get_tags(lm) == {'#t1': 'label'}

    gm_client.add_emails([{'labels': 'label "another label"'}])
    gmail.fetch_folder('\\All')
    flags, msg = get_latest()
    assert '\\Recent #t1 #t2' == flags
    assert local.get_tags(lm) == {'#t1': 'label', '#t2': 'another label'}

    gm_client.add_emails([
        {'labels': r'"\\Important" "\\Sent" "test(&BEIENQRBBEI-)"'}
    ])
    gmail.fetch_folder('\\All')
    flags, msg = get_latest()
    assert '\Recent #sent #important #t3' == flags
    assert local.get_tags(lm) == {
        '#t1': 'label',
        '#t2': 'another label',
        '#t3': 'test(&BEIENQRBBEI-)',
    }

    gm_client.add_emails([{}], box=local.SPAM)
    gmail.fetch_folder('\\Junk')
    assert len(get_msgs(local.SPAM)) == 1

    gm_client.add_emails([{}], box=local.TRASH)
    gmail.fetch_folder('\\Trash')
    assert len(get_msgs(local.TRASH)) == 1


def test_thrids(clean_users, gm_client):
    gm_client.add_emails([{}])
    gmail.fetch_folder()
    local.parse()
    msgs = get_msgs(local.ALL)
    assert ['#latest'] == [i[0] for i in msgs]
    gm_client.add_emails([{}])
    gmail.fetch_folder()
    local.parse()
    msgs = get_msgs(local.ALL)
    assert ['#latest', '#latest'] == [i[0] for i in msgs]

    gm_client.add_emails([{'in_reply_to': '<101@mlr>'}])
    gmail.fetch_folder()
    local.parse()
    msgs = get_msgs(local.ALL)
    assert ['', '#latest', '#latest'] == [i[0] for i in msgs]

    gm_client.add_emails([{'refs': '<101@mlr> <102@mlr>'}])
    gmail.fetch_folder()
    local.parse()
    msgs = get_msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i[0] for i in msgs]

    local.parse('all')
    msgs = get_msgs(local.ALL)
    assert ['', '', '', '#latest'] == [i[0] for i in msgs]


def test_parsed_msg(clean_users, gm_client, load_file):
    gm_client.add_emails([{'flags': '\\Flagged'}])
    gmail.fetch_folder()
    local.parse()
    flags, msg = get_latest(local.ALL)
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

    gmail.fetch_folder()
    local.parse()
    flags, msg = get_latest(local.ALL)
    assert msg['to'].startswith('primary discussion list')

    # should be decoding of headers during parsing
    gm_client.add_emails([
        {'raw': load_file('msg-header-with-encoding.txt')}
    ])

    gmail.fetch_folder()
    local.parse(batch=1)
    flags, msg = get_latest(local.ALL, raw=True)
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

    gmail.fetch_folder()
    local.parse(batch=1)
    flags, msg = get_latest(local.ALL, raw=True)
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
