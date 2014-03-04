#!/usr/bin/env python
import argparse
import logging
import subprocess

from mailr import db, app, syncer

logging.basicConfig(
    format='%(levelname)s %(asctime)s  %(message)s',
    datefmt='%H:%M:%S', level=logging.DEBUG
)
sh = lambda cmd: subprocess.call(cmd, shell=True)


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
        .exe(lambda a: (syncer.sync_gmail(a.with_bodies)))

    cmd('parse')\
        .arg('-n', '--new', action='store_true')\
        .exe(lambda a: syncer.parse_emails(a.new))

    cmd('db-clear').exe(lambda a: db.drop_all())

    cmd('run').exe(lambda a: app.run())

    cmd('lessc').exe(lambda a: sh(
        'lessc {0}styles.less {0}styles.css && '
        'autoprefixer {0}styles.css {0}styles.css && '
        'csso {0}styles.css {0}styles.css'.format('mailr/theme/')
    ))

    args = parser.parse_args()
    if not hasattr(args, 'exe'):
        parser.print_usage()
    else:
        args.exe(args)


if __name__ == '__main__':
    try:
        parse_args()
    except KeyboardInterrupt:
        raise SystemExit(1)
