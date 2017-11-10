from unittest.mock import ANY

from mailur import app, local


def test_from_list():
    res = app.from_list(local.addresses('test <test@example.com>'))
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test <test@example.com>'
    }]

    res = app.from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test2', 'addr': ANY, 'hash': ANY, 'title': ANY},
    ]

    res = app.from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
        'test3 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test2', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test3', 'addr': ANY, 'hash': ANY, 'title': ANY},
    ]

    res = app.from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
        'test3 <test@example.com>,'
        'test4 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test2', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test3', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test4', 'addr': ANY, 'hash': ANY, 'title': ANY},
    ]

    res = app.from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
        'test3 <test@example.com>,'
        'test4 <test@example.com>,'
        'test5 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'expander': '2 more'},
        {'name': 'test4', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test5', 'addr': ANY, 'hash': ANY, 'title': ANY},
    ]

    res = app.from_list(local.addresses(','.join(
        'test%s <test@example.com>' % i for i in range(10)
    )))
    assert res == [
        {'name': 'test0', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'expander': '7 more'},
        {'name': 'test8', 'addr': ANY, 'hash': ANY, 'title': ANY},
        {'name': 'test9', 'addr': ANY, 'hash': ANY, 'title': ANY},
    ]
