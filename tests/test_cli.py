from subprocess import check_output

from gevent import sleep, spawn

from mailur import cli, local


def test_general():
    stdout = check_output('mlr -h', shell=True)
    assert b'Mailur CLI' in stdout

    stdout = check_output('mlr icons', shell=True)
    assert b'assets/font/icons.less updated\n' in stdout


def test_fetch_and_parse(gm_client, login, msgs, patch, raises):
    stdout = check_output('mlr parse %s' % login.user1, shell=True)
    assert b'## all parsed already' in stdout

    cli.main('gmail %s' % login.user1)
    assert len(msgs(local.SRC)) == 0
    assert len(msgs()) == 0

    gm_client.add_emails([{}], fetch=False, parse=False)
    cli.main('gmail %s' % login.user1)
    assert len(msgs(local.SRC)) == 1
    assert len(msgs()) == 0

    cli.main('parse %s' % login.user1)
    assert len(msgs(local.SRC)) == 1
    assert len(msgs()) == 1

    gm_client.add_emails([{}], fetch=False, parse=False)
    cli.main('gmail %s --parse' % login.user1)
    assert len(msgs(local.SRC)) == 2
    assert len(msgs()) == 2

    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2']
    assert [i['uid'] for i in msgs()] == ['1', '2']
    cli.main('parse %s all' % login.user1)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2']
    assert [i['uid'] for i in msgs()] == ['3', '4']

    with patch('mailur.gmail.fetch') as m, raises(SystemExit):
        m.side_effect = SystemExit
        cli.main('gmail %s --parse' % login.user1)
    assert len(msgs(local.SRC)) == 2
    assert len(msgs()) == 2


def test_sync_idle(gm_client, msgs, login, patch):
    with patch('mailur.gmail.get_credentials') as m:
        m.return_value = login.user2, 'user'
        spawn(lambda: cli.main('sync %s --gm-timeout=300' % login.user1))
        sleep(1)

    gm_client.add_emails([{}] * 4, fetch=False, parse=False)
    sleep(1)
    assert len(msgs(local.SRC)) == 4
    assert len(msgs()) == 4

    local.parse('all')

    gm_client.add_emails([{}], fetch=False, parse=False)
    sleep(2)
    assert len(msgs(local.SRC)) == 5
    assert len(msgs()) == 5

    con_src = local.client(local.SRC, readonly=False)
    con_src.store('1:*', '+FLAGS', '#1')
    sleep(1)
    assert [i['flags'] for i in msgs(local.SRC)] == ['#1'] * 5
    assert [i['flags'] for i in msgs()] == ['#latest #1'] * 5


def test_sync_flags(gm_client, msgs, login):
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
