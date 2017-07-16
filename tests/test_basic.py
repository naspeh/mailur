import email
import re

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


def test_basic_gmail():
    gm = imap.Gmail()
    assert gm.current_folder == 'All'

    gm = imap.Gmail('\\Junk')
    assert gm.current_folder == 'V/Spam'

    gm = imap.Gmail('\\Trash')
    assert gm.current_folder == 'V/Trash'


def test_fetch_and_parse(clean_users, gmail, some):
    gm = imap.Gmail()
    lm = imap.Local()
    parse.fetch_folder()
    parse.parse_folder()

    def gmail_uidnext():
        res = lm.getmetadata('gmail/uidnext/all')
        assert res == [(b'All (/private/gmail/uidnext/all {12}', some), b')']
        return some.value

    def mlr_uidnext():
        res = lm.getmetadata('mlr/uidnext')
        assert res == [(b'All (/private/mlr/uidnext {1}', some), b')']
        return some.value

    assert gmail_uidnext().endswith(b',1')
    assert lm.getmetadata('mlr/uidnext') == [b'All (/private/mlr/uidnext NIL)']

    gmail.add_emails(gm)
    parse.fetch_folder()
    parse.parse_folder()
    assert gmail_uidnext().endswith(b',2')
    assert mlr_uidnext() == b'2'
    assert lm.select(lm.ALL) == [b'1']
    assert lm.select(lm.PARSED) == [b'1']

    gmail.add_emails(gm, [{'txt': '1'}, {'txt': '2'}])
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


def test_fetched_msg(clean_users, gmail):
    def get_latest():
        parse.fetch_folder()

        lm = imap.Local()
        res = lm.fetch('*', '(flags body[])')
        msg = res[0][1]
        print(msg.decode())
        msg = email.message_from_bytes(msg)
        line = res[0][0].decode()
        print(line)
        flags = re.search('FLAGS \(([^)]*)\)', line).group(1)
        return flags, msg

    gm = imap.Gmail()
    gmail.add_emails(gm)
    _, msg = get_latest()
    # headers
    assert 'X-SHA1' in msg
    msgid = msg.get('X-GM-MSGID')
    assert msgid and msgid == '10100'
    thrid = msg.get('X-GM-THRID')
    assert thrid and thrid == '10100'
    uid = msg.get('X-GM-UID')
    assert uid and uid == '101'

    gmail.add_emails(gm, [{'flags': '\\Flagged \\Inbox \\Junk'}])
    flags, msg = get_latest()
    assert '\\Flagged' in flags
    assert '$Inbox' in flags
    assert '$Junk' in flags


def test_parsed_msg(gmail):
    gm = imap.Gmail()

    gmail.add_emails(gm)
    parse.fetch_folder()
    parse.parse_folder()

    lm = imap.Local()
    lm.select(lm.PARSED)
    res = lm.fetch('*', 'body[]')
    msg = email.message_from_bytes(res[0][1])
    print(msg.as_string())

    assert 'X-UID' in msg
    assert re.match('<\d+>', msg['X-UID'])
