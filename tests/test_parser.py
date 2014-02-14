from . import read_file
from mailr import parser


def test_subjects():
    emails = read_file('emails', 'expect.json')

    def check(a, b):
        assert a == b

    for path, expect in emails.items():
        raw = read_file('emails', path).decode()
        result = parser.parse_header(raw)
        yield check, expect['subject'], result['subject']
