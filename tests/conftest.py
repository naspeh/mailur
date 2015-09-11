from unittest.mock import patch

from pytest import fixture

from mailur import Env


@fixture
def env():
    '''Test Environment'''
    with patch.object(Env, 'db_connect'):
        return Env('test.user', conf={
            'pg_username': '',
            'pg_password': '',
            'google_id': '',
            'google_secret': '',
            'cookie_secret': 'secret',
            'path_attachments': '/tmp/attachments'
        })
