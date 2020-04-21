from gevent import sleep, spawn

from mailur import cli, local, remote


def test_local(gm_client, msgs):
    gm_client.add_emails([{}] * 5)
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == [''] * 5

    con_src = local.client(local.SRC, readonly=False)
    con_all = local.client(local.ALL, readonly=False)

    con_src.store('1:*', '+FLAGS', '#1')
    con_all.store('1:*', '+FLAGS', '#2')
    local.sync_flags_to_all()
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1'] * 5
    assert [i['flags'] for i in msgs()] == ['#1'] * 5

    con_src.store('1,2', '+FLAGS', '#2')
    con_all.store('2,3', '+FLAGS', '#3')
    local.sync_flags_to_all()
    assert [i['flags'] for i in msgs(local.SRC)] == [
        '#1 #2', '#1 #2', '#1', '#1', '#1'
    ]
    assert [i['flags'] for i in msgs()] == [
        '#2 #1', '#2 #1', '#1', '#1', '#1'
    ]

    con_all.store('1:*', '-FLAGS', '#1 #2')
    con_all.store('1:*', '+FLAGS', '#3')
    local.sync_flags_to_src()
    assert [i['flags'] for i in msgs(local.SRC)] == ['#3'] * 5
    assert [i['flags'] for i in msgs()] == ['#3'] * 5

    con_src.store('1,2', '+FLAGS', '#2')
    con_all.store('2,3', '+FLAGS', '#4')
    local.sync_flags_to_src()
    assert [i['flags'] for i in msgs(local.SRC)] == [
        '#3', '#3 #4', '#3 #4', '#3', '#3'
    ]
    assert [i['flags'] for i in msgs()] == [
        '#3', '#3 #4', '#3 #4', '#3', '#3'
    ]

    con_all.store('1:*', '-FLAGS', '#3 #4')
    local.sync_flags_to_src()
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == [''] * 5

    local.sync_flags_to_src()
    con_all.store('1:*', '+FLAGS', '#err')
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == ['#err'] * 5

    con_src.store('1:*', '+FLAGS', '#err')
    con_all.store('1:*', '-FLAGS', '#err')
    local.sync_flags_to_all()
    assert [i['flags'] for i in msgs(local.SRC)] == ['#err'] * 5
    assert [i['flags'] for i in msgs()] == [''] * 5

    con_src.store('1:*', '-FLAGS', '#err')
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == [''] * 5

    # idle
    spawn(local.sync_flags)
    sleep(1)

    con_src.store('1:*', '+FLAGS', '#1')
    for i in range(2, 6):
        con_src.store('%s' % i, '+FLAGS', '#%s' % i)
    sleep(1)
    assert [i['flags'] for i in msgs(local.SRC)] == [
        '#1', '#1 #2', '#1 #3', '#1 #4', '#1 #5'
    ]
    assert [i['flags'] for i in msgs()] == [
        '#1', '#2 #1', '#1 #3', '#1 #4', '#1 #5'
    ]


def test_cli_idle_gmail(gm_client, msgs, login, patch):
    actions = []

    def fetch(con, uids, fields):
        responces = getattr(gm_client, 'fetch', None)
        if 'CHANGEDSINCE' in fields:
            index = fields.split()[-1]
            if index == '5)':
                return ('OK', [
                    b'4 (X-GM-MSGID 10400 X-GM-LABELS ("\\Inbox" "\\Starred") '
                    b'FLAGS (\\Seen) UID 104 MODSEQ (427368))'
                ])
            return ('OK', [])
        elif responces:
            return responces.pop()
        elif 'X-GM-LABELS' in fields:
            if con.current_box != local.SRC:
                return ('OK', [
                    b'1 (X-GM-MSGID 10100 X-GM-LABELS () '
                    b'FLAGS (\\Seen) UID 101 MODSEQ (427368))'
                ])
            return ('OK', [
                (
                    b'2 (X-GM-MSGID 10200 X-GM-LABELS () '
                    b'FLAGS (\\Seen) UID 102 MODSEQ (427368))'
                ),
                (
                    b'3 (X-GM-MSGID 10300 X-GM-LABELS () '
                    b'FLAGS (\\Seen) UID 103 MODSEQ (427368))'
                ),
                (
                    b'4 (X-GM-MSGID 10400 X-GM-LABELS () '
                    b'FLAGS (\\Seen) UID 104 MODSEQ (427368))'
                ),
                (
                    b'6 (X-GM-MSGID 10600 X-GM-LABELS (\\Draft) '
                    b'FLAGS (\\Seen) UID 106 MODSEQ (427368))'
                ),
            ])
        return con._uid('FETCH', uids, fields)

    def search(con, charset, *criteria):
        if 'X-GM-MSGID' in criteria[0]:
            uid = int(criteria[0].split()[-1]) // 100
            return ('OK', [(b'%d' % uid)])
        return con._uid('SEARCH', charset, *criteria)

    def store(con, uids, cmd, flags):
        if 'X-GM-LABELS' in cmd:
            actions.append((uids, cmd, sorted(flags.split())))
            return ('OK', [])
        return con._uid('STORE', uids, cmd, flags)

    gm_client.fake_fetch = fetch
    gm_client.fake_search = search
    gm_client.fake_store = store

    spawn(lambda: cli.main('sync %s --timeout=300' % login.user1))
    sleep(5)

    gm_client.add_emails([{}] * 4, fetch=False, parse=False)
    sleep(3)
    assert len(msgs(local.SRC)) == 4
    assert len(msgs()) == 4

    local.parse('all')

    gm_client.add_emails([{}], fetch=False, parse=False)
    sleep(3)
    assert len(msgs(local.SRC)) == 5
    assert len(msgs()) == 5
    expected_flags = ['', '', '', '\\Flagged \\Seen #inbox', '']
    assert [i['flags'] for i in msgs(local.SRC)] == expected_flags
    assert [i['flags'] for i in msgs()] == expected_flags

    con_src = local.client(local.SRC, readonly=False)
    con_src.store('1:*', '+FLAGS', '#1')
    sleep(3)
    expected_flags = [(f + ' #1').strip() for f in expected_flags]
    assert [i['flags'] for i in msgs(local.SRC)] == expected_flags
    assert [i['flags'] for i in msgs()] == expected_flags

    assert actions == [
        ('101', '-X-GM-LABELS', ['\\Junk']),
        ('101', '+X-GM-LABELS', ['\\Inbox']),  # move to \\All
        ('101', '-X-GM-LABELS', ['\\Trash']),
        ('101', '+X-GM-LABELS', ['\\Inbox']),  # move to \\All
        ('104', '+X-GM-LABELS', ['\\Inbox', '\\Starred']),
        ('104', '+X-GM-LABELS', ['\\Inbox', '\\Starred']),
        ('101', '-X-GM-LABELS', ['\\Junk']),
        ('101', '+X-GM-LABELS', ['\\Inbox']),  # move to \\All
        ('101', '-X-GM-LABELS', ['\\Trash']),
        ('101', '+X-GM-LABELS', ['\\Inbox']),  # move to \\All
    ]

    actions.clear()
    con_src = local.client(local.SRC, readonly=False)
    con_src.store('2', '+FLAGS', '#inbox')
    sleep(3)
    con_src.store('2', '+FLAGS', '#trash')
    sleep(3)
    expected_flags[1] = '#inbox #1 #trash'
    assert [i['flags'] for i in msgs(local.SRC)] == expected_flags
    assert [i['flags'] for i in msgs()] == expected_flags
    assert actions == [
        ('102', '+X-GM-LABELS', ['\\Inbox']),
        ('102', '-X-GM-LABELS', ['\\Inbox']),
        ('102', '+X-GM-LABELS', ['\\Trash']),
    ]


def test_cli_idle_general_imap(gm_client, msgs, login, patch):
    remote.data_account({
        'username': 'test@test.com',
        'password': 'test',
        'imap_host': 'imap.test.com',
        'smtp_host': 'smtp.test.com'
    })
    assert remote.get_folders() == [{'tag': '\\All'}]

    spawn(lambda: cli.main('sync %s --timeout=300' % login.user1))
    sleep(2)

    gm_client.add_emails([{}] * 4, fetch=False, parse=False)
    gm_client.fetch = [gm_client.fetch[0]]
    sleep(2)
    assert len(msgs(local.SRC)) == 4
    assert len(msgs()) == 4

    gm_client.list = []
    xlist = [('OK', [b'(\\HasNoChildren) "/" INBOX'])] * 10
    with patch.object(gm_client, 'list', xlist):
        spawn(lambda: cli.main('sync %s --timeout=300' % login.user1))
        sleep(2)

        gm_client.add_emails([{'flags': '#inbox'}], fetch=False, parse=False)
        gm_client.fetch = [gm_client.fetch[0]]
        sleep(2)
        assert len(msgs(local.SRC)) == 5
        assert len(msgs()) == 5
        assert len(msgs('INBOX')) == 1


def test_cli_all_flags(gm_client, msgs, login):
    gm_client.add_emails([{}] * 5)
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == [''] * 5

    con_src = local.client(local.SRC, readonly=False)
    con_all = local.client(local.ALL, readonly=False)

    con_src.store('1:*', '+FLAGS', '#1')
    con_all.store('1:*', '+FLAGS', '#2')
    cli.main('sync-flags %s' % login.user1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1'] * 5
    assert [i['flags'] for i in msgs()] == ['#1'] * 5

    con_src.store('1:*', '+FLAGS', '#2')
    con_all.store('1:*', '+FLAGS', '#3')
    cli.main('sync-flags %s --reverse' % login.user1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1 #3'] * 5
    assert [i['flags'] for i in msgs()] == ['#1 #3'] * 5


def test_clean_flags(gm_client, msgs, login):
    gm_client.add_emails([{}] * 2)
    local.link_threads(['1', '2'])

    assert [i['flags'] for i in msgs(local.SRC)] == ['', '']
    assert [i['flags'] for i in msgs()] == ['', '']

    con_src = local.client(local.SRC, readonly=False)
    con_all = local.client(local.ALL, readonly=False)

    con_src.store('1', '+FLAGS', '#tag1')
    con_src.store('2', '+FLAGS', '#tag2 #tag3')
    con_all.store('1', '+FLAGS', '#tag1 #tag3')
    con_all.store('2', '+FLAGS', '#tag2')
    assert [i['flags'] for i in msgs(local.SRC)] == ['#tag1', '#tag2 #tag3']
    assert [i['flags'] for i in msgs()] == ['#tag1 #tag3', '#tag2']

    cli.main('clean-flags %s #tag1' % login.user1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['', '#tag2 #tag3']
    assert [i['flags'] for i in msgs()] == ['#tag3', '#tag2']

    cli.main('clean-flags %s #tag2 #tag3' % login.user1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['', '']
    assert [i['flags'] for i in msgs()] == ['', '']
