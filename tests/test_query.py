from pytest import mark

from core.views import parse_query


@mark.parametrize('query, expected', [
    ('', (
        "SELECT id, id AS sort FROM emails"
        " WHERE labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
    ('subj:Test%', (
        "SELECT id, id AS sort FROM emails"
        " WHERE subj LIKE 'Test%' AND labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
    ('subj:"Test subj"', (
        "SELECT id, id AS sort FROM emails"
        " WHERE subj LIKE 'Test subj' AND labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
    ('show:few', (
        "SELECT id, id AS sort FROM emails"
        " WHERE labels @> ARRAY['\\All']::varchar[]",
        {'few': True, 'labels': ['\\All']}
    )),
    ('in:\\Inbox show:all', (
        "SELECT id, id AS sort FROM emails"
        " WHERE labels @> ARRAY['\\Inbox']::varchar[]",
        {'few': False, 'labels': ['\\Inbox']}
    )),
    ('in:\\Inbox', (
        "SELECT id, id AS sort FROM emails"
        " WHERE labels @> ARRAY['\\Inbox']::varchar[]",
        {'few': True, 'labels': ['\\Inbox']}
    )),
    ('in:"test box"', (
        "SELECT id, id AS sort FROM emails"
        " WHERE labels @> ARRAY['\\All', 'test box']::varchar[]",
        {'few': False, 'labels': ['\\All', 'test box']}
    )),
    ('in:\\Spam', (
        "SELECT id, id AS sort FROM emails"
        " WHERE labels @> ARRAY['\\Spam']::varchar[]",
        {'few': False, 'labels': ['\\Spam']}
    )),
    ('in:\\Inbox,\\Unread', (
        "SELECT id, id AS sort FROM emails"
        " WHERE labels @> ARRAY['\\Inbox', '\\Unread']::varchar[]",
        {'few': False, 'labels': ['\\Inbox', '\\Unread']}
    )),
    ('in:\\Inbox subj:"Test 1"', (
        "SELECT id, id AS sort FROM emails"
        " WHERE subj LIKE 'Test 1' AND labels @> ARRAY['\\Inbox']::varchar[]",
        {'few': False, 'labels': ['\\Inbox']}
    )),
    ('from:user@test.com', (
        "SELECT id, id AS sort FROM emails"
        " WHERE array_to_string(fr, ',') LIKE '%<user@test.com>%'"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
    ('to:user@test.com', (
        "SELECT id, id AS sort FROM emails"
        " WHERE array_to_string(\"to\" || cc, ',') LIKE '%<user@test.com>%'"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
    ('person:q@test.com', (
        "SELECT id, id AS sort FROM emails"
        " WHERE array_to_string(\"to\" || cc || fr, ',') LIKE '%<q@test.com>%'"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
    ('test', (
        "SELECT id, ts_rank(search, plainto_tsquery('simple', 'test')) AS sort"
        " FROM emails"
        " WHERE search @@ (plainto_tsquery('simple', 'test'))"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
    ('t subj:Test t2', (
        "SELECT id, ts_rank(search, plainto_tsquery('simple', 't t2')) AS sort"
        " FROM emails"
        " WHERE subj LIKE 'Test'"
        " AND search @@ (plainto_tsquery('simple', 't t2'))"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'few': False, 'labels': ['\\All']}
    )),
])
def test_parsing(env, query, expected):
    result = parse_query(env, query)
    assert result == expected

    env.sql('{} ORDER BY sort'.format(result[0])).fetchone()
