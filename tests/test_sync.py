from gevent import sleep, spawn

from mailur import cli, local


def test_local(gm_client, msgs):
    gm_client.add_emails([{}] * 5)
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == ['#latest'] * 5

    con_src = local.client(local.SRC, readonly=False)
    con_all = local.client(local.ALL, readonly=False)

    con_src.store('1:*', '+FLAGS', '#1')
    con_all.store('1:*', '+FLAGS', '#2')
    local.sync_flags_to_all()
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1'] * 5
    assert [i['flags'] for i in msgs()] == ['#latest #1'] * 5

    con_src.store('1,2', '+FLAGS', '#2')
    con_all.store('2,3', '+FLAGS', '#3')
    local.sync_flags_to_all()
    assert [i['flags'] for i in msgs(local.SRC)] == [
        '#1 #2', '#1 #2', '#1', '#1', '#1'
    ]
    assert [i['flags'] for i in msgs()] == [
        '#latest #2 #1', '#latest #2 #1', '#latest #1',
        '#latest #1', '#latest #1'
    ]

    con_all.store('1:*', '-FLAGS', '#1 #2')
    con_all.store('1:*', '+FLAGS', '#3')
    local.sync_flags_to_src()
    assert [i['flags'] for i in msgs(local.SRC)] == ['#3'] * 5
    assert [i['flags'] for i in msgs()] == ['#latest #3'] * 5

    con_src.store('1,2', '+FLAGS', '#2')
    con_all.store('2,3', '+FLAGS', '#4')
    local.sync_flags_to_src()
    assert [i['flags'] for i in msgs(local.SRC)] == [
        '#3', '#3 #4', '#3 #4', '#3', '#3'
    ]
    assert [i['flags'] for i in msgs()] == [
        '#latest #3', '#latest #3 #4', '#latest #3 #4',
        '#latest #3', '#latest #3'
    ]

    con_all.store('1:*', '-FLAGS', '#3 #4')
    local.sync_flags_to_src()
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == ['#latest'] * 5

    local.sync_flags_to_src()
    con_all.store('1:*', '+FLAGS', '#err #dup')
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == ['#latest #err #dup'] * 5

    con_src.store('1:*', '+FLAGS', '#latest #err #dup')
    con_all.store('1:*', '-FLAGS', '#err #dup')
    local.sync_flags_to_all()
    assert [i['flags'] for i in msgs(local.SRC)] == ['#latest #err #dup'] * 5
    assert [i['flags'] for i in msgs()] == ['#latest'] * 5

    con_src.store('1:*', '-FLAGS', '#latest #err #dup')
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == ['#latest'] * 5

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
        '#latest #1', '#latest #2 #1', '#latest #1 #3',
        '#latest #1 #4', '#latest #1 #5'
    ]


def test_cli_idle(gm_client, msgs, login, patch):
    with patch('mailur.gmail.get_credentials') as m:
        m.return_value = login.user2, 'user'
        spawn(lambda: cli.main('sync %s --timeout=300' % login.user1))
        sleep(3)

    gm_client.add_emails([{}] * 4, fetch=False, parse=False)
    sleep(1)
    assert len(msgs(local.SRC)) == 4
    assert len(msgs()) == 4

    local.parse('all')

    gm_client.add_emails([{}], fetch=False, parse=False)
    sleep(1)
    assert len(msgs(local.SRC)) == 5
    assert len(msgs()) == 5

    con_src = local.client(local.SRC, readonly=False)
    con_src.store('1:*', '+FLAGS', '#1')
    sleep(1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1'] * 5
    assert [i['flags'] for i in msgs()] == ['#latest #1'] * 5


def test_cli_all_flags(gm_client, msgs, login):
    gm_client.add_emails([{}] * 5)
    assert [i['flags'] for i in msgs(local.SRC)] == [''] * 5
    assert [i['flags'] for i in msgs()] == ['#latest'] * 5

    con_src = local.client(local.SRC, readonly=False)
    con_all = local.client(local.ALL, readonly=False)

    con_src.store('1:*', '+FLAGS', '#1')
    con_all.store('1:*', '+FLAGS', '#2')
    cli.main('sync-flags %s' % login.user1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1'] * 5
    assert [i['flags'] for i in msgs()] == ['#latest #1'] * 5

    con_src.store('1:*', '+FLAGS', '#2')
    con_all.store('1:*', '+FLAGS', '#3')
    cli.main('sync-flags %s --reverse' % login.user1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1 #3'] * 5
    assert [i['flags'] for i in msgs()] == ['#latest #1 #3'] * 5


def test_clean_flags(gm_client, msgs, login):
    gm_client.add_emails([{}] * 2)
    local.link_threads(['1', '2'])

    assert [i['flags'] for i in msgs(local.SRC)] == ['', '', '\\Seen #link']
    assert [i['flags'] for i in msgs()] == ['', '#latest', '\\Seen #link']

    con_src = local.client(local.SRC, readonly=False)
    con_all = local.client(local.ALL, readonly=False)

    con_src.store('3', '-FLAGS', '#link \\Seen')
    con_src.store('1', '+FLAGS', '#latest')
    con_src.store('2', '+FLAGS', '#dup')
    con_all.store('3', '-FLAGS', '#link \\Seen')
    con_all.store('2', '-FLAGS', '#latest')
    assert [i['flags'] for i in msgs(local.SRC)] == ['#latest', '#dup', '']
    assert [i['flags'] for i in msgs()] == ['', '', '']
    local.clean_flags()
    assert [i['flags'] for i in msgs(local.SRC)] == ['', '', '\\Seen #link']
    assert [i['flags'] for i in msgs()] == ['', '#latest', '\\Seen #link']

    con_src.store('3', '-FLAGS', '#link \\Seen')
    con_src.store('2', '+FLAGS', '#err')
    con_all.store('3', '-FLAGS', '#link \\Seen')
    con_all.store('2', '-FLAGS', '#latest')
    assert [i['flags'] for i in msgs(local.SRC)] == ['', '#err', '']
    assert [i['flags'] for i in msgs()] == ['', '', '']
    cli.main('clean-flags %s' % login.user1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['', '', '\\Seen #link']
    assert [i['flags'] for i in msgs()] == ['', '#latest', '\\Seen #link']
