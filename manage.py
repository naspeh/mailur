#!/usr/bin/env python
import argparse
import glob
import os
import subprocess

from werkzeug.serving import run_simple
from werkzeug.wsgi import SharedDataMiddleware

from mailr import conf, db, app, syncer, log

sh = lambda cmd: log.info(cmd) or subprocess.call(cmd, shell=True)
ssh = lambda cmd: sh('ssh %s "%s"' % (
    conf('server_host'), cmd.replace('"', '\"').replace('$', '\$')
))


def run(args):
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        main(['lessc'])

    extra_files = [
        glob.glob(os.path.join(conf.theme_dir, fmask)) +
        glob.glob(os.path.join(conf.theme_dir, '*', fmask))
        for fmask in ['*.less', '*.css', '*.js']
    ]
    extra_files = sum(extra_files, [])

    wsgi_app = SharedDataMiddleware(app.create_app(), {
        '/theme': conf.theme_dir, '/attachments': conf.attachments_dir
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

    cmd('sync')\
        .arg('-b', '--with-bodies', action='store_true')\
        .exe(lambda a: (syncer.sync_gmail(a.with_bodies)))

    cmd('tasks').exe(lambda a: syncer.process_tasks())

    cmd('parse')\
        .arg('-n', '--new', action='store_true')\
        .arg('-l', '--limit', type=int, default=500)\
        .arg('-t', '--last')\
        .exe(lambda a: syncer.parse_emails(a.new, a.limit, a.last))

    cmd('db-init').exe(lambda a: db.create_all())
    cmd('db-clear').exe(lambda a: db.drop_all() or db.create_all())

    cmd('test').exe(lambda a: (
        sh('MAILR_CONF=conf_test.json py.test %s' % ' '.join(a))
    ))

    cmd('run').exe(run)

    cmd('lessc').exe(lambda a: sh(
        'lessc {0}styles.less {0}styles.css && '
        'autoprefixer {0}styles.css {0}styles.css && '
        'csso {0}styles.css {0}styles.css'.format('mailr/theme/')
    ))

    cmd('deploy', help='deploy to server')\
        .arg('-t', '--target', default='origin/master', help='checkout it')\
        .exe(lambda a: ssh(
            'cd /home/mailr/src'
            '&& git fetch origin' +
            '&& git checkout {}'.format(a.target) +
            '&& touch ../reload'
        ))

    args, extra = parser.parse_known_args(argv)
    if getattr(args, 'cmd', None) == 'test':
        args.exe(extra)
    elif not hasattr(args, 'exe'):
        parser.print_usage()
    else:
        args.exe(args)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(1)
