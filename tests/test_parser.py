from pytest import mark

from . import read_file
from mailr import parser

emails = read_file('files_parser', 'expected.json').items()


@mark.parametrize('path, expected', emails)
def test_emails(path, expected):
    raw = read_file('files_parser', path)
    result = parser.parse(raw, 'test')
    assert expected['subject'] == result['subject']

    for type_ in ['html']:
        if expected.get(type_):
            assert type_ in result
            assert expected[type_] in result[type_]
            assert result[type_].count(expected[type_]) == 1

    if expected.get('attachments'):
        assert 'attachments' in result
        assert len(expected['attachments']) == len(result['attachments'])
        assert expected['attachments'] == result['attachments']
