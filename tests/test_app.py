import datetime as dt

from mailur import local
from mailur.web import from_list


def test_init(clean_users, gm_client, web, some):
    res = web.post_json('/init')
    assert res.status_code == 200
    assert web.cookies == {}

    res = web.post_json('/init', {'offset': 2})
    assert res.status_code == 200
    assert web.cookies == {'offset': '2'}
    assert res.json == {'tags': {'#inbox': {'name': '#inbox', 'unread': 0}}}

    time_dt = dt.datetime.utcnow()
    time = int(time_dt.timestamp())
    gm_client.add_emails([{'labels': '\\Inbox', 'date': time}])
    local.parse()

    res = web.post_json('/init')
    assert res.status_code == 200
    assert web.cookies == {'offset': '2'}
    assert res.json == {'tags': {'#inbox': {'name': '#inbox', 'unread': 1}}}

    res = web.post_json('/search', {'q': 'all', 'preload': 1})
    assert res.status_code == 200
    assert res.json == {
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'uids': ['1']
    }
    time_2h = time_dt + dt.timedelta(hours=2)
    assert some['time_human'] == time_2h.strftime('%H:%M')
    assert some['time_title'] == time_2h.strftime('%a, %d %b, %Y at %H:%M')

    res = web.post_json('/init', {'offset': 0})
    assert res.status_code == 200
    assert web.cookies == {'offset': '0'}

    res = web.post_json('/search', {'q': 'all', 'preload': 1})
    assert res.status_code == 200
    assert res.json == {
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'uids': ['1']
    }
    assert some['time_human'] == time_dt.strftime('%H:%M')
    assert some['time_title'] == time_dt.strftime('%a, %d %b, %Y at %H:%M')


def test_from_list(some):
    res = from_list(local.addresses('test <test@example.com>'))
    assert res == [{
        'name': 'test',
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'title': 'test <test@example.com>'
    }]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test2', 'addr': some, 'hash': some, 'title': some},
    ]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
        'test3 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test2', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test3', 'addr': some, 'hash': some, 'title': some},
    ]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
        'test3 <test@example.com>,'
        'test4 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test2', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test3', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test4', 'addr': some, 'hash': some, 'title': some},
    ]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test@example.com>,'
        'test3 <test@example.com>,'
        'test4 <test@example.com>,'
        'test5 <test@example.com>,'
    ))
    assert res == [
        {'name': 'test', 'addr': some, 'hash': some, 'title': some},
        {'expander': 2},
        {'name': 'test4', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test5', 'addr': some, 'hash': some, 'title': some},
    ]

    res = from_list(local.addresses(','.join(
        'test%s <test@example.com>' % i for i in range(10)
    )))
    assert res == [
        {'name': 'test0', 'addr': some, 'hash': some, 'title': some},
        {'expander': 7},
        {'name': 'test8', 'addr': some, 'hash': some, 'title': some},
        {'name': 'test9', 'addr': some, 'hash': some, 'title': some},
    ]
