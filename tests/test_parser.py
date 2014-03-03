from pytest import mark

from . import read_file
from mailr import parser

emails = read_file('files_parser', 'expected.json').items()


@mark.parametrize('path, expected', emails)
def test_emails(path, expected):
    raw = read_file('files_parser', path)
    result = parser.parse_header(raw)
    assert expected['subject'] == result['subject']

    result = parser.parse(raw)
    for type_ in ['text/plain', 'text/html']:
        if expected.get(type_):
            assert type_ in result
            assert expected[type_] in result[type_]

    if expected.get('attachments'):
        assert 'attachments' in result
        assert len(expected['attachments']) == len(result['attachments'])
        assert expected['attachments'] == [
            [a['content_type'], a['filename']] for a in result['attachments']
        ]
