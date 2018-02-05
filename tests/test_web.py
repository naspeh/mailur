import datetime as dt

from mailur.message import addresses
from mailur.web import parse_query, wrap_addresses


def test_login_and_themes(web, some, login):
    res = web.get('/login', status=200)
    assert '/theme-base.css' in res, res.text
    assert '/login.js' in res, res.txt
    assert '"themes": ["base", "indigo", "mint", "solarized"]' in res, res.text
    assert '"Europe/Kiev"' in res, res.text
    assert '"current_theme": "base"' in res, res.text

    res = web.get('/solarized/login', status=200)
    assert '/theme-solarized.css' in res, res.text
    assert '"current_theme": "solarized"' in res, res.text

    params = {'username': login.user1, 'password': 'user', 'timezone': 'UTC'}
    res = web.post_json('/login', params, status=200)
    assert web.cookies == {'session': some}
    assert login.user1 not in some
    res = web.get('/', status=200)
    assert '/theme-base.css' in res, res.text
    assert '/index.js' in res, res.text
    assert '"tags": {' in res, res.text
    assert '"current_theme": "base"' in res, res.text

    res = web.get('/solarized/', status=200)
    assert '/theme-solarized.css' in res, res.text

    web.reset()
    res = web.post_json('/login', dict(params, theme='solarized'), status=200)
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

    res = web.post_json('/login', {'username': login.user1}, status=400)
    assert 'errors' in res
    assert 'schema' in res

    res = web.post_json('/login', dict(params, password=''), status=400)
    assert res.json == {
        'errors': ['Authentication failed.'],
        'details': "b'[AUTHENTICATIONFAILED] Authentication failed.'"
    }
    web.get('/', status=302)


def test_tz(gm_client, web, login, some):
    time_dt = dt.datetime.utcnow()
    time = int(time_dt.timestamp())
    gm_client.add_emails([{'labels': '\\Inbox', 'date': time}])

    web = login(tz='UTC')
    res = web.post_json('/search', {'q': '', 'preload': 1}, status=200)
    assert res.json == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
    }
    assert some['time_human'] == time_dt.strftime('%H:%M')
    assert some['time_title'] == time_dt.strftime('%a, %d %b, %Y at %H:%M')

    web = login(tz='Asia/Singapore')
    res = web.post_json('/search', {'q': '', 'preload': 1}, status=200)
    assert res.json == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
    }
    time_2h = time_dt + dt.timedelta(hours=8)
    assert some['time_human'] == time_2h.strftime('%H:%M')
    assert some['time_title'] == time_2h.strftime('%a, %d %b, %Y at %H:%M')


def test_tags(gm_client, login, some):
    def tag(name, **kw):
        id = kw.get('id', name)
        return dict({
            'id': id,
            'name': name,
            'short_name': name,
            'query': ':threads tag:%s' % id
        }, **kw)

    web = login()
    res = web.get('/tags', status=200)
    assert res.json == {'ids': ['#inbox', '#spam', '#trash'], 'info': some}
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
    }

    gm_client.add_emails([
        {'labels': '\\Inbox \\Junk'},
        {'labels': '\\Junk \\Trash'}
    ])
    res = web.get('/tags', status=200)
    assert res.json == {'ids': ['#inbox', '#spam', '#trash'], 'info': some}
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1, unread=0),
        '#spam': tag('#spam', pinned=1, unread=1),
        '#trash': tag('#trash', pinned=1, unread=1),
    }

    gm_client.add_emails([{'labels': '\\Inbox t1 "test 2"'}])
    res = web.get('/tags', status=200)
    assert res.json == {
        'ids': ['#inbox', 't1', '#38b0d2ff', '#spam', '#trash'],
        'info': some
    }
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1, unread=1),
        '#spam': tag('#spam', pinned=1, unread=1),
        '#trash': tag('#trash', pinned=1, unread=1),
        't1': tag('t1', unread=1),
        '#38b0d2ff': tag('test 2', unread=1, id='#38b0d2ff')
    }

    gm_client.add_emails([{'labels': '"test 3"', 'flags': '\\Flagged'}])
    res = web.get('/tags', status=200)
    assert res.json == {
        'ids': ['#inbox', 't1', '#38b0d2ff', '#e558c4df', '#spam', '#trash'],
        'info': some
    }
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1, unread=1),
        '#spam': tag('#spam', pinned=1, unread=1),
        '#trash': tag('#trash', pinned=1, unread=1),
        't1': tag('t1', unread=1),
        '#38b0d2ff': tag('test 2', unread=1, id='#38b0d2ff'),
        '#e558c4df': tag('test 3', unread=1, id='#e558c4df'),
    }

    web = login(username=login.user2)
    res = web.get('/tags', status=200)
    assert res.json == {'ids': ['#inbox', '#spam', '#trash'], 'info': some}
    assert some.value == {
        '#inbox': tag('#inbox', pinned=1),
        '#spam': tag('#spam', pinned=1),
        '#trash': tag('#trash', pinned=1),
    }

    web = login()
    web.post_json('/tag', {}, status=400)
    web.post_json('/tag', {'name': '#new'}, status=400)
    web.post_json('/tag', {'name': '\\new'}, status=400)
    res = web.post_json('/tag', {'name': 'new'}, status=200)
    assert res.json == tag('new')
    res = web.post_json('/tag', {'name': 'нью'}, status=200)
    assert res.json == tag('нью', id='#d44f332a')


def test_general(gm_client, load_email, login, some):
    web = login()
    res = web.post_json('/search', {'q': '', 'preload': 10}, status=200)
    assert res.json == {
        'uids': [],
        'msgs': {},
        'msgs_info': '/msgs/info',
    }

    msg = {'labels': '\\Inbox'}
    gm_client.add_emails([msg, dict(msg, refs='<101@mlr>')])
    res = web.post_json('/search', {'q': '', 'preload': 10}, status=200)
    assert res.json == {
        'uids': ['2', '1'],
        'msgs': {
            '1': {
                'arrived': 1499504910,
                'count': 0,
                'date': some,
                'errors': [],
                'files': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<101@mlr>',
                'origin_uid': '1',
                'parent': None,
                'preview': '42',
                'query_msgid': 'ref:<101@mlr>',
                'query_subject': ':threads subj:"Subj 101"',
                'query_thread': 'thread:1',
                'subject': 'Subj 101',
                'tags': ['#inbox'],
                'time_human': some,
                'time_title': some,
                'uid': '1',
                'url_raw': '/raw/1',
            },
            '2': {
                'arrived': 1499504910,
                'count': 0,
                'date': some,
                'errors': [],
                'files': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<102@mlr>',
                'origin_uid': '2',
                'parent': '<101@mlr>',
                'preview': '42',
                'query_msgid': 'ref:<102@mlr>',
                'query_subject': ':threads subj:"Subj 102"',
                'query_thread': 'thread:2',
                'subject': 'Subj 102',
                'tags': ['#inbox'],
                'time_human': some,
                'time_title': some,
                'uid': '2',
                'url_raw': '/raw/2',
            }
        },
        'msgs_info': '/msgs/info',
    }

    web.post_json('/msgs/flag', {'uids': ['1'], 'new': ['\\Seen']}, status=200)
    res = web.post_json('/search', {'q': 'in:#inbox'}, status=200)
    assert [i['is_unread'] for i in res.json['msgs'].values()] == [False, True]

    res = web.post_json('/search', {'q': ':threads'}, status=200)
    assert res.json == {
        'uids': ['2'],
        'msgs': {
            '2': {
                'arrived': 1499504910,
                'count': 2,
                'date': some,
                'errors': [],
                'files': [],
                'from_list': [],
                'is_pinned': False,
                'is_unread': True,
                'msgid': '<102@mlr>',
                'origin_uid': '2',
                'parent': '<101@mlr>',
                'preview': '42',
                'query_msgid': 'ref:<102@mlr>',
                'query_subject': ':threads subj:"Subj 102"',
                'query_thread': 'thread:2',
                'subject': 'Subj 102',
                'tags': ['#inbox'],
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
    web.post_json('/msgs/flag', {'uids': ['2'], 'new': ['\\Seen']}, status=200)
    res = web.post_json('/search', {'q': ':threads in:#inbox'}, status=200)
    assert not res.json['msgs']['2']['is_unread']

    res = web.get('/raw/2')
    assert res.content_type == 'text/plain'
    assert 'Message-ID: <102@mlr>' in res.text
    res = web.get('/raw/2/1')
    assert res.content_type == 'text/plain'
    assert '42' in res.text

    m = load_email('msg-attachments-two-gmail.txt')
    q = 'thread:%s' % m['uid']
    res = web.post_json('/search', {'q': q}, status=200)
    assert res.json == {
        'uids': ['3'],
        'msgs_info': '/msgs/info',
        'msgs': {'3': some},
        'same_subject': [],
        'tags': [],
        'thread': True,
    }
    assert some['files'] == [
        {
            'filename': '08.png',
            'image': True,
            'path': '2',
            'size': 553,
            'url': '/raw/3/2/08.png'
        },
        {
            'filename': '09.png',
            'image': True,
            'path': '3',
            'size': 520,
            'url': '/raw/3/3/09.png'
        }
    ]
    assert some['preview'] == (
        'ответ на тело 2014-03-03 18:09 GMT+02:00 Ne Greh '
        '&lt; negreh@gmail.com &gt; : тело  [08.png, 09.png]'
    )
    res = web.get(some['files'][0]['url'], status=200)
    assert res.content_type == 'image/png'
    res = web.get(some['files'][1]['url'], status=200)
    assert res.content_type == 'image/png'
    res = web.get('/raw/3')
    assert res.content_type == 'text/plain'

    res = web.post_json('/search', {'q': 'tag:#inbox'}, status=200)
    assert res.json['tags'] == ['#inbox']
    assert [i['tags'] for i in res.json['msgs'].values()] == [[], []]


def test_msgs_flag(gm_client, login, msgs):
    def post(uids, **data):
        web.post_json('/msgs/flag', dict(uids=uids, **data), status=200)
        return [' '.join(sorted(m['flags'].split())) for m in msgs()]

    web = login()
    web.post_json('/msgs/flag', {'new': ['\\Seen']}, status=400)
    web.post_json('/msgs/flag', {'old': ['\\Seen']}, status=400)

    gm_client.add_emails([{}])
    assert [m['flags'] for m in msgs()] == ['#latest']

    assert post(['1'], new=['\\Seen']) == ['#latest \\Seen']
    assert post(['1'], old=['\\Seen']) == ['#latest']

    gm_client.add_emails([{'refs': '<101@mlr>'}])
    assert [m['flags'] for m in msgs()] == ['', '#latest']
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


def test_search_thread(gm_client, login, some):
    def post(uid, preload=4):
        data = {'q': 'thread:%s' % uid, 'preload': preload}
        return web.post_json('/search', data, status=200).json

    web = login()
    assert post('1') == {}

    gm_client.add_emails([{}])
    res = post('1')
    assert res == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'tags': [],
        'same_subject': [],
        'thread': True,
    }

    gm_client.add_emails([{'refs': '<101@mlr>'}] * 2)
    res = post('1')
    assert len(res['uids']) == 3
    assert len(res['msgs']) == 3
    assert res['tags'] == []
    assert res['same_subject'] == []

    gm_client.add_emails([{'refs': '<101@mlr>', 'subj': 'Subj 103'}] * 3)
    res = post('1')
    assert len(res['uids']) == 6
    assert len(res['msgs']) == 6
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    res = web.post_json('/msgs/flag', {
        'uids': res['uids'], 'new': ['\\Seen']
    }, status=200)

    res = post('1', preload=2)
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '6']
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    res = web.post_json('/msgs/flag', {
        'uids': ['2'], 'new': ['\\Flagged']
    }, status=200)

    res = post('1', preload=2)
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '2', '6']
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    res = web.post_json('/msgs/flag', {
        'uids': ['2'], 'new': ['#inbox', '#sent', 'test2']
    }, status=200)
    res = web.post_json('/msgs/flag', {
        'uids': ['1'], 'new': ['#inbox', 'test1']
    }, status=200)

    res = post('1', preload=None)
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '2', '3', '4', '5', '6']
    assert res['tags'] == ['#inbox', 'test1', 'test2']
    assert [res['msgs'][uid]['tags'] for uid in sorted(res['msgs'])] == [
        [], [], [], [], [], []
    ]

    res = web.post_json(res['msgs_info'], {
        'uids': res['uids'],
        'hide_tags': res['tags']
    })
    assert [res.json[uid]['tags'] for uid in sorted(res.json)] == [
        [], [], [], [], [], []
    ]


def test_from_list(some):
    res = wrap_addresses(addresses('test <test@example.com>'))
    assert res == [
        {
            'name': 'test',
            'addr': 'test@example.com',
            'hash': '55502f40dc8b7c769880b10874abc9d0',
            'title': 'test <test@example.com>',
            'query': ':threads from:test@example.com',
        },
    ]

    res = wrap_addresses(addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
    ))
    assert ['test', 'test2'] == [a['name'] for a in res]

    res = wrap_addresses(addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
    ))
    assert ['test', 'test2', 'test3'] == [a['name'] for a in res]

    res = wrap_addresses(addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
    ))
    assert ['test', 'test2', 'test3', 'test4'] == [a['name'] for a in res]

    res = wrap_addresses(addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
        'test5 <test5@example.com>,'
    ))
    assert ['test', {'expander': 2}, 'test4', 'test5'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = wrap_addresses(addresses(
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

    res = wrap_addresses(addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test2 <test2@example.com>,'
    ))
    assert ['test', 'test3', 'test2'] == [a['name'] for a in res]

    res = wrap_addresses(addresses(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
    ))
    assert ['test', 'test2', 'test3'] == [a['name'] for a in res]

    res = wrap_addresses(addresses(','.join(
        'test{0} <test{0}@example.com>'.format(i) for i in range(10)
    )))
    assert ['test0', {'expander': 7}, 'test8', 'test9'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = wrap_addresses(addresses(','.join(
        'test <test@example.com>' for i in range(10)
    )))
    assert ['test'] == [a['name'] for a in res]


def test_query():
    ending = 'unkeyword #trash unkeyword #spam'
    assert parse_query('') == (ending, {})
    assert parse_query('test') == ('text "test" ' + ending, {})
    assert parse_query('test1 test2') == ('text "test1 test2" ' + ending, {})

    assert parse_query('thread:1') == ('uid 1', {'thread': True})
    assert parse_query('thr:1') == ('uid 1', {'thread': True})
    assert parse_query('thr:1 test') == ('uid 1 text "test"', {'thread': True})
    assert parse_query('THR:1') == ('uid 1', {'thread': True})

    assert parse_query('in:#inbox') == (
        'keyword #inbox ' + ending,
        {'tags': ['#inbox']}
    )
    assert parse_query('tag:#sent') == (
        'keyword #sent ' + ending,
        {'tags': ['#sent']}
    )
    assert parse_query('tag:#inbox tag:#work') == (
        'keyword #inbox keyword #work ' + ending,
        {'tags': ['#inbox', '#work']}
    )

    assert parse_query('tag:#trash') == (
        'keyword #trash',
        {'tags': ['#trash']}
    )
    assert parse_query('tag:#spam') == (
        'keyword #spam unkeyword #trash',
        {'tags': ['#spam']}
    )

    assert parse_query(':threads') == (ending, {'threads': True})
    assert parse_query(':threads test') == (
        'text "test" ' + ending,
        {'threads': True}
    )
    assert parse_query('test :threads') == (
        'text "test" ' + ending,
        {'threads': True}
    )

    assert parse_query('uid:1') == ('uid 1 ' + ending, {})
    assert parse_query('uid:1 :threads') == (
        'uid 1 ' + ending, {'threads': True}
    )

    assert parse_query('from:t@t.com') == ('from t@t.com ' + ending, {})
    assert parse_query('from:t@t.com test') == (
        'from t@t.com text "test" ' + ending, {}
    )
    assert parse_query('subj:"test subj"') == (
        'header subject "test subj" ' + ending, {}
    )
    assert parse_query('subject:"test subj" test') == (
        'header subject "test subj" text "test" ' + ending, {}
    )
    assert parse_query('mid:<101@mlr>') == (
        'header message-id <101@mlr> ' + ending, {}
    )
    assert parse_query('message_id:<101@mlr> test') == (
        'header message-id <101@mlr> text "test" ' + ending, {}
    )
    assert parse_query('ref:<_@mlr>') == (
        'or header message-id <_@mlr> header references <_@mlr> ' + ending, {}
    )

    assert parse_query(':raw text in:#spam') == ('text in:#spam ' + ending, {})

    assert parse_query(':unread') == ('unseen ' + ending, {})
    assert parse_query(':unseen') == ('unseen ' + ending, {})
    assert parse_query(':seen') == ('seen ' + ending, {})
    assert parse_query(':read') == ('seen ' + ending, {})
    assert parse_query(':pinned') == ('flagged ' + ending, {})
    assert parse_query(':unpinned') == ('unflagged ' + ending, {})
    assert parse_query(':flagged') == ('flagged ' + ending, {})
    assert parse_query(':unflagged') == ('unflagged ' + ending, {})
    assert parse_query(':pin :unread') == ('flagged unseen ' + ending, {})
