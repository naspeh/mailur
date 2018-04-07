import re
from unittest.mock import call, patch

from mailur import gmail, local


@patch('mailur.imap.select')
def test_client(select, some):
    con = gmail.client()
    assert select.call_args == call(some, b'All', True)
    assert set(con.__dict__.keys()) == set(
        '_con idle logout list select select_tag status search fetch'
        .split()
    )

    con.select_tag('\\Junk')
    assert select.call_args == call(some, b'tags/Spam', True)

    con.select_tag('\\Trash')
    assert select.call_args == call(some, b'tags/Trash', True)

    con.select_tag('\\Drafts')
    assert select.call_args == call(some, b'tags/Drafts', True)

    with patch('mailur.imap.fn_time') as m:
        con.list()
        assert m.called


def test_credentials():
    name, pwd = 'test', 'test'
    gmail.save_credentials(name, pwd)
    assert gmail.get_credentials() == (name, pwd)

    name, pwd = 'test@test.com', 'test'
    gmail.save_credentials(name, pwd)
    assert gmail.get_credentials() == (name, pwd)


def test_fetch_and_parse(gm_client, some):
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
    assert gm_uidnext().endswith(b',2')
    assert mlr_uidnext() == b'2'
    assert lm.select(local.SRC) == [b'1']
    assert lm.select(local.ALL) == [b'1']

    gm_client.add_emails([{'txt': '1'}, {'txt': '2'}])
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


def test_origin_msg(gm_client, latest, login):
    gm_client.add_emails(parse=False)
    msg = latest(local.SRC)['body']
    # headers
    sha256 = msg.get('X-SHA256')
    assert sha256 and re.match('<[a-z0-9]{64}>', sha256)
    uid = msg.get('X-GM-UID')
    assert uid and uid == '<101>'
    msgid = msg.get('X-GM-MSGID')
    assert msgid and msgid == '<10100>'
    thrid = msg.get('X-GM-THRID')
    assert thrid and thrid == '<10100>'
    user = msg.get('X-GM-Login')
    assert user == '<%s>' % login.user2

    gm_client.add_emails([
        {'flags': r'\Flagged', 'labels': r'"\\Inbox" "\\Sent" label'}
    ], parse=False)
    flags = latest(local.SRC)['flags']
    assert r'\Flagged #inbox #sent label' == flags
    assert local.saved_tags() == {}

    gm_client.add_emails([{'labels': r'test/#-.,:;!?/'}], parse=False)
    flags = latest(local.SRC)['flags']
    assert r'test/#-.,:;!?/' == flags
    assert local.saved_tags() == {}

    gm_client.add_emails([
        {'labels': 'label "another label" (label)'}
    ], parse=False)
    flags = latest(local.SRC)['flags']
    assert 'label #12ea23fc #40602c03' == flags
    assert local.saved_tags() == {
        '#12ea23fc': {'name': 'another label'},
        '#40602c03': {'name': '(label)'},
    }

    # - "\Important" must be skiped
    # - flags must be transformed with imap-utf7
    gm_client.add_emails([
        {'labels': r'"\\Important" "\\Sent" "test(&BEIENQRBBEI-)"'}
    ], parse=False)
    flags = latest(local.SRC)['flags']
    assert '#sent #a058c658' == flags
    assert local.saved_tags() == {
        '#12ea23fc': {'name': 'another label'},
        '#40602c03': {'name': '(label)'},
        '#a058c658': {'name': 'test(тест)'},
    }

    gm_client.add_emails([{}], tag='\\Junk', parse=False)
    assert latest(local.SRC)['flags'] == '#spam'

    gm_client.add_emails([{}], tag='\\Trash', parse=False)
    assert latest(local.SRC)['flags'] == '#trash'

    gm_client.add_emails([{}], tag='\\Draft', parse=False)
    assert latest(local.SRC)['flags'] == '\\Draft'

    gm_client.add_emails([{}], tag='\\Inbox', fetch=False, parse=False)
    gmail.fetch(tag='\\Chats', box='INBOX')
    assert latest(local.SRC)['flags'] == '#chats'


def test_thrid(gm_client, msgs):
    gm_client.add_emails([
        {'labels': 'mlr/thrid mlr/thrid/1516806882952089676'},
        {'labels': 'mlr/thrid mlr/thrid/1516806882952089676'}
    ], parse=False)

    assert [i['flags'] for i in msgs(local.SRC)] == ['mlr/thrid', 'mlr/thrid']
    assert [i['body']['X-Thread-ID'] for i in msgs(local.SRC)] == [
        '<mlr/thrid/1516806882952089676@mailur.link>',
        '<mlr/thrid/1516806882952089676@mailur.link>'
    ]


def test_unique(gm_client, msgs):
    gm_client.add_emails([{}], parse=False)

    m = msgs(local.SRC)[-1]
    gid = m['body']['X-GM-MSGID']
    gm_client.add_emails([{'gid': int(gid.strip('<>'))}], parse=False)
    assert [i['body']['X-GM-THRID'] for i in msgs(local.SRC)] == [gid]
