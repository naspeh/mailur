from subprocess import check_output

from mailur import cli, local


def test_general(gm_client, login, msgs, patch, call):
    stdout = check_output('mlr -h', shell=True)
    assert b'Mailur CLI' in stdout

    gm_client.add_emails([{}, {}], fetch=False, parse=False)
    assert [i['uid'] for i in msgs(local.SRC)] == []
    assert [i['uid'] for i in msgs()] == []

    cli.main('%s remote --parse' % login.user1)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2']
    assert [i['uid'] for i in msgs()] == ['1', '2']

    with patch('mailur.cli.local') as m:
        cli.main('%s metadata' % login.user1)
        assert m.update_metadata.called

    cli.main('%s metadata' % login.user1)

    with patch('mailur.cli.remote.fetch_folder') as m:
        cli.main('%s remote' % login.user1)
        opts = {'batch': 1000, 'threads': 2}
        assert m.call_args_list == [
            call(tag='\\All', **opts),
            call(tag='\\Junk', **opts),
            call(tag='\\Trash', **opts),
        ]

        m.reset_mock()
        cli.main('%s remote --tag=\\All' % login.user1)
        assert m.call_args_list == [call(tag='\\All', **opts)]

        m.reset_mock()
        cli.main('%s remote --box=All' % login.user1)
        assert m.call_args_list == [call(box='All', **opts)]


def test_fetch_and_parse(gm_client, login, msgs, patch, raises):
    stdout = check_output('mlr %s parse' % login.user1, shell=True)
    assert b'## all parsed already' in stdout

    cli.main('%s remote' % login.user1)
    assert len(msgs(local.SRC)) == 0
    assert len(msgs()) == 0

    gm_client.add_emails([{}], fetch=False, parse=False)
    cli.main('%s remote' % login.user1)
    assert len(msgs(local.SRC)) == 1
    assert len(msgs()) == 0

    cli.main('%s parse' % login.user1)
    assert len(msgs(local.SRC)) == 1
    assert len(msgs()) == 1

    gm_client.add_emails([{}], fetch=False, parse=False)
    cli.main('%s remote --parse' % login.user1)
    assert len(msgs(local.SRC)) == 2
    assert len(msgs()) == 2

    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2']
    assert [i['uid'] for i in msgs()] == ['1', '2']
    cli.main('%s parse all' % login.user1)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2']
    assert [i['uid'] for i in msgs()] == ['3', '4']

    with patch('mailur.remote.fetch') as m, raises(SystemExit):
        m.side_effect = SystemExit
        cli.main('%s remote --parse' % login.user1)
    assert len(msgs(local.SRC)) == 2
    assert len(msgs()) == 2
