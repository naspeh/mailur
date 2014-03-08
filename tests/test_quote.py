from lxml import etree
from pytest import mark

from . import open_file
from mailr.parser import hide_quote


@mark.parametrize('id', [1457489417718057053, 1456781505677497494])
def test_thread_with_quotes(id):
    with open_file('files_quote', '%s.html' % id) as f:
        thread = etree.fromstring(f.read().decode())

    mails = []
    for mail in thread.xpath('mail'):
        subj_ = mail.xpath('subject')[0].text
        text_ = mail.xpath('text')[0].text
        html_ = mail.xpath('html')[0].text
        mails.append({'subj': subj_, 'html': html_, 'text': text_})

    class_ = 'email_quote'
    for i in range(1, len(mails)):
        res = hide_quote(mails[i]['html'], mails[i - 1]['html'], class_)
        assert 'class="%s"' % class_ in res
