import re

from mailur import local, remote


def test_client(some, patch, call):
    with patch('mailur.imap.select') as m:
        con = remote.client(tag='\\All')
        assert m.call_args == call(some, b'mlr', True)

        assert set(con.__dict__.keys()) == set(
            '_con logout list select select_tag status search '
            'fetch idle copy enable'
            .split()
        )

        con.select_tag('\\Junk')
        assert m.call_args == call(some, b'mlr/All', True)

        con.select_tag('\\Trash')
        assert m.call_args == call(some, b'mlr/All', True)

        con.select_tag('\\Draft')
        assert m.call_args == call(some, b'mlr/All', True)

    with patch('mailur.imap.fn_time') as m:
        con.list()
        assert m.called


def test_account(gm_client):
    params = {
        'username': 'test',
        'password': 'test',
        'imap_host': 'imap.gmail.com',
        'smtp_host': 'smtp.gmail.com'
    }
    remote.data_account(params.copy())
    assert remote.data_account.get() == dict(
        params, gmail=True, smtp_port=465, imap_port=993,
    )

    params = {
        'username': 'test@test.com',
        'password': 'test',
        'imap_host': 'imap.test.com',
        'smtp_host': 'smtp.test.com'
    }
    remote.data_account(params.copy())
    assert remote.data_account.get() == dict(
        params, smtp_port=465, imap_port=993,
    )

    gm_client.list = [('OK', [
        b'(\\HasNoChildren \\All) "/" mlr/All',
    ])]
    assert remote.get_folders() == [{'tag': '\\All'}]

    gm_client.list = [('OK', [
        b'(\\HasNoChildren) "/" INBOX',
    ])]
    assert remote.get_folders() == [{'box': 'INBOX', 'tag': '\\Inbox'}]


def test_fetch_and_parse(gm_client, some, raises):
    lm = local.client()
    remote.fetch()
    local.parse()

    def gm_uidnext():
        account = remote.data_account.get()
        key = ':'.join((account['imap_host'], account['username'], '\\All'))
        res = remote.data_uidnext.key(key)
        assert res
        return res[1]

    def mlr_uidnext():
        return local.data_uidnext.get()

    assert gm_uidnext() == 1
    assert mlr_uidnext() is None

    gm_client.add_emails()
    assert gm_uidnext() == 2
    assert mlr_uidnext() == 2
    assert lm.select(local.SRC) == [b'1']
    assert lm.select(local.ALL) == [b'1']

    gm_client.add_emails([{'txt': '1'}, {'txt': '2'}])
    assert gm_uidnext() == 4
    assert mlr_uidnext() == 4
    assert lm.select(local.SRC) == [b'3']
    assert lm.select(local.ALL) == [b'3']

    remote.fetch()
    local.parse('all')
    assert gm_uidnext() == 4
    assert mlr_uidnext() == 4
    assert lm.select(local.SRC) == [b'3']
    assert lm.select(local.ALL) == [b'3']
    assert lm.status(local.ALL, '(UIDNEXT)') == [b'mlr/All (UIDNEXT 7)']


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
    assert user == '<%s*root>' % login.user2

    gm_client.add_emails([
        {'flags': r'\Flagged', 'labels': r'"\\Inbox" "\\Sent" label'}
    ], parse=False)
    flags = latest(local.SRC)['flags']
    assert r'\Flagged #inbox #sent label' == flags
    assert local.data_tags.get() == {}

    gm_client.add_emails([{'labels': r'test/#-.,:;!?/'}], parse=False)
    flags = latest(local.SRC)['flags']
    assert r'test/#-.,:;!?/' == flags
    assert local.data_tags.get() == {}

    gm_client.add_emails([
        {'labels': 'label "another label" (label)'}
    ], parse=False)
    flags = latest(local.SRC)['flags']
    assert 'label #12ea23fc #40602c03' == flags
    assert local.data_tags.get() == {
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
    assert local.data_tags.get() == {
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
    remote.fetch(tag='\\Chats', box='mlr')
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
