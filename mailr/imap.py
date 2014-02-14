import re
from collections import OrderedDict


def fetch(im, ids, query):
    status, data = im.uid('fetch', ','.join(ids), query)

    idata = iter(data)
    keys = query[1:-1].split()

    re_keys = r'|'.join([re.escape(k) for k in keys])
    re_noesc = r'[^\\](?:\\\\)*'
    re_list = r'("(.+?%s)"|[^ ]+)' % re_noesc
    re_full = r'(%s) ((\d+)|({\d+})|(\(%s\)))' % (re_keys, re_list)
    lexer_list = re.compile(re_list)
    lexer_full = re.compile(re_full)

    def parse(item, row):
        if isinstance(item, tuple):
            line = item[0]
        else:
            line = item

        matches = lexer_full.findall(line.decode())
        if matches:
            for match in matches:
                key, value = match[0:2]
                if match[2]:
                    row[key] = int(value)
                elif match[3]:
                    row[key] = item[1]
                    row = parse(next(idata), row)
                elif match[4]:
                    value_ = value[1:-1]
                    value_ = lexer_list.findall(value_)
                    value_ = [v[1] if v[1] else v[0] for v in value_]
                    row[key] = value_
        return row

    rows = OrderedDict()
    for id in ids:
        row = parse(next(idata), {})
        rows[row['UID']] = row
    return rows