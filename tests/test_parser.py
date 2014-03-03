from . import read_file, ok
from mailr import parser


def test_subjects():
    emails = read_file('files_parser', 'expected.json')
    for path, expected in emails.items():
        raw = read_file('files_parser', path)
        result = parser.parse_header(raw)
        yield ok, 'a == b', dict(a=expected['subject'], b=result['subject'])
        result = parser.parse(raw)
        yield ok, 'a in b', dict(a=expected['body'], b=result['body'])
