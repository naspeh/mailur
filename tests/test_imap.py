from unittest.mock import patch, call, ANY

from mailur import imap


@patch('mailur.imap.select')
def test_basic_gmail(select):
    gm = imap.Gmail()
    assert select.call_args == call(ANY, b'All', True)

    gm.select_tag('\\Junk')
    assert select.call_args == call(ANY, b'V/Spam', True)

    gm.select_tag('\\Trash')
    assert select.call_args == call(ANY, b'V/Trash', True)


def test_fn_parse_thread():
    fn = imap.parse_thread
    assert fn('(1)(2 3)') == [['1'], ['2', '3']]
    assert fn('(11)(21 31)') == [['11'], ['21', '31']]
    assert fn('(1)(2 3 (4 5))') == [['1'], '2 3 4 5'.split()]
    assert fn('(130 131 (132 133 134 (138)(139)(140)))') == [
        '130 131 132 133 134 138 139 140'.split()
    ]
    assert fn(b'(1)(2)(3)') == [['1'], ['2'], ['3']]


def test_fn_pack_uids():
    fn = imap.pack_uids
    assert fn(['1', '2', '3', '4']) == '1:4'
    assert fn(['1', '3', '4']) == '1,3:4'
    assert fn(['100', '1', '4', '3', '10', '9', '8', '7']) == '1,3:4,7:10,100'
