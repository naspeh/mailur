import datetime as dt
import email
import re
import time

from mailur import local
from mailur.message import addresses
from mailur.web import parse_query, wrap_addresses


def test_login_and_themes(web, some, login):
    res = web.get('/login', status=200)
    assert '/assets/theme-base.css' in res, res.text
    assert '/assets/login.js' in res, res.txt
    assert '"themes": ["base", "indigo", "mint", "solarized"]' in res, res.text
    assert '"Europe/Kiev"' in res, res.text
    assert '"current_theme": "base"' in res, res.text

    res = web.get('/login?theme=solarized', status=200)
    assert '/assets/theme-solarized.css' in res, res.text
    assert '"current_theme": "solarized"' in res, res.text

    params = {'username': login.user1, 'password': 'user', 'timezone': 'UTC'}
    res = web.post_json('/login', params, status=200)
    assert web.cookies == {'session': some}
    assert login.user1 not in some
    res = web.get('/', status=200)
    assert '/assets/theme-base.css' in res, res.text
    assert '/assets/index.js' in res, res.text
    assert '"tags": {' in res, res.text
    assert '"current_theme": "base"' in res, res.text

    res = web.get('/?theme=solarized', status=200)
    assert '/assets/theme-solarized.css' in res, res.text

    web.reset()
    res = web.post_json('/login', dict(params, theme='solarized'), status=200)
    res = web.get('/', status=200)
    assert '/assets/theme-solarized.css' in res, res.text

    # max_age should be updated every time
    expires = [i for i in web.cookiejar][0].expires
    time.sleep(1)
    res = web.get('/', status=200)
    assert [i for i in web.cookiejar][0].expires > expires

    res = web.get('/logout', status=302)
    assert res.location == 'http://localhost:80/login?theme=solarized'
    assert web.cookies == {}

    res = web.get('/', status=302)
    assert res.location == 'http://localhost:80/login'
    res.follow(status=200)

    web.reset()
    res = web.get('/?theme=solarized', status=302)
    assert res.location == 'http://localhost:80/login?theme=solarized'
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

    # wrong theme
    web.get('/wrong/login', status=404)
    web = login()
    web.get('/wrong/', status=404)


def test_tz(gm_client, web, login, some):
    time_dt = dt.datetime.utcnow()
    time = int(time_dt.timestamp())
    gm_client.add_emails([{'labels': '\\Inbox', 'date': time}])

    web = login(tz='UTC')
    res = web.search({'q': '', 'preload': 1})
    assert res == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
    }
    assert some['time_human'] == time_dt.strftime('%H:%M')
    assert some['time_title'] == time_dt.strftime('%a, %d %b, %Y at %H:%M')

    web = login(tz='Asia/Singapore')
    res = web.search({'q': '', 'preload': 1})
    assert res == {
        'uids': ['1'],
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
    }
    time_2h = time_dt + dt.timedelta(hours=8)
    assert some['time_human'] == time_2h.strftime('%H:%M')
    assert some['time_title'] == time_2h.strftime('%a, %d %b, %Y at %H:%M')


def test_tags(gm_client, login, some, load_file):
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
        {'raw': load_file('msg-lookup-error.txt')},
        {'mid': '<lookup-error@test>'},
    ])
    assert res.json == {'ids': ['#inbox', '#spam', '#trash'], 'info': some}

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


def test_general(gm_client, load_email, latest, login, some):
    web = login()
    res = web.search({'q': '', 'preload': 10})
    assert res == {
        'uids': [],
        'msgs': {},
        'msgs_info': '/msgs/info',
    }

    msg = {'labels': '\\Inbox'}
    gm_client.add_emails([msg, dict(msg, refs='<101@mlr>')])
    res = web.search({'q': '', 'preload': 10})
    assert res == {
        'uids': ['2', '1'],
        'msgs': {
            '1': {
                'arrived': some,
                'count': 0,
                'date': some,
                'errors': [],
                'files': [],
                'from_list': [],
                'is_draft': False,
                'is_link': False,
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
                'thrid': '<9a500e323280b62c3476c27b9d23274a@mailur.link>',
                'uid': '1',
                'url_raw': '/raw/1/original-msg.eml',
                'url_reply': '/reply/1',
            },
            '2': {
                'arrived': some,
                'count': 0,
                'date': some,
                'errors': [],
                'files': [],
                'from_list': [],
                'is_draft': False,
                'is_link': False,
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
                'thrid': '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
                'uid': '2',
                'url_raw': '/raw/2/original-msg.eml',
                'url_reply': '/reply/2',
            }
        },
        'msgs_info': '/msgs/info',
    }

    web.post_json('/msgs/body', {'uids': ['1']}, status=200)
    res = web.search({'q': 'in:#inbox'})
    assert [i['is_unread'] for i in res['msgs'].values()] == [False, True]
    web.post_json('/msgs/body', {'uids': ['1']}, status=200)

    res = web.search({'q': ':threads'})
    assert res == {
        'uids': ['2'],
        'msgs': {
            '2': {
                'arrived': some,
                'count': 2,
                'date': some,
                'errors': [],
                'files': [],
                'from_list': [],
                'is_draft': False,
                'is_link': False,
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
                'thrid': '<1ff2e08acb99d6af71ea8ccf5b0d3358@mailur.link>',
                'uid': '2',
                'uids': ['1', '2'],
                'url_raw': '/raw/2/original-msg.eml',
                'url_reply': '/reply/2',
            }
        },
        'msgs_info': '/thrs/info',
        'threads': True
    }
    web.flag({'uids': ['2'], 'new': ['\\Seen']})
    res = web.search({'q': ':threads in:#inbox'})
    assert not res['msgs']['2']['is_unread']

    res = web.get('/raw/2')
    assert res.content_type == 'text/plain'
    assert 'Message-ID: <102@mlr>' in res.text
    res = web.get('/raw/2/1')
    assert res.content_type == 'text/plain'
    assert '42' in res.text

    m = load_email('msg-attachments-two-gmail.txt')
    q = 'thread:%s' % m['uid']
    res = web.search({'q': q})
    assert res == {
        'uids': ['3'],
        'edit': None,
        'has_link': False,
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
            'url': '/raw/3/2/08.png',
        },
        {
            'filename': '09.png',
            'image': True,
            'path': '3',
            'size': 520,
            'url': '/raw/3/3/09.png',
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

    res = web.search({'q': 'tag:#inbox'})
    assert res['tags'] == ['#inbox']
    assert [i['tags'] for i in res['msgs'].values()] == [[], []]

    # one message from thread is going to #trash
    gm_client.add_emails([{'labels': '\\Inbox', 'from': 'one@t.com'}])
    res = web.search({'q': ':threads tag:#inbox'})
    assert res['uids'] == ['4', '2']
    res = web.post_json('/thrs/link', {'uids': res['uids']}).json
    assert res == {'uids': ['4', '1', '2']}
    res = web.search({'q': ':threads tag:#inbox'})
    assert res['uids'] == ['4']
    web.flag({'uids': ['4'], 'new': ['#trash']})
    res = web.search({'q': ':threads tag:#inbox'})
    assert res['uids'] == ['4']
    assert res['msgs']['4']['subject'] == 'Subj 102'
    assert 'from' not in res['msgs']['4']
    res = web.search({'q': 'thread:4'})
    assert res['uids'] == ['1', '2']
    res = web.search({'q': ':threads tag:#trash'})
    assert res['uids'] == ['4']
    assert res['msgs']['4']['subject'] == 'Subj 104'
    assert res['msgs']['4']['from'] == {
        'addr': 'one@t.com',
        'hash': 'bc11cf997156ef71c34c23457e67fd65',
        'name': 'one',
        'query': 'tag:#trash :threads from:one@t.com',
        'title': 'one@t.com'
    }
    res = web.search({'q': 'tag:#trash thread:4'})
    assert res['uids'] == ['4']

    # thread in #trash
    gm_client.add_emails([{'labels': '\\Trash'}])
    m = latest(parsed=True)
    res = web.post_json('/thrs/info', {'uids': [m['uid']]}, status=200).json
    assert res == {}

    # unlink thread
    gm_client.add_emails([{'labels': 'test'}] * 2)
    local.parse('all')
    res = web.search({'q': ':threads tag:test'})
    assert res['uids'] == ['14', '13']
    res = web.post_json('/thrs/link', {'uids': res['uids']}).json
    res = web.search({'q': ':threads tag:test'})
    assert res['uids'] == ['14']
    res = web.post_json('/thrs/unlink', {'uids': res['uids']}).json
    assert res == {'query': ':threads uid:13,14'}
    res = web.search({'q': res['query']})
    assert res['uids'] == ['14', '13']


def test_msgs_flag(gm_client, login, msgs):
    def post(uids, **data):
        web.flag(dict(uids=uids, **data))
        return [' '.join(sorted(m['flags'].split())) for m in msgs()]

    web = login()
    web.flag({'new': ['\\Seen']}, status=400)
    web.flag({'old': ['\\Seen']}, status=400)

    gm_client.add_emails([{}])
    assert [m['flags'] for m in msgs()] == ['']

    assert post(['1'], new=['\\Seen']) == ['\\Seen']
    assert post(['1'], old=['\\Seen']) == ['']

    gm_client.add_emails([{'refs': '<101@mlr>'}])
    assert [m['flags'] for m in msgs()] == ['', '']
    assert post(['1', '2'], new=['\\Seen']) == ['\\Seen', '\\Seen']
    assert post(['1'], old=['\\Seen']) == ['', '\\Seen']
    assert post(['1', '2'], old=['\\Seen']) == ['', '']

    assert post(['1', '2'], new=['#1', '#2']) == ['#1 #2', '#1 #2']
    assert post(['1', '2'], new=['#3', '#2'], old=['#1', '#2']) == [
        '#2 #3', '#2 #3'
    ]
    assert post(['1', '2'], new=['#4'], old=['#2', '#3']) == [
        '#4', '#4'
    ]


def test_search_thread(gm_client, login, some):
    def post(uid, preload=4):
        data = {'q': 'thread:%s' % uid, 'preload': preload}
        return web.search(data)

    web = login()
    assert post('1') == {
        'uids': [],
        'msgs': {},
        'msgs_info': '/msgs/info',
        'same_subject': [],
        'tags': [],
        'thread': True,
    }

    gm_client.add_emails([{}])
    res = post('1')
    assert res == {
        'uids': ['1'],
        'edit': None,
        'msgs': {'1': some},
        'msgs_info': '/msgs/info',
        'tags': [],
        'same_subject': [],
        'thread': True,
        'has_link': False,
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

    web.flag({'uids': res['uids'], 'new': ['\\Seen']})

    res = post('1', preload=2)
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '6']
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    web.flag({'uids': ['2'], 'new': ['\\Flagged']})

    res = post('1', preload=2)
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '2', '6']
    assert res['tags'] == []
    assert res['same_subject'] == ['4', '5', '6']

    web.flag({'uids': ['2'], 'new': ['#inbox', '#sent', 'test2']})
    web.flag({'uids': ['1'], 'new': ['#inbox', 'test1']})

    res = post('1', preload=None)
    assert len(res['uids']) == 6
    assert sorted(res['msgs']) == ['1', '2', '3', '4', '5', '6']
    assert res['tags'] == ['#inbox', 'test1', 'test2']
    assert [res['msgs'][uid]['tags'] for uid in sorted(res['msgs'])] == [
        [], [], [], [], [], []
    ]

    data = {'uids': res['uids'], 'hide_tags': res['tags']}
    res = web.post_json(res['msgs_info'], data, status=200).json
    assert [res[uid]['tags'] for uid in sorted(res)] == [
        [], [], [], [], [], []
    ]

    web.flag({'uids': ['2'], 'new': ['#trash']})
    q_thread = 'tag:#trash thread:2'
    res = web.search({'q': 'tag:#trash'})
    assert sorted(res['msgs']) == ['2']
    assert res['tags'] == ['#trash']
    m = res['msgs']['2']
    assert m['query_thread'] == q_thread

    res = web.search({'q': ':threads tag:#trash'})
    assert sorted(res['msgs']) == ['6']
    assert res['tags'] == ['#trash']
    m = res['msgs']['6']
    assert m['query_thread'] == 'tag:#trash thread:6'
    assert m['count'] == 1

    res = web.search({'q': q_thread})
    assert sorted(res['msgs']) == ['2']
    assert res['tags'] == ['#inbox', '#trash', 'test2']
    m = res['msgs']['2']
    assert m['query_thread'] == q_thread
    assert m['tags'] == []

    res = web.search({'q': ':threads'})
    assert sorted(res['msgs']) == ['6']
    m = res['msgs']['6']
    assert m['query_thread'] == 'thread:6'
    assert m['tags'] == ['#inbox', 'test1']
    assert m['count'] == 5

    res = post('1', preload=None)
    assert sorted(res['msgs']) == ['1', '3', '4', '5', '6']
    assert res['tags'] == ['#inbox', 'test1']


def test_drafts_part0(gm_client, login, latest, load_email, some):
    web = login()
    gm_client.add_emails([
        {'from': '"The One" <one@t.com>', 'to': 'two@t.com, three@t.com'}
    ])
    res = web.search({'q': 'thread:1'})
    assert res['uids'] == ['1']
    url_reply = res['msgs']['1']['url_reply']
    assert url_reply == '/reply/1'
    res = web.get(url_reply, status=200).json
    query_edit = res['query_edit']
    assert re.match(r'draft:\<[^>]{8}\>', query_edit)

    res = web.search({'q': 'thread:1'})
    assert res['uids'] == ['1', '2']
    draft = res['msgs']['2']
    assert 'url_reply' not in draft
    assert draft['is_draft']
    assert not draft['is_unread']
    assert draft['parent'] == '<101@mlr>'
    assert draft['query_edit'] == query_edit

    res = web.search({'q': query_edit})
    assert res['uids'] == ['1', '2']
    draft = res['edit']
    assert isinstance(draft['time'], int)
    assert draft['txt'] == ''
    assert draft['subject'] == 'Re: Subj 101'
    assert draft['from'] == ''
    assert draft['to'] == '"The One" <one@t.com>, two@t.com, three@t.com'
    assert web.body('2') == ''

    gm_client.add_emails([
        {'from': '"The Two" <two@t.com>', 'labels': '\\Sent'}
    ])
    res = web.get(url_reply, status=200).json
    res = web.search({'q': res['query_edit']})
    assert res['uids'] == ['1', '4', '2']
    draft = res['edit']
    assert draft['from'] == '"The Two" <two@t.com>'
    assert draft['to'] == '"The One" <one@t.com>, three@t.com'

    gm_client.add_emails([{'refs': '<101@mlr>', 'date': time.time() + 1}])
    res = web.search({'q': 'thread:1'})
    assert res['uids'] == ['1', '4', '2', '5']
    draft = res['msgs']['4']
    res = web.search({'q': ':threads'})
    assert res['uids'] == ['5', '3']
    assert res['msgs']['5']['query_edit'] == draft['query_edit']

    res = web.get('/compose').json
    res = web.search({'q': res['query_edit']})
    assert res['uids'] == ['6']
    draft = res['edit']
    assert draft['from'] == '"The Two" <two@t.com>'
    assert draft['to'] == ''
    assert draft['txt'] == ''
    assert draft['subject'] == ''

    m = load_email('msg-attachments-two-gmail.txt')
    res = web.get('/reply/%s' % m['uid'], {'forward': 1}).json
    res = web.search({'q': res['query_edit']})
    draft = res['edit']
    assert draft['txt'] == (
        '\r\n\r\n'
        '```\r\n'
        '---------- Forwarded message ----------\r\n'
        'Subject: Re: тема измененная\r\n'
        'Date: Mon, 3 Mar 2014 18:10:08 +0200\r\n'
        'From: "Grisha K." <naspeh@gmail.com>\r\n'
        'To: "Ne Greh" <negreh@gmail.com>\r\n'
        '```\r\n'
    )
    assert 'ответ на тело' in draft['quoted']
    assert draft['files'] == [
        {
            'filename': '08.png',
            'image': True,
            'path': '2.2',
            'size': 553,
            'url': '/raw/8/2.2/08.png'
        },
        {
            'filename': '09.png',
            'image': True,
            'path': '2.3',
            'size': 520,
            'url': '/raw/8/2.3/09.png'
        }
    ]

    forwarded = '---------- Forwarded message ----------'
    m = load_email('msg-links.txt')
    res = web.get('/reply/%s' % m['uid'], {'forward': 1}).json
    m = latest(parsed=True)
    assert m['meta']['subject'] == 'Fwd: Тестим ссылки'
    assert forwarded in m['body']
    assert 'https://github.com' in m['body']
    res = web.post('/editor', {'uid': m['uid']}, status=200).json
    m = latest(parsed=True)
    assert 'https://github.com' in m['body']

    gm_client.add_emails([{'from': 'two@t.com', 'to': 'two@t.com'}])
    m = latest(parsed=True)
    res = web.get('/reply/%s' % m['uid']).json
    res = web.search({'q': res['query_edit']})
    draft = res['edit']
    assert draft['from'] == '"The Two" <two@t.com>'
    assert draft['to'] == 'two@t.com'
    assert draft['txt'] == ''

    msg = {'from': 'a@t.com', 'to': 'b@t.com'}
    gm_client.add_emails([dict(msg, subj='')])
    m = latest(parsed=True)
    res = web.get('/reply/%s' % m['uid']).json
    m = latest(parsed=True)
    assert m['meta']['subject'] == 'Re:'
    res = web.get('/reply/%s' % m['uid']).json
    m = latest(parsed=True)
    assert m['meta']['subject'] == 'Re:'

    gm_client.add_emails([dict(msg, subj='Re[2]:')])
    m = latest(parsed=True)
    res = web.get('/reply/%s' % m['uid']).json
    m = latest(parsed=True)
    assert m['meta']['subject'] == 'Re:'

    gm_client.add_emails([dict(msg, subj='fwd: subj')])
    m = latest(parsed=True)
    res = web.get('/reply/%s' % m['uid']).json
    m = latest(parsed=True)
    assert m['meta']['subject'] == 'Re: subj'

    gm_client.add_emails([dict(msg, subj='Fwd:subj')])
    m = latest(parsed=True)
    res = web.get('/reply/%s' % m['uid']).json
    m = latest(parsed=True)
    assert m['meta']['subject'] == 'Re: subj'


def test_drafts_part1(gm_client, login, patch, some):
    web = login()
    gm_client.add_emails([
        {'flags': '\\Seen', 'mid': '<101@Mlr>'},
        {'refs': '<101@MLR>', 'flags': '\\Seen'}
    ])
    query = 'thread:1'
    assert web.search({'q': query})['uids'] == ['1', '2']

    gm_client.add_emails([{'refs': '<101@MLR>', 'flags': '\\Draft'}])
    assert web.search({'q': query})['uids'] == ['1', '3', '2']

    gm_client.add_emails([{'refs': '<102@mlr>', 'flags': '\\Seen'}] * 4)
    gm_client.add_emails([{'refs': '<104@MLR>', 'flags': '\\Draft'}])
    res = web.search({'q': query, 'preload': 2})
    assert res['uids'] == ['1', '3', '2', '4', '8', '5', '6', '7']
    assert sorted(res['msgs']) == ['1', '3', '4', '7', '8']

    gm_client.add_emails([
        {'refs': '<101@mlr>'},
        {'refs': '<109@mlr>', 'flags': '\\Draft'}
    ])
    res = web.search({'q': query, 'preload': 2})
    assert res['uids'] == ['1', '3', '2', '4', '8', '5', '6', '7', '9', '10']
    assert sorted(res['msgs']) == ['1', '10', '3', '4', '8', '9']
    assert not res['edit']

    draft = res['msgs']['3']
    assert draft['is_draft']
    assert draft['query_edit'] == 'draft:%s' % draft['draft_id']

    res = web.search({'q': draft['query_edit'], 'preload': 2})
    assert res['uids'] == ['1', '3', '2', '4', '8', '5', '6', '7', '9', '10']
    assert res['edit'] == {
        'cc': '',
        'draft_id': draft['draft_id'],
        'files': [],
        'flags': '\\Draft \\Recent',
        'from': '',
        'in-reply-to': '',
        'origin_uid': '3',
        'quoted': None,
        'references': '<101@mlr>',
        'subject': 'Subj 103',
        'time': some,
        'to': '',
        'txt': '42',
        'uid': '3',
        'url_send': '/send/3',
    }

    with patch('mailur.gmail.data_credentials') as c:
        c.get.return_value = ('test', 'test')
        with patch('mailur.web.smtplib.SMTP'):
            res = web.get('/send/3', status=400).json
    assert res == {'errors': ['"From" and "To" shouldn\'t be empty']}


def test_drafts_part2(gm_client, login, msgs, latest, patch, some):
    from webtest import Upload

    web = login()

    gm_client.add_emails([
        {'flags': '\\Seen'},
        {
            'refs': '<101@mlr>',
            'from': 'A@t.com',
            'to': 'b@t.com',
            'flags': '\\Draft \\Seen',
            'labels': 'test'
        }
    ])
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '2']
    assert [i['uid'] for i in msgs()] == ['1', '2']
    m = latest(parsed=True)
    assert m['flags'] == '\\Seen \\Draft test'
    assert m['meta']['draft_id'] == some
    draft_id = some.value
    assert re.match(r'\<[^\>]+\>', draft_id)
    assert m['body_full']['x-draft-id'] == draft_id

    res = web.post('/editor', {
        'uid': '2',
        'txt': '**test it**',
    }, status=200).json
    assert res == {'uid': '3', 'url_send': '/send/3'}
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '3']
    assert [i['uid'] for i in msgs()] == ['1', '3']
    m = latest(parsed=1)
    assert local.data_msgids.get() == {
        '<101@mlr>': ['1'],
        m['meta']['msgid']: ['3']
    }
    assert m['flags'] == '\\Seen \\Draft test'
    assert m['meta']['files'] == []
    assert m['meta']['draft_id'] == draft_id
    assert m['body_full']['x-draft-id'] == draft_id
    assert m['body_full']['from'] == 'A@t.com'
    assert m['body_full']['to'] == 'b@t.com'
    assert m['body_full']['subject'] == 'Subj 102'
    assert m['body'] == '<p><strong>test it</strong></p>'

    res = web.search({'q': 'draft:%s' % draft_id})
    assert res['edit']
    assert res['edit']['files'] == []
    addrs_from, addrs_to = local.data_addresses.get()
    assert addrs_from == {
        'a@t.com': {
            'addr': 'a@t.com',
            'hash': '671fc7fb9f958db9fdd252dfaf2325db',
            'name': 'A',
            'time': some,
            'title': 'A@t.com',
        },
    }
    assert some.value == m['meta']['date']
    assert addrs_to == {
        'a@t.com': {
            'addr': 'a@t.com',
            'hash': '671fc7fb9f958db9fdd252dfaf2325db',
            'name': 'A',
            'time': some,
            'title': 'A@t.com',
        },
        'b@t.com': {
            'addr': 'b@t.com',
            'hash': 'd2ed191b17f1b9abdfd509d877a765db',
            'name': 'b',
            'time': some,
            'title': 'b@t.com',
        }
    }

    web.post('/editor', {
        'uid': '3',
        'files': Upload('test.rst', b'txt', 'text/x-rst')
    }, status=200)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '4']
    assert [i['uid'] for i in msgs()] == ['1', '4']
    m = latest(parsed=1)
    assert local.data_msgids.get() == {
        '<101@mlr>': ['1'],
        m['meta']['msgid']: ['4']
    }
    assert m['flags'] == '\\Seen \\Draft test'
    assert m['meta']['files'] == [
        {
            'filename': 'test.rst',
            'path': '2.1',
            'size': 3,
            'url': '/raw/4/2.1/test.rst',
        }
    ]
    assert m['meta']['draft_id'] == draft_id
    assert m['body_full']['x-draft-id'] == draft_id
    assert m['body_full']['from'] == 'A@t.com'
    assert m['body_full']['to'] == 'b@t.com'
    assert m['body_full']['subject'] == 'Subj 102'
    assert m['body'] == '<p><strong>test it</strong></p>'

    res = web.search({'q': 'draft:%s' % draft_id})
    assert res['edit']
    assert res['edit']['files'] == [{
        'filename': 'test.rst',
        'path': '2.1',
        'size': 3,
        'url': '/raw/4/2.1/test.rst',
    }]

    web.post('/editor', {
        'uid': '4',
        'txt': 'Тест',
        'subject': (
            'Тема новая '
            'looooooooooooooooooooooooooooooooooooong'
        ),
        'from': '"Альфа" <a@t.com>',
        'to': (
            '"Бета" <b@t.com>,'
            '"Длинное Имя looooooooooooooooooooooooooooooooooooong" <c@t.com>'
        ),
        'files': Upload('test2.rst', b'lol', 'text/x-rst')
    }, status=200)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '5']
    assert [i['uid'] for i in msgs()] == ['1', '5']
    m = latest(parsed=1, policy=email.policy.default)
    assert m['flags'] == '\\Seen \\Draft test'
    assert m['meta']['files'] == [
        {
            'filename': 'test.rst',
            'path': '2.1',
            'size': 3,
            'url': '/raw/5/2.1/test.rst',
        },
        {
            'filename': 'test2.rst',
            'path': '2.2',
            'size': 3,
            'url': '/raw/5/2.2/test2.rst',
        },
    ]
    assert m['meta']['draft_id'] == draft_id
    assert m['body_full']['x-draft-id'] == draft_id
    assert m['body_full']['from'] == 'Альфа <a@t.com>'
    assert m['body_full']['to'] == (
        'Бета <b@t.com>, '
        'Длинное Имя looooooooooooooooooooooooooooooooooooong <c@t.com>'
    )
    assert m['body_full']['subject'] == (
        'Тема новая looooooooooooooooooooooooooooooooooooong'
    )
    assert m['body'] == '<p>Тест</p>'

    addrs_from, addrs_to = local.data_addresses.get()
    assert addrs_from == {
        'a@t.com': {
            'addr': 'a@t.com',
            'hash': '671fc7fb9f958db9fdd252dfaf2325db',
            'name': 'Альфа',
            'time': some,
            'title': '"Альфа" <a@t.com>'
        },
    }
    assert addrs_to == {
        'a@t.com': {
            'addr': 'a@t.com',
            'hash': '671fc7fb9f958db9fdd252dfaf2325db',
            'name': 'Альфа',
            'time': some,
            'title': '"Альфа" <a@t.com>'
        },
        'b@t.com': {
            'addr': 'b@t.com',
            'hash': 'd2ed191b17f1b9abdfd509d877a765db',
            'name': 'Бета',
            'time': some,
            'title': '"Бета" <b@t.com>',
        },
        'c@t.com': {
            'addr': 'c@t.com',
            'hash': 'f0af54f840071ec985f7bc9a225172dc',
            'name': 'Длинное Имя looooooooooooooooooooooooooooooooooooong',
            'time': some,
            'title': (
                '"Длинное Имя looooooooooooooooooooooooooooooooooooong" '
                '<c@t.com>'
            )
        },
    }

    with patch('mailur.gmail.data_credentials') as c:
        c.get.return_value = ('test', 'test')
        with patch('mailur.web.smtplib.SMTP.sendmail') as m:
            with patch('mailur.web.smtplib.SMTP.login'):
                res = web.get('/send/5', status=200).json
    assert m.call_args[0][:2] == (['a@t.com'], ['b@t.com', 'c@t.com'])
    body = m.call_args[0][2].decode()
    assert body.startswith('''\
Subject: =?utf-8?b?0KLQtdC80LAg0L3QvtCy0LDRjyBsb29vb29vb29vb29vb29v?=\r
 =?utf-8?b?b29vb29vb29vb29vb29vb29vb29vb25n?=\r
From: =?utf-8?b?0JDQu9GM0YTQsA==?= <a@t.com>\r
To: =?utf-8?b?0JHQtdGC0LA=?= <b@t.com>,\r
 =?utf-8?b?0JTQu9C40L3QvdC+0LUg0JjQvNGPIGxvb29vb29vb29vb29vb29vb29v?=\r
 =?utf-8?b?b29vb29vb29vb29vb29vb29vbmc=?= <c@t.com>\r
'''), body
    assert res == {'query': some}
    assert re.match(r'^:threads mid:\<.*@mailur\.sent\>', some.value)

    with patch('mailur.local.new_msg') as m:
        m.side_effect = ValueError
        web.post('/editor', {
            'uid': '5',
            'txt': 'test it',
        }, status=500)
    assert [i['uid'] for i in msgs(local.SRC)] == ['1', '5']
    assert [i['uid'] for i in msgs()] == ['1', '5']


def test_addresses(some):
    def wrap_from_list(addrs):
        return wrap_addresses(addresses(addrs), max=4)

    res = wrap_from_list('test <test@example.com>')
    assert res == [
        {
            'name': 'test',
            'addr': 'test@example.com',
            'hash': '55502f40dc8b7c769880b10874abc9d0',
            'title': '"test" <test@example.com>',
            'query': ':threads from:test@example.com',
        },
    ]

    res = wrap_from_list(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
    )
    assert ['test', 'test2'] == [a['name'] for a in res]

    res = wrap_from_list(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
    )
    assert ['test', 'test2', 'test3'] == [a['name'] for a in res]

    res = wrap_from_list(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
    )
    assert ['test', 'test2', 'test3', 'test4'] == [a['name'] for a in res]

    res = wrap_from_list(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
        'test5 <test5@example.com>,'
    )
    assert ['test', {'expander': 2}, 'test4', 'test5'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = wrap_from_list(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test4 <test4@example.com>,'
        'test5 <test5@example.com>,'
        'test <test@example.com>,'
    )
    assert [{'expander': 2}, 'test4', 'test5', 'test'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = wrap_from_list(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
        'test2 <test2@example.com>,'
    )
    assert ['test', 'test3', 'test2'] == [a['name'] for a in res]

    res = wrap_from_list(
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test <test@example.com>,'
        'test2 <test2@example.com>,'
        'test3 <test3@example.com>,'
    )
    assert ['test', 'test2', 'test3'] == [a['name'] for a in res]

    res = wrap_from_list(','.join(
        'test{0} <test{0}@example.com>'.format(i) for i in range(10)
    ))
    assert ['test0', {'expander': 7}, 'test8', 'test9'] == [
        a if 'expander' in a else a['name'] for a in res
    ]

    res = wrap_from_list(','.join(
        'test <test@example.com>' for i in range(10)
    ))
    assert ['test'] == [a['name'] for a in res]

    # other options
    addrs = addresses('test <test@example.com>')
    res = wrap_addresses(addrs, field='to')
    assert res == [{
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'name': 'test',
        'query': ':threads to:test@example.com',
        'title': '"test" <test@example.com>'
    }]
    res = wrap_addresses(addrs, field='to', base_q='tag:#trash ')
    assert res == [{
        'addr': 'test@example.com',
        'hash': '55502f40dc8b7c769880b10874abc9d0',
        'name': 'test',
        'query': 'tag:#trash :threads to:test@example.com',
        'title': '"test" <test@example.com>'
    }]


def test_query():
    end = 'unkeyword #trash unkeyword #spam'
    assert parse_query('') == (end, {})
    assert parse_query('test') == ('text "test" ' + end, {})
    assert parse_query('test1 test2') == ('text "test1 test2" ' + end, {})

    assert parse_query('thread:1') == (
        'uid 1 ' + end, {'thread': True, 'uid': '1'}
    )
    assert parse_query('thr:1') == (
        'uid 1 ' + end, {'thread': True, 'uid': '1'}
    )
    assert parse_query('THR:1') == (
        'uid 1 ' + end, {'thread': True, 'uid': '1'}
    )
    assert parse_query('thr:1 test') == (
        'uid 1 text "test" ' + end, {'thread': True, 'uid': '1'}
    )

    assert parse_query('in:#inbox') == (
        'keyword #inbox ' + end, {'tags': ['#inbox']}
    )
    assert parse_query('tag:#sent') == (
        'keyword #sent ' + end, {'tags': ['#sent']}
    )
    assert parse_query('tag:#inbox tag:#work') == (
        'keyword #inbox keyword #work ' + end, {'tags': ['#inbox', '#work']}
    )

    assert parse_query('tag:#trash') == (
        'keyword #trash', {'tags': ['#trash']}
    )
    assert parse_query('tag:#spam') == (
        'keyword #spam unkeyword #trash', {'tags': ['#spam']}
    )
    assert parse_query('in:#inbox test') == (
        'text "test" keyword #inbox ' + end, {'tags': ['#inbox']}
    )

    assert parse_query(':threads') == (end, {'threads': True})
    assert parse_query(':threads test') == (
        'text "test" ' + end, {'threads': True}
    )
    assert parse_query('test :threads') == (
        'text "test" ' + end, {'threads': True}
    )

    assert parse_query('uid:1') == ('uid 1 ' + end, {})
    assert parse_query('uid:1 :threads') == ('uid 1 ' + end, {'threads': True})

    assert parse_query('to:t@t.com') == ('to "t@t.com" ' + end, {})
    assert parse_query('from:t@t.com') == ('from "t@t.com" ' + end, {})
    assert parse_query('from:t@t.com test') == (
        'from "t@t.com" text "test" ' + end, {}
    )
    assert parse_query('subj:"test subj"') == (
        'header subject "test subj" ' + end, {}
    )
    assert parse_query('subject:"test subj" test') == (
        'header subject "test subj" text "test" ' + end, {}
    )
    assert parse_query('subj:тест?') == (
        'header subject "тест?" ' + end, {}
    )

    assert parse_query('mid:<101@mlr>') == (
        'header message-id <101@mlr> ' + end, {}
    )
    assert parse_query('message_id:<101@mlr> test') == (
        'header message-id <101@mlr> text "test" ' + end, {}
    )
    assert parse_query('ref:<_@mlr>') == (
        'or header message-id <_@mlr> header references <_@mlr> ' + end,
        {'thread': True}
    )

    assert parse_query(':raw text in:#spam') == ('text in:#spam ' + end, {})

    assert parse_query(':draft') == ('draft ' + end, {'flags': ['draft']})
    assert parse_query(':unread') == ('unseen ' + end, {'flags': ['unseen']})
    assert parse_query(':unseen') == ('unseen ' + end, {'flags': ['unseen']})
    assert parse_query(':seen') == ('seen ' + end, {'flags': ['seen']})
    assert parse_query(':read') == ('seen ' + end, {'flags': ['seen']})
    assert parse_query(':pinned') == ('flagged ' + end, {'flags': ['flagged']})
    assert parse_query(':unpinned') == (
        'unflagged ' + end, {'flags': ['unflagged']}
    )
    assert parse_query(':flagged') == (
        'flagged ' + end, {'flags': ['flagged']}
    )
    assert parse_query(':unflagged') == (
        'unflagged ' + end, {'flags': ['unflagged']}
    )
    assert parse_query(':pin :unread') == (
        'flagged unseen ' + end, {'flags': ['flagged', 'unseen']}
    )

    assert parse_query('date:2007') == (
        'since 01-Jan-2007 before 01-Jan-2008 ' + end, {}
    )
    assert parse_query('date:2007-04') == (
        'since 01-Apr-2007 before 01-May-2007 ' + end, {}
    )
    assert parse_query('date:2007-04-01') == ('on 01-Apr-2007 ' + end, {})

    assert parse_query('draft:<12345678>') == (
        'header message-id <12345678> ' + end,
        {'draft': '<12345678>', 'thread': True}
    )


def test_nginx(web, login, patch):
    web.get('/nginx', status=400)

    res = web.get('/nginx', status=200, headers={
        'Auth-User': login.user1,
        'Auth-Pass': 'user',
        'Auth-Protocol': 'imap'
    })
    assert dict(res.headers) == {
        'Auth-Port': '143',
        'Auth-Server': '127.0.0.1',
        'Auth-Status': 'OK',
        'Content-Length': '0',
        'Content-Type': 'text/html; charset=UTF-8'
    }

    res = web.get('/nginx', status=200, headers={
        'Auth-User': login.user1,
        'Auth-Pass': 'user',
        'Auth-Protocol': 'smtp'
    })
    assert dict(res.headers) == {
        'Auth-Port': '25',
        'Auth-Server': '127.0.0.1',
        'Auth-Status': 'OK',
        'Content-Length': '0',
        'Content-Type': 'text/html; charset=UTF-8'
    }

    res = web.get('/nginx', status=200, headers={
        'Auth-User': login.user1,
        'Auth-Pass': 'wrong',
        'Auth-Protocol': 'imap'
    })
    assert dict(res.headers) == {
        'Auth-Status': "b'[AUTHENTICATIONFAILED] Authentication failed.'",
        'Auth-Wait': '3',
        'Content-Length': '0',
        'Content-Type': 'text/html; charset=UTF-8'
    }

    disabled = {
        'Auth-Status': 'Disabled',
        'Auth-Wait': '3',
        'Content-Length': '0',
        'Content-Type': 'text/html; charset=UTF-8'
    }
    with patch.dict('mailur.web.conf', {'IMAP_OFF': [login.user1]}):
        res = web.get('/nginx', status=200, headers={
            'Auth-User': login.user1,
            'Auth-Pass': 'user',
            'Auth-Protocol': 'imap'
        })
        assert dict(res.headers) == disabled
        res = web.get('/nginx', status=200, headers={
            'Auth-User': login.user1,
            'Auth-Pass': 'user',
            'Auth-Protocol': 'smtp'
        })
        assert dict(res.headers) == disabled


def test_privacy(gm_client, login, load_email):
    web = login()

    headers = '\r\n'.join([
        'Date: Wed, 07 Jan 2015 13:23:22 +0000',
        'From: katya@example.com',
        'To: grrr@example.com',
        'MIME-Version: 1.0',
        'Content-type: text/html; charset=utf-8',
        'Content-Transfer-Encoding: 8bit',
    ])

    raw = '\r\n'.join([
        headers,
        'Message-ID: <richer-styles-and-imgs@test>',
        'Subject: styles and images',
        ''
        '<p style="color:red">test html</p>',
        '<img src="https://github.com/favicon.ico" />'
    ])
    gm_client.add_emails([{'raw': raw.encode()}])
    uid, info = web.search({'q': ':raw all'})['msgs'].popitem()
    assert info['richer'] == 'Show styles and 1 external images'
    body = web.body(uid)
    assert 'data-src="/proxy?url=https://github.com' in body
    assert ' style="color:red"' not in body
    assert 'data-style="color:red"' in body
    body = web.body(uid, False)
    assert body == (
        '<p style="color:red">test html</p>\r\n'
        '<img src="/proxy?url=https://github.com/favicon.ico">'
    )

    # embend shouldn't be replaced with proxy url
    m = load_email('msg-embeds-one-gmail.txt', parsed=True)
    uid, info = web.search({'q': 'uid:%s' % m['uid']})['msgs'].popitem()
    assert 'richer' not in info

    body = web.body(uid)
    src = 'src="/raw/%s/2/50.png"' % m['meta']['origin_uid']
    assert src in body
