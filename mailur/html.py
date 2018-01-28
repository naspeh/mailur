import re
from html import escape
from urllib.parse import urlencode

from lxml.html import fromstring, tostring
from lxml.html.clean import Cleaner, autolink


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
        # clean data-src attribute if exists
        if img.attrib.get('data-src'):
            del img.attrib['data-src']

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
        # clean data-src attribute if exists
        if el.attrib.get('data-style'):
            del el.attrib['data-style']
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

    htm = escape(txt)
    htm = re.sub('(?m)((\r?\n)*|^[ ]*)', replace, htm)
    htm = fromstring(htm)
    fix_links(htm)
    htm = tostring(htm, encoding='utf-8').decode()
    return htm


def to_text(htm):
    htm = fromstring(htm)
    return '\n'.join(escape(i) for i in htm.xpath('//text()') if i)


def to_line(htm, limit=200):
    txt = to_text(htm)
    txt = re.sub('([\s ]|&nbsp;)+', ' ', txt)
    return txt[:limit]
