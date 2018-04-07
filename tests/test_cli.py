from subprocess import check_output

from mailur import cli, local


def test_general(gm_client, login, msgs, patch):
    stdout = check_output('mlr -h', shell=True)
    assert b'Mailur CLI' in stdout

    stdout = check_output('mlr icons', shell=True)
    assert b'assets/font/icons.less updated\n' in stdout

    gm_client.add_emails([{}, {}], fetch=False, parse=False)
    assert [i['uid'] for i in msgs(local.SRC)] == []
    assert [i['uid'] for i in msgs()] == []

    cli.main('gmail %s --parse' % login.user1)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2']
    assert [i['uid'] for i in msgs()] == ['1', '2']
    local.link_threads(['1', '2'])

    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2', '3']
    assert [i['uid'] for i in msgs()] == ['1', '2', '3']
    cli.main('update-links %s' % login.user1)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2', '4']
    assert [i['uid'] for i in msgs()] == ['1', '2', '4']

    with patch('mailur.cli.local') as m:
        cli.main('update-metadata %s' % login.user1)
        assert m.save_addrs.called
        assert m.save_msgids.called
        assert m.save_uid_pairs.called


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
