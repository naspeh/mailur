import datetime as dt

from mailur import local
from mailur.web import from_list


def test_login_and_themes(web, some):
    res = web.get('/login', status=200)
    assert '/theme-base.css' in res, res.text
    assert '/login.js' in res, res.txt
    assert '"themes": ["base", "indigo", "mint", "solarized"]' in res, res.text
    assert '"Europe/Kiev"' in res, res.text

    res = web.get('/solarized/login', status=200)
    assert '/theme-solarized.css' in res, res.text

    res = web.post_json('/login', status=400)
    assert 'errors' in res
    assert 'schema' in res
    assert web.cookies == {}

    res = web.get('/', status=302)
    assert res.location.endswith('/login')
    assert web.cookies == {'origin_url': '"/"'}
    res.follow(status=200)

    res = web.post_json('/login', {'username': 'test1'}, status=400)
    assert 'errors' in res
    assert 'schema' in res

    login = {'username': 'test1', 'password': 'user', 'timezone': 'UTC'}
    res = web.post_json('/login', dict(login, password=''), status=400)
    assert res.json == {
        'errors': ['Authentication failed.'],
        'details': "b'[AUTHENTICATIONFAILED] Authentication failed.'"
    }
    web.get('/', status=302)

    res = web.post_json('/login', login, status=200)
    assert web.cookies == {'session': some}
    assert 'test1' not in some
    res = web.get('/', status=200)
    assert '/theme-base.css' in res, res.text
    assert '/index.js' in res, res.text
    assert 'window.data={"tags":' in res, res.text

    res = web.get('/solarized/', status=200)
    assert '/theme-solarized.css' in res, res.text

    res = web.post_json('/login', dict(login, theme='solarized'), status=200)
    res = web.get('/', status=200)
    assert '/theme-solarized.css' in res, res.text

    res = web.get('/logout', status=302)
    assert web.cookies == {}


def test_tz(clean_users, gm_client, web, login, some):
    res = web.get('/timezones')
    assert 'Europe/Kiev' in res

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
        return dict({
            'id': name,
            'name': name,
            'short_name': name,
            'query': ':threads keyword "%s"' % name
        }, **kw)

    web = login()

    res = web.get('/tags', status=200)
    assert res.json == {
        '#inbox': tag('#inbox', pinned=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
        '#sent': tag('#sent', unread=0),
        '#latest': tag('#latest', unread=0),
    }

    gm_client.add_emails([{'labels': '\\Inbox'}])
    local.parse()

    res = web.get('/tags', status=200)
    assert res.json == {
        '#inbox': tag('#inbox', pinned=1, unread=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
        '#sent': tag('#sent', unread=0),
        '#latest': tag('#latest', unread=0),
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
