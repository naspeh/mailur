from pytest import fixture

from mailur.env import Env


@fixture
def env():
    '''Test Environment'''
    return Env({'password': 'test'})
