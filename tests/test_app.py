import datetime as dt

from mailur import local
from mailur.web import from_list


def test_init(clean_users, gm_client, web, some):
    def tag(name, **kw):
        return dict({
            'id': name,
            'name': name,
            'short_name': name,
            'query': ':threads keyword "%s"' % name
        }, **kw)

    res = web.post_json('/init')
    assert res.status_code == 200
    assert web.cookies == {}

    res = web.post_json('/init', {'offset': 2})
    assert res.status_code == 200
    assert web.cookies == {'offset': '2'}
    assert res.json == {'tags': {
        '#inbox': tag('#inbox', pinned=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
        '#sent': tag('#sent', unread=0),
        '#latest': tag('#latest', unread=0),
    }}

    time_dt = dt.datetime.utcnow()
    time = int(time_dt.timestamp())
    gm_client.add_emails([{'labels': '\\Inbox', 'date': time}])
    local.parse()

    res = web.post_json('/init')
    assert res.status_code == 200
    assert web.cookies == {'offset': '2'}
    assert res.json == {'tags': {
        '#inbox': tag('#inbox', pinned=1, unread=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
        '#sent': tag('#sent', unread=0),
        '#latest': tag('#latest', unread=0),
    }}

    res = web.post_json('/search', {'q': 'all', 'preload': 1})
    assert res.status_code == 200
    assert res.json == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'threads': False,
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
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'threads': False
    }
    assert some['time_human'] == time_dt.strftime('%H:%M')
    assert some['time_title'] == time_dt.strftime('%a, %d %b, %Y at %H:%M')


def test_basic(clean_users, gm_client, web, some):
    res = web.post_json('/search', {'q': 'all', 'preload': 10})
    assert res.status_code == 200
    assert res.json == {
        'uids': [],
        'msgs': {},
        'msgs_info': '/msgs/info',
        'threads': False
    }

    gm_client.add_emails([{}, {'refs': '<101@mlr>'}])
    local.parse()
    res = web.post_json('/search', {'q': 'all', 'preload': 10})
    assert res.status_code == 200
    assert res.json == {
        'uids': ['2', '1'],
        'msgs': {
            '1': {
                'arrived': 1499504910,
                'count': 0,
                'date': some,
                'flags': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<101@mlr>',
                'origin_uid': '1',
                'parent': None,
                'preview': '42',
                'query_msgid': ':threads header message-id "<101@mlr>"',
                'query_subject': ':threads header subject "Subj 101"',
                'query_thread': 'inthread refs uid 1',
                'subject': 'Subj 101',
                'time_human': some,
                'time_title': some,
                'uid': '1',
                'url_raw': '/raw/1'
            },
            '2': {
                'arrived': 1499504910,
                'count': 0,
                'date': some,
                'flags': ['#latest'],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<102@mlr>',
                'origin_uid': '2',
                'parent': '<101@mlr>',
                'preview': '42',
                'query_msgid': ':threads header message-id "<102@mlr>"',
                'query_subject': ':threads header subject "Subj 102"',
                'query_thread': 'inthread refs uid 2',
                'subject': 'Subj 102',
                'time_human': some,
                'time_title': some,
                'uid': '2',
                'url_raw': '/raw/2'
            }
        },
        'msgs_info': '/msgs/info',
        'threads': False,
    }
    res = web.post_json('/search', {'q': ':threads all', 'preload': 10})
    assert res.status_code == 200
    assert res.json == {
        'uids': ['2'],
        'msgs': {
            '2': {
                'arrived': 1499504910,
                'count': 2,
                'date': some,
                'flags': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<102@mlr>',
                'origin_uid': '2',
                'parent': '<101@mlr>',
                'preview': '42',
                'query_msgid': ':threads header message-id "<102@mlr>"',
                'query_subject': ':threads header subject "Subj 102"',
                'query_thread': 'inthread refs uid 2',
                'subject': 'Subj 102',
                'time_human': some,
                'time_title': some,
                'uid': '2',
                'url_raw': '/raw/2'
            }
        },
        'msgs_info': '/thrs/info',
        'threads': True
    }


def test_from_list(some):
    res = from_list(local.addresses('test <test@example.com>'))
    assert res == [
        {
            'name': 'test',
            'addr': 'test@example.com',
            'hash': '55502f40dc8b7c769880b10874abc9d0',
            'title': 'test <test@example.com>',
            'query': ':threads from test@example.com',
        },
    ]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
    ))
    assert ['test', 'test2'] == [a['name'] for a in res]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
    ))
    assert ['test', 'test2', 'test3'] == [a['name'] for a in res]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
    ))
    assert ['test', 'test2', 'test3', 'test4'] == [a['name'] for a in res]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
        'test5 <test5@example.com>,'
    ))
    assert ['test', {'expander': 2}, 'test4', 'test5'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
        'test5 <test5@example.com>,'
        'test <test@example.com>,'
    ))
    assert [{'expander': 2}, 'test4', 'test5', 'test'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test2 <test2@example.com>,'
    ))
    assert ['test', 'test3', 'test2'] == [a['name'] for a in res]

    res = from_list(local.addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
    ))
    assert ['test', 'test2', 'test3'] == [a['name'] for a in res]

    res = from_list(local.addresses(','.join(
        'test{0} <test{0}@example.com>'.format(i) for i in range(10)
    )))
    assert ['test0', {'expander': 7}, 'test8', 'test9'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = from_list(local.addresses(','.join(
        'test <test@example.com>' for i in range(10)
    )))
    assert ['test'] == [a['name'] for a in res]
