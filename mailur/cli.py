import argparse
import functools as ft
import pathlib
import sys
import time

from gevent import joinall, sleep, spawn

from . import conf, local, log, remote

root = pathlib.Path(__file__).resolve().parent.parent


def main(args=None):
    if args is None:
        args = sys.argv[1:]
    if isinstance(args, str):
        args = args.split()

    try:
        parser = build_parser(args)
        args = parser.parse_args(args)
        if not hasattr(args, 'cmd'):
            parser.print_usage()
            exit(2)
        process(args)
    except KeyboardInterrupt:
        raise SystemExit('^C')


def build_parser(args):
    parser = argparse.ArgumentParser('Mailur CLI')
    parser.add_argument('login', help='local user')
    cmds = parser.add_subparsers(title='commands')

    def cmd(name, **kw):
        p = cmds.add_parser(name, **kw)
        p.set_defaults(cmd=name)
        p.arg = lambda *a, **kw: p.add_argument(*a, **kw) and p
        p.exe = lambda f: p.set_defaults(exe=f) or p
        return p

    cmd('remote-setup-imap')\
        .arg('username')\
        .arg('password')\
        .arg('--imap', required=True)\
        .arg('--imap-port')\
        .arg('--smtp', required=True)\
        .arg('--smtp-port')

    cmd('remote-setup-gmail')\
        .arg('username')\
        .arg('password')\
        .arg('--imap', default='imap.gmail.com')\
        .arg('--smtp', default='smtp.gmail.com')

    cmd('remote')\
        .arg('--tag')\
        .arg('--box')\
        .arg('--parse', action='store_true')\
        .arg('--batch', type=int, default=1000, help='batch size')\
        .arg('--threads', type=int, default=2, help='thread pool size')

    cmd('parse')\
        .arg('criteria', nargs='?')\
        .arg('--batch', type=int, default=1000, help='batch size')\
        .arg('--threads', type=int, default=2, help='thread pool size')\
        .arg('--fix-duplicates', action='store_true')

    cmd('metadata')\
        .arg('uids', nargs='?')

    cmd('sync')\
        .arg('--timeout', type=int, default=1200, help='timeout in seconds')\
        .exe(lambda args: sync(args.timeout))

    cmd('sync-flags')\
        .arg('--reverse', action='store_true')\
        .exe(lambda args: (
            local.sync_flags_to_src()
            if args.reverse
            else local.sync_flags_to_all()
        ))

    cmd('clean-flags')\
        .arg('flag', nargs='+')\
        .exe(lambda args: local.clean_flags(args.flag))

    cmd('diagnose')\
        .exe(lambda args: local.diagnose())
    return parser


def process(args):
    conf['USER'] = args.login
    if hasattr(args, 'exe'):
        args.exe(args)
    elif args.cmd in ('remote-setup-imap', 'remote-setup-gmail'):
        remote.data_account({
            'username': args.username,
            'password': args.password,
            'imap_host': args.imap,
            'imap_port': int(args.imap_port),
            'smtp_host': args.smtp,
            'smtp_port': int(args.smtp_port),
        })
    elif args.cmd == 'remote':
        opts = dict(threads=args.threads, batch=args.batch)
        select_opts = dict(tag=args.tag, box=args.box)
        fetch_opts = dict(opts, **select_opts)
        fetch_opts = {k: v for k, v in fetch_opts.items() if v}

        remote.fetch(**fetch_opts)
        if args.parse:
            local.parse(**opts)
    elif args.cmd == 'parse':
        opts = dict(threads=args.threads, batch=args.batch)
        if args.fix_duplicates:
            local.clean_duplicate_msgs()
        local.parse(args.criteria, **opts)
    elif args.cmd == 'metadata':
        local.update_metadata(args.uids)


def run_forever(fn):
    # but if it always raises exception, run only 3 times

    @ft.wraps(fn)
    def inner(*a, **kw):
        count = 3
        while count:
            try:
                fn(*a, **kw)
            except Exception as e:
                log.exception(e)
                sleep(10)
                count = -1
    return inner


def sync(timeout=1200):
    @run_forever
    def idle_remote(params):
        with remote.client(**params) as c:
            handlers = {
                'EXISTS': lambda res: remote.sync(),
                'FETCH': lambda res: remote.sync(only_flags=True),
            }
            c.idle(handlers, timeout=timeout)

    @run_forever
    def sync_flags():
        local.sync_flags_to_all()
        local.sync_flags(
            post_handler=lambda res: remote.sync(only_flags=True),
            timeout=timeout
        )

    try:
        remote.sync()
        jobs = [spawn(sync_flags)]
        for params in remote.get_folders():
            jobs.append(spawn(idle_remote, params))
        joinall(jobs, raise_error=True)
    except KeyboardInterrupt:
        time.sleep(1)


if __name__ == '__main__':
    main()
