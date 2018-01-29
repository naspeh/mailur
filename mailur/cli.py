"""Mailur CLI

Usage:
  mlr gmail <login> [(set <username> <password>) --parse -t<threads> -b<batch>]
  mlr parse <login> [<criteria> -t<threads> -b<batch>]
  mlr threads <login> [<criteria>]
  mlr icons
  mlr web
  mlr lint [--ci]
  mlr test

Options:
  -h --help     Show this screen.
  --version     Show version.
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
    local.USER = args['<login>']
    opts = {
        'batch': int(args.get('-b')),
        'threads': int(args.get('-t')),
    }
    if args['gmail'] and args['set']:
        gmail.save_credentials(args['<username>'], args['<password>'])
    elif args['gmail']:
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
        run('pytest -n2 -q')
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
        run('which yarn && yarn run dev || npm run dev', shell=True)

    try:
        pool = Pool()
        pool.spawn(api)
        pool.spawn(webpack)
        pool.join()
    except KeyboardInterrupt:
        time.sleep(1)


def run(cmd):
    from sys import exit
    from subprocess import call

    check = 'which pytest'
    if call(check, cwd=root, shell=True):
        raise SystemExit(
            'Test dependencies must be installed.\n'
            '$ pip install -e .[test]'
        )

    cmd = 'sh -xc %r' % cmd
    exit(call(cmd, cwd=root, shell=True))


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
    tpl = str((font / 'icons.less.tpl').resolve())
    txt = bottle.template(
        tpl, icons=icons,
        template_settings={'syntax': '{% %} % {{ }}'}
    )
    f = font / 'icons.less'
    f.write_text(txt)
    print('%s updated' % f)


if __name__ == '__main__':
    main()
