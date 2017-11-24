"""Mailur CLI

Usage:
  mailur -l<login> gmail <username> <password> [--parse -t<threads> -b<batch>]
  mailur -l<login> parse [<criteria> -t<threads> -b<batch>]
  mailur -l<login> threads [<criteria>]
  mailur -l<login> web

Options:
  -h --help     Show this screen.
  --version     Show version.
  -l <login>    Local user (for dovecot).
  -b <batch>    Batch size [default: 1000].
  -t <threads>  Amount of threads for thread pool [default: 2].
"""
from docopt import docopt

from . import gmail, local


def main(args):
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
    elif args['web']:
        web()


def web():
    import os
    import time
    from gevent.subprocess import run
    from gevent.pool import Pool

    def api():
        cmd = (
            'gunicorn mailur.app -b :5000 '
            ' -k gevent --timeout=300 --reload --access-logfile=-'
            ' --access-logformat="%(m)s %(U)s %(s)s %(L)ss %(b)sb"'
        )
        env = dict(os.environ, MLR_USER=local.USER)
        run(cmd, env=env, shell=True)

    def webpack():
        run('webpack -w', shell=True)

    try:
        pool = Pool()
        pool.spawn(api)
        pool.spawn(webpack)
        pool.join()
    except KeyboardInterrupt:
        time.sleep(1)


if __name__ == '__main__':
    args = docopt(__doc__, version='Mailur 0.3')
    try:
        main(args)
    except KeyboardInterrupt:
        raise SystemExit('^C')
