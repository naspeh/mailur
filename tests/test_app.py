import datetime as dt

from mailur import local
from mailur.web import from_list


def test_login_and_themes(web, some):
    res = web.get('/login', status=200)
    assert '/theme-base.css' in res, res.text
    assert '/login.js' in res, res.txt
    assert '"themes": ["base", "indigo", "mint", "solarized"]' in res, res.text
    assert '"Europe/Kiev"' in res, res.text
    assert '"current_theme": "base"' in res, res.text

    res = web.get('/solarized/login', status=200)
    assert '/theme-solarized.css' in res, res.text
    assert '"current_theme": "solarized"' in res, res.text

    login = {'username': 'test1', 'password': 'user', 'timezone': 'UTC'}
    res = web.post_json('/login', login, status=200)
    assert web.cookies == {'session': some}
    assert 'test1' not in some
    res = web.get('/', status=200)
    assert '/theme-base.css' in res, res.text
    assert '/index.js' in res, res.text
    assert '"tags": {' in res, res.text
    assert '"current_theme": "base"' in res, res.text

    res = web.get('/solarized/', status=200)
    assert '/theme-solarized.css' in res, res.text

    web.reset()
    res = web.post_json('/login', dict(login, theme='solarized'), status=200)
    res = web.get('/', status=200)
    assert '/theme-solarized.css' in res, res.text

    res = web.get('/logout', status=302)
    assert web.cookies == {}

    res = web.get('/', status=302)
    assert res.location == 'http://localhost:80/login'
    res.follow(status=200)

    web.reset()
    res = web.get('/solarized/', status=302)
    assert res.location == 'http://localhost:80/solarized/login'
    res.follow(status=200)

    web.get('/tags', status=403)

    res = web.post_json('/login', status=400)
    assert 'errors' in res
    assert 'schema' in res
    assert web.cookies == {}

    res = web.post_json('/login', {'username': 'test1'}, status=400)
    assert 'errors' in res
    assert 'schema' in res

    res = web.post_json('/login', dict(login, password=''), status=400)
    assert res.json == {
        'errors': ['Authentication failed.'],
        'details': "b'[AUTHENTICATIONFAILED] Authentication failed.'"
    }
    web.get('/', status=302)


def test_tz(clean_users, gm_client, web, login, some):
    time_dt = dt.datetime.utcnow()
    time = int(time_dt.timestamp())
    gm_client.add_emails([{'labels': '\\Inbox', 'date': time}])
    local.parse()

    web = login(tz='UTC')
    res = web.post_json('/search', {'q': 'all', 'preload': 1}, status=200)
    assert res.json == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'threads': False
    }
    assert some['time_human'] == time_dt.strftime('%H:%M')
    assert some['time_title'] == time_dt.strftime('%a, %d %b, %Y at %H:%M')

    web = login(tz='Asia/Singapore')
    res = web.post_json('/search', {'q': 'all', 'preload': 1}, status=200)
    assert res.json == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'threads': False,
    }
    time_2h = time_dt + dt.timedelta(hours=8)
    assert some['time_human'] == time_2h.strftime('%H:%M')
    assert some['time_title'] == time_2h.strftime('%a, %d %b, %Y at %H:%M')


def test_tags(clean_users, gm_client, login, some):
    def tag(name, **kw):
        id = kw.get('id', name)
        return dict({
            'id': id,
            'name': name,
            'short_name': name,
            'query': ':threads keyword "%s"' % id
        }, **kw)

    web = login()

    res = web.get('/tags', status=200)
    assert res.json == {'ids': ['#inbox', '#spam', '#trash'], 'info': some}
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
    }

    gm_client.add_emails([{'labels': '\\Inbox test1 "test 2"'}])
    local.parse()

    res = web.get('/tags', status=200)
    assert res.json == {
        'ids': ['#inbox', '#38b0d2ff', 'test1', '#spam', '#trash'],
        'info': some
    }
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1, unread=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
        'test1': tag('test1', unread=1),
        '#38b0d2ff': tag('test 2', unread=1, id='#38b0d2ff')
    }

    gm_client.add_emails([{'labels': '"test 3"', 'flags': '\\Flagged'}])
    local.parse()
    res = web.get('/tags', status=200)
    assert res.json == {
        'ids': [
            '#inbox', '#38b0d2ff', '#e558c4df', 'test1',
            '#spam', '#trash',
        ],
        'info': some
    }
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1, unread=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
        'test1': tag('test1', unread=1),
        '#38b0d2ff': tag('test 2', unread=1, id='#38b0d2ff'),
        '#e558c4df': tag('test 3', unread=1, id='#e558c4df'),
    }

    res = web.post_json('/tag/new', {'name': 'new'}, status=200)
    assert res.json == tag('new')

    web = login(username='test2')
    res = web.get('/tags', status=200)
    assert res.json == {'ids': ['#inbox', '#spam', '#trash'], 'info': some}
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
    }


def test_basic(clean_users, gm_client, login, some):
    web = login()
    res = web.post_json('/search', {'q': 'all', 'preload': 10}, status=200)
    assert res.json == {
        'uids': [],
        'msgs': {},
        'msgs_info': '/msgs/info',
        'threads': False
    }

    gm_client.add_emails([{}, {'refs': '<101@mlr>'}])
    local.parse()
    res = web.post_json('/search', {'q': 'all', 'preload': 10}, status=200)
    assert res.json == {
        'uids': ['2', '1'],
        'msgs': {
            '1': {
                'arrived': 1499504910,
                'count': 0,
                'date': some,
                'tags': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<101@mlr>',
                'origin_uid': '1',
                'parent': None,
                'preview': '42',
                'query_msgid': ':threads header message-id "<101@mlr>"',
                'query_subject': ':threads header subject "Subj 101"',
                'query_thread': ':thread 1',
                'subject': 'Subj 101',
                'time_human': some,
                'time_title': some,
                'uid': '1',
                'url_raw': '/raw/1',
            },
            '2': {
                'arrived': 1499504910,
                'count': 0,
                'date': some,
                'tags': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<102@mlr>',
                'origin_uid': '2',
                'parent': '<101@mlr>',
                'preview': '42',
                'query_msgid': ':threads header message-id "<102@mlr>"',
                'query_subject': ':threads header subject "Subj 102"',
                'query_thread': ':thread 2',
                'subject': 'Subj 102',
                'time_human': some,
                'time_title': some,
                'uid': '2',
                'url_raw': '/raw/2',
            }
        },
        'msgs_info': '/msgs/info',
        'threads': False,
    }
    res = web.post_json(
        '/search', {'q': ':threads all', 'preload': 10}, status=200
    )
    assert res.json == {
        'uids': ['2'],
        'msgs': {
            '2': {
                'arrived': 1499504910,
                'count': 2,
                'date': some,
                'tags': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<102@mlr>',
                'origin_uid': '2',
                'parent': '<101@mlr>',
                'preview': '42',
                'query_msgid': ':threads header message-id "<102@mlr>"',
                'query_subject': ':threads header subject "Subj 102"',
                'query_thread': ':thread 2',
                'subject': 'Subj 102',
                'time_human': some,
                'time_title': some,
                'uid': '2',
                'uids': ['1', '2'],
                'url_raw': '/raw/2',
            }
        },
        'msgs_info': '/thrs/info',
        'threads': True
    }


def test_msgs_flag(clean_users, gm_client, login, msgs):
    def post(uids, **data):
        web.post_json('/msgs/flag', dict(uids=uids, **data), status=200)
        return [' '.join(sorted(m['flags'].split())) for m in msgs(local.ALL)]

    web = login()
    web.post_json('/msgs/flag', {'new': ['\\Seen']}, status=400)
    web.post_json('/msgs/flag', {'old': ['\\Seen']}, status=400)

    gm_client.add_emails([{}])
    local.parse()
    assert [m['flags'] for m in msgs(local.ALL)] == ['#latest']

    assert post(['1'], new=['\\Seen']) == ['#latest \\Seen']
    assert post(['1'], old=['\\Seen']) == ['#latest']

    gm_client.add_emails([{'refs': '<101@mlr>'}])
    local.parse()
    assert [m['flags'] for m in msgs(local.ALL)] == ['', '#latest']
    assert post(['1', '2'], new=['\\Seen']) == ['\\Seen', '#latest \\Seen']
    assert post(['1'], old=['\\Seen']) == ['', '#latest \\Seen']
    assert post(['1', '2'], old=['\\Seen']) == ['', '#latest']

    assert post(['1', '2'], new=['#1', '#2']) == ['#1 #2', '#1 #2 #latest']
    assert post(['1', '2'], new=['#3', '#2'], old=['#1', '#2']) == [
        '#2 #3', '#2 #3 #latest'
    ]
    assert post(['1', '2'], new=['#4'], old=['#2', '#3']) == [
        '#4', '#4 #latest'
    ]


def test_search_thread(clean_users, gm_client, login, some):
    def post(uid):
        data = {'q': ':thread %s' % uid, 'preload': 4}
        return web.post_json('/search', data, status=200).json

    web = login()
    assert post('1') == {}

    gm_client.add_emails([{}])
    local.parse()
    res = post('1')
    assert res == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'tags': [],
        'same_subject': [],
    }

    gm_client.add_emails([{'refs': '<101@mlr>'}] * 2)
    local.parse()
    res = post('1')
    assert len(res['uids']) == 3
    assert len(res['msgs']) == 3
    assert res['tags'] == []
    assert res['same_subject'] == []

    gm_client.add_emails([{'refs': '<101@mlr>', 'subj': 'Subj 103'}] * 3)
    local.parse()
    res = post('1')
    assert len(res['uids']) == 6
    assert len(res['msgs']) == 6
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    res = web.post_json('/msgs/flag', {
        'uids': res['uids'], 'new': ['\\Seen']
    }, status=200)

    res = post('1')
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '4', '5', '6']
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    res = web.post_json('/msgs/flag', {
        'uids': ['2'], 'new': ['\\Flagged']
    }, status=200)

    res = post('1')
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '2', '4', '5', '6']
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    res = web.post_json('/msgs/flag', {
        'uids': ['2'], 'new': ['#inbox', '#sent', 'test2']
    }, status=200)
    res = web.post_json('/msgs/flag', {
        'uids': ['1'], 'new': ['#inbox', 'test1']
    }, status=200)

    res = post('1')
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '2', '4', '5', '6']
    assert res['tags'] == ['#inbox', 'test1', 'test2']
    assert [res['msgs'][uid]['tags'] for uid in sorted(res['msgs'])] == [
        [], [], [], [], []
    ]

    res = web.post_json(res['msgs_info'], {
        'uids': res['uids'],
        'hide_tags': res['tags']
    })
    assert [res.json[uid]['tags'] for uid in sorted(res.json)] == [
        [], [], [], [], [], []
    ]


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
