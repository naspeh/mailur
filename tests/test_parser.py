from . import read_file, ok
from mailr import parser


def test_subjects():
    emails = read_file('files_parser', 'expect.json')

    for path, expect in emails.items():
        raw = read_file('files_parser', path)
        result = parser.parse_header(raw)
        yield ok, expect['subject'], result['subject']
