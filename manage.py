#!/usr/bin/env python
import argparse
import glob
import os
import logging
import subprocess

from werkzeug.serving import run_simple
from werkzeug.wsgi import SharedDataMiddleware

from mailr import theme_dir, attachments_dir, db, app, syncer, views

logging.basicConfig(
    format='%(levelname)s %(asctime)s  %(message)s',
    datefmt='%H:%M:%S', level=logging.DEBUG
)
sh = lambda cmd: subprocess.call(cmd, shell=True)


def run():
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        main(['lessc'])

    extra_files = [
        glob.glob(os.path.join(theme_dir, fmask)) +
        glob.glob(os.path.join(theme_dir, '*', fmask))
        for fmask in ['*.less', '*.css', '*.js']
    ]
    extra_files = sum(extra_files, [])

    wsgi_app = SharedDataMiddleware(app.create_app(), {
        '/theme': theme_dir, '/attachments': attachments_dir
    })
    run_simple(
        '0.0.0.0', 5000, wsgi_app,
        use_debugger=True, use_reloader=True,
        extra_files=extra_files
    )


def main(argv=None):
    parser = argparse.ArgumentParser('mail')
    cmds = parser.add_subparsers(help='commands')

    def cmd(name, **kw):
        p = cmds.add_parser(name, **kw)
        p.set_defaults(cmd=name)
        p.arg = lambda *a, **kw: p.add_argument(*a, **kw) and p
        p.exe = lambda f: p.set_defaults(exe=f) and p
        return p

    cmd('auth', help='refresh auth')\
        .exe(lambda a: views.auth_refresh(None))

    cmd('sync')\
        .arg('-b', '--with-bodies', action='store_true')\
        .exe(lambda a: (syncer.sync_gmail(a.with_bodies)))

    cmd('parse')\
        .arg('-n', '--new', action='store_true')\
        .exe(lambda a: syncer.parse_emails(a.new))

    cmd('db-clear').exe(lambda a: db.drop_all())

    cmd('run').exe(lambda a: run())

    cmd('lessc').exe(lambda a: sh(
        'lessc {0}styles.less {0}styles.css && '
        'autoprefixer {0}styles.css {0}styles.css && '
        'csso {0}styles.css {0}styles.css'.format('mailr/theme/')
    ))

    args = parser.parse_args(argv)
    if not hasattr(args, 'exe'):
        parser.print_usage()
    else:
        args.exe(args)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(1)
