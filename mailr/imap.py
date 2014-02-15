import re
from collections import OrderedDict

re_noesc = r'[^\\](?:\\\\)*'


def list_(im):
    data = im.list()

    re_line = r'^[(]([^)]+)[)] "([^"]+)" "(.*%s)"$' % re_noesc
    lexer_line = re.compile(re_line)
    rows = []
    for line in data:
        matches = lexer_line.match(line.decode())
        row = matches.groups()
        row = tuple(row[0].split()), row[1], row[2]
        rows.append(row)
    return rows


def fetch(im, ids, query):
    status, data = im.uid('fetch', ','.join(ids), query)

    data = iter(data)
    keys = query[1:-1].split()
    if 'UID' not in keys:
        keys.append('UID')

    re_keys = r'|'.join([re.escape(k) for k in keys])
    re_list = r'("(.+?%s)"|[^ ]+)' % re_noesc
    re_line = r'(%s) ((\d+)|({\d+})|([(].*%s[)]))' % (re_keys, re_noesc)
    lexer_list = re.compile(re_list)
    lexer_line = re.compile(re_line)

    def parse(item, row):
        if isinstance(item, tuple):
            line = item[0]
        else:
            line = item

        matches = lexer_line.findall(line.decode())
        if matches:
            for match in matches:
                key, value = match[0:2]
                if match[2]:
                    row[key] = int(value)
                elif match[3]:
                    row[key] = item[1]
                    row = parse(next(data), row)
                elif match[4]:
                    unesc = lambda v: re.sub(r'\\(.)', r'\1', v)
                    value_ = value[1:-1]
                    value_ = lexer_list.findall(value_)
                    value_ = [unesc(v[1]) if v[1] else v[0] for v in value_]
                    row[key] = value_
        return row

    rows = OrderedDict()
    for id in ids:
        row = parse(next(data), {})
        rows[row['UID']] = row
    return rows
