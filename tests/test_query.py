from pytest import mark

from core.views import parse_query


@mark.parametrize('query, expected', [
    ('', (
        "SELECT id FROM emails"
        " WHERE labels @> ARRAY['\\All']::varchar[]",
        {'labels': ['\\All']}
    )),
    ('subj:Test%', (
        "SELECT id FROM emails"
        " WHERE subj LIKE 'Test%' AND labels @> ARRAY['\\All']::varchar[]",
        {'labels': ['\\All']}
    )),
    ('subj:"Test subj"', (
        "SELECT id FROM emails"
        " WHERE subj LIKE 'Test subj' AND labels @> ARRAY['\\All']::varchar[]",
        {'labels': ['\\All']}
    )),
    ('in:\\Inbox', (
        "SELECT id FROM emails"
        " WHERE labels @> ARRAY['\\Inbox']::varchar[]",
        {'labels': ['\\Inbox']}
    )),
    ('in:"test box"', (
        "SELECT id FROM emails"
        " WHERE labels @> ARRAY['\\All', 'test box']::varchar[]",
        {'labels': ['\\All', 'test box']}
    )),
    ('in:\\Spam', (
        "SELECT id FROM emails"
        " WHERE labels @> ARRAY['\\Spam']::varchar[]",
        {'labels': ['\\Spam']}
    )),
    ('in:\\Inbox,\\Unread', (
        "SELECT id FROM emails"
        " WHERE labels @> ARRAY['\\Inbox', '\\Unread']::varchar[]",
        {'labels': ['\\Inbox', '\\Unread']}
    )),
    ('in:\\Inbox subj:"Test 1"', (
        "SELECT id FROM emails"
        " WHERE subj LIKE 'Test 1' AND labels @> ARRAY['\\Inbox']::varchar[]",
        {'labels': ['\\Inbox']}
    )),
    ('from:user@test.com', (
        "SELECT id FROM emails"
        " WHERE array_to_string(fr, ',') LIKE '%<user@test.com>%'"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'labels': ['\\All']}
    )),
    ('to:user@test.com', (
        "SELECT id FROM emails"
        " WHERE array_to_string(\"to\" || cc, ',') LIKE '%<user@test.com>%'"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'labels': ['\\All']}
    )),
    ('person:q@test.com', (
        "SELECT id FROM emails"
        " WHERE array_to_string(\"to\" || cc || fr, ',') LIKE '%<q@test.com>%'"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'labels': ['\\All']}
    )),
    ('test', (
        "SELECT id, ts_rank(search, plainto_tsquery('simple', 'test')) AS sort"
        " FROM emails"
        " WHERE search @@ (plainto_tsquery('simple', 'test'))"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'order_by': 'sort', 'labels': ['\\All']}
    )),
    ('t subj:Test t2', (
        "SELECT id, ts_rank(search, plainto_tsquery('simple', 't t2')) AS sort"
        " FROM emails"
        " WHERE subj LIKE 'Test'"
        " AND search @@ (plainto_tsquery('simple', 't t2'))"
        " AND labels @> ARRAY['\\All']::varchar[]",
        {'order_by': 'sort', 'labels': ['\\All']}
    )),
])
def test_parsing(env, query, expected):
    result = parse_query(env, query)
    assert result == expected

    order_by = result[1].get('order_by', 'id')
    env.sql('{} ORDER BY {} DESC'.format(result[0], order_by)).fetchone()
