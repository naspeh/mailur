from unittest.mock import ANY

from mailur.app import from_pics


def test_from_pics():
    res = from_pics([('test', 'test@example.com')])
    assert res == [{
        'src': (
            '//www.gravatar.com/avatar/55502f40dc8b7c769880b10874abc9d0'
            '?d=identicon&s=20'
        ),
        'title': 'test <test@example.com>'
    }]

    res = from_pics([
        ('test', 'test@example.com'),
        ('test2', 'test@example.com'),
    ])
    assert res == [
        {'src': ANY, 'title': 'test <test@example.com>'},
        {'src': ANY, 'title': 'test2 <test@example.com>'},
    ]

    res = from_pics([
        ('test', 'test@example.com'),
        ('test2', 'test@example.com'),
        ('test3', 'test@example.com'),
    ])
    assert res == [
        {'src': ANY, 'title': 'test <test@example.com>'},
        {'src': ANY, 'title': 'test2 <test@example.com>'},
        {'src': ANY, 'title': 'test3 <test@example.com>'},
    ]

    res = from_pics([
        ('test', 'test@example.com'),
        ('test2', 'test@example.com'),
        ('test3', 'test@example.com'),
        ('test4', 'test@example.com'),
    ])
    assert res == [
        {'src': ANY, 'title': 'test <test@example.com>'},
        {'src': ANY, 'title': 'test2 <test@example.com>'},
        {'src': ANY, 'title': 'test3 <test@example.com>'},
        {'src': ANY, 'title': 'test4 <test@example.com>'},
    ]

    res = from_pics([
        ('test', 'test@example.com'),
        ('test2', 'test@example.com'),
        ('test3', 'test@example.com'),
        ('test4', 'test@example.com'),
        ('test5', 'test@example.com'),
    ])
    assert res == [
        {'src': ANY, 'title': 'test <test@example.com>'},
        {'expander': '2 more'},
        {'src': ANY, 'title': 'test4 <test@example.com>'},
        {'src': ANY, 'title': 'test5 <test@example.com>'},
    ]

    res = from_pics([('test', 'test@example.com')] * 10)
    assert res == [
        {'src': ANY, 'title': 'test <test@example.com>'},
        {'expander': '7 more'},
        {'src': ANY, 'title': 'test <test@example.com>'},
        {'src': ANY, 'title': 'test <test@example.com>'},
    ]
