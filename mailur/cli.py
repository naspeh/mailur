"""Mailur CLI

Usage:
  mailur -l<login> gmail <username> <password> [--parse -t<threads> -b<batch>]
  mailur -l<login> parse [<criteria> -t<threads> -b<batch>]
  mailur -l<login> threads [<criteria>]
  mailur icons
  mailur web
  mailur lint [--ci]
  mailur test -- [<options>...]

Options:
  -h --help     Show this screen.
  --version     Show version.
  -l <login>    Local user (for dovecot).
  -b <batch>    Batch size [default: 1000].
  -t <threads>  Amount of threads for thread pool [default: 2].
"""
from pathlib import Path

from docopt import docopt

from . import gmail, local

root = Path(__file__).parent.parent


def main():
    args = docopt(__doc__, version='Mailur 0.3')
    try:
        process(args)
    except KeyboardInterrupt:
        raise SystemExit('^C')


def process(args):
    local.USER = args['-l']
    opts = {
        'batch': int(args.get('-b')),
        'threads': int(args.get('-t')),
    }
    if args['gmail']:
        gmail.USER = args['<username>']
        gmail.PASS = args['<password>']
        gmail.fetch(**opts)
        if args.get('--parse'):
            local.parse(**opts)
    elif args['parse']:
        # local.save_msgids()
        # local.save_uid_pairs()
        local.parse(args.get('<criteria>'), **opts)
    elif args['threads']:
        with local.client() as con:
            local.update_threads(con, criteria=args.get('<criteria>'))
    elif args['icons']:
        icons()
    elif args['web']:
        web()
    elif args['test']:
        opts = ' '.join(args['<options>'])
        run('pytest %r' % opts)
    elif args['lint']:
        ci = args['--ci'] and 1 or ''
        run('ci=%s bin/lint' % ci)
    else:
        raise SystemExit('Target not defined:\n%s' % args)


def web():
    import time
    from gevent.subprocess import run
    from gevent.pool import Pool

    def api():
        cmd = (
            'gunicorn mailur.web:app -b :5000 '
            ' -k gevent --timeout=300 --reload --access-logfile=-'
            ' --access-logformat="%(m)s %(U)s %(s)s %(L)ss %(b)sb"'
        )
        run(cmd, shell=True)

    def webpack():
        run('webpack --config=assets/webpack.config.js -w', shell=True)

    try:
        pool = Pool()
        pool.spawn(api)
        pool.spawn(webpack)
        pool.join()
    except KeyboardInterrupt:
        time.sleep(1)


def run(cmd):
    from subprocess import call

    check = 'which pytest'
    if call(check, cwd=root, shell=True):
        raise SystemExit(
            'Test dependencies must be installed.\n'
            '$ pip install -e .[test]'
        )

    cmd = 'sh -xc %r' % cmd
    call(cmd, cwd=root, shell=True)


def icons():
    import json
    import bottle

    font = root / 'assets/font'
    sel = (font / 'selection.json').read_text()
    sel = json.loads(sel)
    icons = [
        (i['properties']['name'], '\\%s' % hex(i['properties']['code'])[2:])
        for i in sel['icons']
    ]
    tpl = (font / 'icons.less.txt').resolve()
    txt = bottle.template(str(tpl), icons=icons)
    f = font / 'icons.less'
    f.write_text(txt)
    print('%s updated' % f)


if __name__ == '__main__':
    main()
