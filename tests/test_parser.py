from . import read_file
from mailr import parser


def test_subjects():
    emails = read_file('files_parser', 'expect.json')

    def check(a, b):
        assert a == b

    for path, expect in emails.items():
        raw = read_file('files_parser', path)
        result = parser.parse_header(raw.decode())
        yield check, expect['subject'], result['subject']
