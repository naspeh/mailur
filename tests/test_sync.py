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


def test_cli_idle(gm_client, msgs, login, patch):
    spawn(lambda: cli.main('sync %s --timeout=300' % login.user1))
    sleep(2)

    gm_client.add_emails([{}] * 4, fetch=False, parse=False)
    sleep(2)
    assert len(msgs(local.SRC)) == 4
    assert len(msgs()) == 4

    local.parse('all')

    gm_client.add_emails([{}], fetch=False, parse=False)
    sleep(2)
    assert len(msgs(local.SRC)) == 5
    assert len(msgs()) == 5

    con_src = local.client(local.SRC, readonly=False)
    con_src.store('1:*', '+FLAGS', '#1')
    sleep(2)
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1'] * 5
    assert [i['flags'] for i in msgs()] == ['#1'] * 5


def test_cli_idle2(gm_client, msgs, login, patch):
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
