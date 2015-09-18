import json

from pytest import mark

from . import read_file
from mailur import syncer

emails = read_file('files_parser', 'expected.json').items()


@mark.parametrize('path, expected', emails)
def test_emails(env, path, expected):
    raw = read_file('files_parser', path)
    result = dict(syncer.get_parsed(env, raw, 'test'))
    assert expected['subject'] == result['subj']

    for type_ in ['html', 'text']:
        if expected.get(type_):
            assert type_ in result
            assert expected[type_] in result[type_]
            assert result[type_].count(expected[type_]) == 1

    if expected.get('attachments'):
        assert 'attachments' in result
        attachments = json.loads(result['attachments'])
        assert len(expected['attachments']) == len(attachments)
        assert expected['attachments'] == attachments

    if expected.get('from'):
        assert 'fr' in result
        assert expected['from'] == list(result['fr'])

    if expected.get('refs'):
        assert 'refs' in result
        assert expected['refs'] == result['refs']
