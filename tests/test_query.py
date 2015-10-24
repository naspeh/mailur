from pytest import mark

from core.views import parse_query


@mark.parametrize('query, expected', [
    ('', ''),
    ('subj:Test%', "WHERE subj LIKE 'Test%'"),
    ('subj:"Test subj"', "WHERE subj LIKE 'Test subj'"),
    ('in:\\Inbox', "WHERE labels @> ARRAY['\\Inbox']::varchar[]"),
    ('in:\\Inbox,\\Unread', (
        "WHERE labels @> ARRAY['\\Inbox', '\\Unread']::varchar[]"
    )),
    ('in:\\Inbox subj:"Test subj"', (
        "WHERE labels @> ARRAY['\\Inbox']::varchar[] AND subj LIKE 'Test subj'"
    )),
    ('from:user@test.com', (
        "WHERE array_to_string(fr, ',') LIKE '%<user@test.com>%'"
    )),
    ('to:user@test.com', (
        "WHERE array_to_string(\"to\" || cc, ',') LIKE '%<user@test.com>%'"
    )),
    ('person:q@test.com', (
        "WHERE array_to_string(\"to\" || cc || fr, ',') LIKE '%<q@test.com>%'"
    )),
    ('test', (
        "WHERE search @@ (plainto_tsquery('simple', 'test'))"
        " ORDER BY ts_rank(search, plainto_tsquery('simple', 'test')) DESC"
    )),
    ('t1 subj:Test t2', (
        "WHERE subj LIKE 'Test'"
        " AND search @@ (plainto_tsquery('simple', 't1 t2'))"
        " ORDER BY ts_rank(search, plainto_tsquery('simple', 't1 t2')) DESC"
    )),
])
def test_parsing(env, query, expected):
    result = parse_query(env, query)
    assert result == expected

    env.sql('SELECT id FROM emails %s' % result).fetchone()
