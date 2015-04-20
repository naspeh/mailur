from pytest import fixture

from mailur import Env


@fixture
def env():
    '''Test Environment'''
    return Env({
        'pg_username': '',
        'pg_password': '',
        'google_id': '',
        'google_secret': '',
        'cookie_secret': 'secret'
    })
