import argparse

from . import db, app, sync


def parse_args():
    parser = argparse.ArgumentParser('mail')
    cmds = parser.add_subparsers(help='commands')

    def cmd(name, **kw):
        p = cmds.add_parser(name, **kw)
        p.set_defaults(cmd=name)
        p.arg = lambda *a, **kw: p.add_argument(*a, **kw) and p
        p.exe = lambda f: p.set_defaults(exe=f) and p
        return p

    cmd('sync')\
        .arg('-b', '--with-bodies', action='store_true')\
        .exe(lambda a: sync.sync_gmail(a.with_bodies))

    cmd('db-clear').exe(lambda a: db.drop_all())

    cmd('run').exe(lambda a: app.run())

    args = parser.parse_args()
    if not hasattr(args, 'exe'):
        parser.print_usage()
    else:
        args.exe(args)
