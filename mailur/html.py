import re
from html import escape
from urllib.parse import urlencode

from lxml.html import fromstring, tostring
from lxml.html.clean import Cleaner, autolink

import mistune

from pygments import highlight
from pygments.formatters import html
from pygments.lexers import get_lexer_by_name


class HighlightRenderer(mistune.Renderer):
    def block_code(self, code, lang):
        if not lang:
            return '\n<pre><code>%s</code></pre>\n' % \
                mistune.escape(code)
        lexer = get_lexer_by_name(lang, stripall=True)
        formatter = html.HtmlFormatter()
        return highlight(code, lexer, formatter)


renderer = HighlightRenderer(escape=False, hard_wrap=True)
markdown = mistune.Markdown(renderer=renderer)


def clean(htm, embeds):
    htm = re.sub(r'^\s*<\?xml.*?\?>', '', htm).strip()
    if not htm:
        return '', {}

    cleaner = Cleaner(
        links=False,
        style=True,
        inline_style=False,
        kill_tags=['head'],
        remove_tags=['html', 'base'],
        safe_attrs=list(set(Cleaner.safe_attrs) - {'class'}) + ['style'],
    )
    htm = fromstring(htm)
    htm = cleaner.clean_html(htm)

    ext_images = 0
    for img in htm.xpath('//img[@src]'):
        src = img.attrib.get('src')
        cid = re.match('^cid:(.*)', src)
        url = cid and embeds.get('<%s>' % cid.group(1))
        if url:
            img.attrib['src'] = url
        elif re.match('^data:image/.*', src):
            pass
        elif re.match('^(https?://|//).*', src):
            ext_images += 1
            proxy_url = '/proxy?' + urlencode({'url': src})
            img.attrib['data-src'] = proxy_url
            del img.attrib['src']
        else:
            del img.attrib['src']

    styles = False
    for el in htm.xpath('//*[@style]'):
        el.attrib['data-style'] = el.attrib['style']
        del el.attrib['style']
        styles = True

    fix_links(htm)

    richer = ['styles'] if styles else []
    if ext_images:
        richer.append('%s external images' % ext_images)
    richer = ('Show %s' % ' and '.join(richer)) if richer else ''

    htm = tostring(htm, encoding='utf-8').decode().strip()
    htm = re.sub('(^<div>|</div>$)', '', htm)
    return htm, {'richer': richer} if richer else {}


def fix_links(doc):
    autolink(doc)
    for link in doc.xpath('//a[@href]'):
        link.attrib['target'] = '_blank'
    return doc


def from_text(txt):
    def replace(match):
        txt = match.group()
        if '\n' in txt:
            return '<br>' * txt.count('\n')
        else:
            return '&nbsp;' * txt.count(' ')

    tpl = '<p>%s</p>'
    htm = escape(txt)
    htm = fromstring(tpl % htm)
    fix_links(htm)
    htm = tostring(htm, encoding='utf-8').decode()
    htm = htm[3:-4]
    htm = re.sub('(?m)((\r?\n)+| [ ]+|^ )', replace, htm)
    htm = tpl % htm
    return htm


def to_text(htm):
    htm = fromstring(htm)
    return '\n'.join(escape(i) for i in htm.xpath('//text()') if i)


def to_line(htm, limit=200):
    txt = to_text(htm)
    txt = re.sub('([\s ]|&nbsp;)+', ' ', txt)
    return txt[:limit]
