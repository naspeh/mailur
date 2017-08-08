"""Mailur CLI

Usage:
  mailur -l <login> gmail <username> <password> [--parse]
  mailur -l <login> parse [<criteria>]
  mailur -l <login> threads [<criteria>]

Options:
  -h --help     Show this screen.
  --version     Show version.
"""
from docopt import docopt

from . import gmail, local


def main(args):
    local.USER = args['<login>']
    if args['gmail']:
        gmail.USER = args['<username>']
        gmail.PASS = args['<password>']
        gmail.fetch()
        if args.get('--parse'):
            local.parse()
    elif args['parse']:
        local.parse(args.get('<criteria>'))
    elif args['threads']:
        local.update_threads(criteria=args.get('<criteria>'))


if __name__ == '__main__':
    args = docopt(__doc__, version='Mailur 0.3')
    try:
        main(args)
    except KeyboardInterrupt:
        raise SystemExit('^C')
