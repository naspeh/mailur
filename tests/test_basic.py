import email
import re
from unittest.mock import patch, call, ANY

from mailur import imap, parse


def test_binary_msg():
    assert parse.binary_msg('Ответ: 42').as_bytes() == '\r\n'.join([
        'MIME-Version: 1.0',
        'Content-Transfer-Encoding: binary',
        'Content-Type: text/plain; charset="utf-8"',
        '',
        'Ответ: 42'
    ]).encode()

    assert parse.binary_msg('Ответ: 42').as_string() == '\r\n'.join([
        'MIME-Version: 1.0',
        'Content-Transfer-Encoding: base64',
        'Content-Type: text/plain; charset="utf-8"',
        '',
        '0J7RgtCy0LXRgjogNDI=\r\n'
    ])


def test_thread_response():
    assert imap.parse_thread('(1)(2 3)') == [['1'], ['2', '3']]
    assert imap.parse_thread('(11)(21 31)') == [['11'], ['21', '31']]
    assert imap.parse_thread('(1)(2 3 (4 5))') == [['1'], '2 3 4 5'.split()]
    assert imap.parse_thread('(130 131 (132 133 134 (138)(139)(140)))') == [
        '130 131 132 133 134 138 139 140'.split()
    ]
    assert imap.parse_thread(b'(1)(2)(3)') == [['1'], ['2'], ['3']]


@patch('mailur.imap.select')
def test_basic_gmail(select):
    gm = imap.Gmail()
    assert select.call_args == call(ANY, b'All', True)

    gm.select_tag('\\Junk')
    assert select.call_args == call(ANY, b'V/Spam', True)

    gm.select_tag('\\Trash')
    assert select.call_args == call(ANY, b'V/Trash', True)


def test_fetch_and_parse(clean_users, gmail, some):
    lm = imap.Local()
    parse.fetch_folder()
    parse.parse_folder()

    def gmail_uidnext():
        res = lm.getmetadata(lm.ALL, 'gmail/uidnext/all')
        assert res == [(b'All (/private/gmail/uidnext/all {12}', some), b')']
        return some.value

    def mlr_uidnext():
        res = lm.getmetadata(lm.PARSED, 'uidnext')
        assert res == [(b'Parsed (/private/uidnext {1}', some), b')']
        return some.value

    assert gmail_uidnext().endswith(b',1')
    assert lm.getmetadata(lm.PARSED, 'uidnext') == [
        b'Parsed (/private/uidnext NIL)'
    ]

    gmail.add_emails()
    parse.fetch_folder()
    parse.parse_folder()
    assert gmail_uidnext().endswith(b',2')
    assert mlr_uidnext() == b'2'
    assert lm.select(lm.ALL) == [b'1']
    assert lm.select(lm.PARSED) == [b'1']

    gmail.add_emails([{'txt': '1'}, {'txt': '2'}])
    parse.fetch_folder()
    parse.parse_folder()
    assert gmail_uidnext().endswith(b',4')
    assert mlr_uidnext() == b'4'
    assert lm.select(lm.ALL) == [b'3']
    assert lm.select(lm.PARSED) == [b'3']

    parse.fetch_folder()
    parse.parse_folder('all')
    assert gmail_uidnext().endswith(b',4')
    assert mlr_uidnext() == b'4'
    assert lm.select(lm.ALL) == [b'3']
    assert lm.select(lm.PARSED) == [b'3']
    assert lm.status(lm.PARSED, '(UIDNEXT)') == [b'Parsed (UIDNEXT 7)']
    assert lm.getmetadata(lm.PARSED, 'uidmap') == [
        (b'Parsed (/private/uidmap {30}', b'{"4": "1", "5": "2", "6": "3"}'),
        b')'
    ]
    assert parse.parsed_uids(lm, [b'1']) == {b'4': b'1'}
    assert parse.parsed_uids(lm) == {b'4': b'1', b'5': b'2', b'6': b'3'}


def get_latest(box='All'):
    lm = imap.Local(box)
    res = lm.fetch('*', '(flags body[])')
    msg = res[0][1]
    print(msg.decode())
    msg = email.message_from_bytes(msg)
    line = res[0][0].decode()
    print(line)
    flags = re.search('FLAGS \(([^)]*)\)', line).group(1)
    return flags, msg


def get_msgs(box='All', uids='1:*'):
    lm = imap.Local(box)
    res = lm.fetch(uids, '(flags body[])')
    return [(
        re.search('FLAGS \(([^)]*)\)', res[i][0].decode()).group(1),
        email.message_from_bytes(res[i][1])
    ) for i in range(0, len(res), 2)]


def test_fetched_msg(gmail):
    gmail.add_emails()
    parse.fetch_folder('\\All')
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

    gmail.add_emails([
        {'flags': '\\Flagged', 'labels': '"\\\\Inbox" "\\\\Sent" test'}
    ])
    parse.fetch_folder('\\All')
    flags, msg = get_latest()
    assert '\\Flagged' in flags
    assert '$Inbox' in flags
    assert '$Sent' in flags
    assert 'test' not in flags

    gmail.add_emails([{}])
    parse.fetch_folder('\\Junk')
    flags, msg = get_latest()
    assert '$Spam' in flags

    gmail.add_emails([{}])
    parse.fetch_folder('\\Trash')
    flags, msg = get_latest()
    assert '$Trash' in flags


def test_thrids(clean_users, gmail):
    gmail.add_emails([{}])
    parse.fetch_folder()
    parse.parse_folder()
    flags, msg = get_latest('Parsed')
    assert 'T:1' == flags
    gmail.add_emails([{}])
    parse.fetch_folder()
    parse.parse_folder()
    flags, msg = get_latest('Parsed')
    assert 'T:2' == flags

    gmail.add_emails([{'in_reply_to': '<101@mlr>'}])
    parse.fetch_folder()
    parse.parse_folder()
    msgs = get_msgs('Parsed')
    assert ['T:3', 'T:2', 'T:3'] == [i[0] for i in msgs]

    gmail.add_emails([{'refs': '<101@mlr> <102@mlr>'}])
    parse.fetch_folder()
    parse.parse_folder()
    msgs = get_msgs('Parsed')
    assert ['T:4', 'T:4', 'T:4', 'T:4'] == [i[0] for i in msgs]

    parse.parse_folder('all')
    msgs = get_msgs('Parsed')
    assert ['T:4', 'T:4', 'T:4', 'T:4'] == [i[0] for i in msgs]


def test_parsed_msg(gmail):
    gmail.add_emails([{'flags': '\\Flagged'}])
    parse.fetch_folder()
    parse.parse_folder()
    flags, msg = get_latest('Parsed')
    assert 'X-UID' in msg
    assert re.match('<\d+>', msg['X-UID'])
    assert '\\Flagged' in flags
