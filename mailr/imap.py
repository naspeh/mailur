import imaplib
import re
from collections import OrderedDict

from . import Timer, log

re_noesc = r'(?:(?:(?<=[^\\][\\])(?:\\\\)*")|[^"])*'


def client():
    conf = __import__('conf')
    im = imaplib.IMAP4_SSL('imap.gmail.com')
    im.login(conf.username, conf.password)
    return im


def store(im, uids, key, value, rm=True):
    key = '%s%s' % (('-' if rm else '+'), key)
    for uid in uids:
        _, data = im.uid('SEARCH', None, '(X-GM-MSGID %s)' % uid)
        uid_ = data[0].decode().split(' ')[0]
        res = im.uid('STORE', uid_, key, value)
        log.info('imap.store(%r, %r): %s', key, value, res)
    return


def list_(im):
    _, data = im.list()

    re_line = r'^[(]([^)]+)[)] "([^"]+)" "(%s)"$' % re_noesc
    lexer_line = re.compile(re_line)
    rows = []
    for line in data:
        matches = lexer_line.match(line.decode())
        row = matches.groups()
        row = tuple(row[0].split()), row[1], row[2]
        rows.append(row)
    return rows


def status(im, name, readonly=True):
    name = '"%s"' % name
    im.select(name, readonly=readonly)

    uid_next = 'UIDNEXT'
    _, data = im.status(name, '(%s)' % uid_next)
    lexer_uid = re.compile(r'[(]%s (\d+)[)]' % uid_next)
    matches = lexer_uid.search(data[0].decode())
    uid = int(matches.groups()[0])
    return uid


def search(im, name):
    uid_next = status(im, name)
    uids, step = [], 5000
    for i in range(1, uid_next, step):
        _, data = im.uid('SEARCH', None, '(UID %d:%d)' % (i, i + step - 1))
        if data[0]:
            uids += data[0].decode().split(' ')
    return uids


def fetch(im, uids, query, batch_size=500, label='some updates', quiet=False):
    steps = range(0, len(uids), batch_size)
    log_ = (lambda *a, **kw: None) if quiet else log.info
    log_('  * Fetch (%d) %d ones with %s...', len(steps), len(uids), query)

    timer = Timer()
    for num, i in enumerate(steps, 1):
        uids_ = uids[i: i + batch_size]
        if not uids_:
            continue
        data_ = _fetch(im, uids_, query)
        log_('  - (%d) %d ones for %.2fs', num, len(uids_), timer.time())
        yield data_
        log_('  - %s for %.2fs', label, timer.time())


def fetch_all(*args, **kwargs):
    data = OrderedDict()
    for data_ in fetch(*args, **kwargs):
        data.update(data_)
    return data


def _fetch(im, ids, query):
    if not isinstance(query, str):
        keys = list(query)
        query = ' '.join(query)
    else:
        keys = query.split()

    status, data_ = im.uid('fetch', ','.join(ids), '(%s)' % query)

    data = iter(data_)
    if 'UID' not in keys:
        keys.append('UID')

    re_keys = r'|'.join([re.escape(k) for k in keys])
    re_list = r'("(%s)"|[^ )"]+)' % re_noesc
    lexer_list = re.compile(re_list)
    lexer_line = re.compile(
        r'(%s) ((\d+)|({\d+})|"([^"]+)"|([(]( ?%s ?)*[)]))'
        % (re_keys, re_list)
    )

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
                    row[key] = value
                elif match[5]:
                    unesc = lambda v: re.sub(r'\\(.)', r'\1', v)
                    value_ = value[1:-1]
                    value_ = lexer_list.findall(value_)
                    value_ = [unesc(v[1]) if v[1] else v[0] for v in value_]
                    row[key] = value_
        return row

    rows = OrderedDict()
    for i in range(len(ids)):
        row = parse(next(data), {})
        rows[str(row['UID'])] = row
    return rows
