#!/usr/bin/env python
import argparse
import functools as ft
import glob
import json
import logging
import os
import subprocess as sp

log = logging.getLogger(__name__)


def sh(cmd):
    log.info(cmd)
    code = sp.call(cmd, shell=True)
    if code:
        raise SystemExit(code)
    return 0


def reqs(dev=False):
    requirements = (
        'Stache '
        'Werkzeug '
        'aiohttp '
        'chardet '
        'lxml '
        'psycopg2 '
        'requests '
        'toronado '
        'valideer '
    )
    requirements += (
        'pytest '
        'ptpdb '
    ) if dev else ''

    sh('[ -d "$VIRTUAL_ENV" ] || (echo "ERROR: no virtualenv" && exit 1)')
    sh(
        'rm -rf $VIRTUAL_ENV && '
        'virtualenv $VIRTUAL_ENV && '
        'pip install wheel && '
        'pip wheel -w ../wheels/ -f ../wheels/ {requirements} &&'
        'pip uninstall -y wheel &&'
        'pip install --no-index -f ../wheels {requirements}'
        .format(requirements=requirements)
    )
    not dev and sh('pip freeze | sort > requirements.txt')


def sync(env, email, target=None, **kwargs):
    from mailur import syncer

    func = ft.partial(syncer.sync_gmail, env, email, **kwargs)
    if target in (None, 'fast'):
        return func()
    elif target == 'bodies':
        return func(bodies=True)
    elif target == 'thrids':
        syncer.update_thrids(env)
    elif target == 'full':
        s = ft.partial(sync, env, email, **kwargs)

        labels = s(target='fast')
        s(target='thrids')
        s(target='bodies', labels=labels)
sync.choices = ['fast', 'thrids', 'bodies', 'full']


def run(env, only_wsgi, use_reloader=True):
    from multiprocessing import Process
    from werkzeug.serving import run_simple
    from werkzeug.wsgi import SharedDataMiddleware
    from mailur import app, async

    if not only_wsgi and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        log.debug('Re-run "css" target and async process')
        main(['css'])
        Process(target=async.run, args=('127.0.0.1', 5001)).start()

    extra_files = (
        glob.glob(os.path.join(env('path_theme'), fmask)) +
        glob.glob(os.path.join(env('path_theme'), '*', fmask))
        for fmask in ['*.less', '*.css', '*.js', '*.mustache']
    )
    extra_files = sum(extra_files, [])

    wsgi_app = SharedDataMiddleware(app.create_app(env.conf), {
        '/attachments': env('path_attachments'),
        '/theme': env('path_theme'),
    })
    run_simple(
        '0.0.0.0', 5000, wsgi_app,
        use_debugger=True, use_reloader=use_reloader,
        extra_files=extra_files
    )


def shell(env):
    '''Start a new interactive python session'''
    namespace = {'env': env}
    try:
        from ptpython.repl import embed
        embed(namespace, history_filename=os.path.expanduser('~/.ptpython'))
    except ImportError:
        from code import interact
        interact('', local=namespace)


def get_base(argv):
    parser = argparse.ArgumentParser('mail')
    cmds = parser.add_subparsers(help='commands')

    def cmd(name, **kw):
        p = cmds.add_parser(name, **kw)
        p.set_defaults(cmd=name)
        p.arg = lambda *a, **kw: p.add_argument(*a, **kw) and p
        p.exe = lambda f: p.set_defaults(exe=f) and p
        return p

    cmd('reqs', help='update python requirements')\
        .arg('-d', '--dev', action='store_true')\
        .exe(lambda a: reqs(a.dev))

    cmd('node', help='update nodejs packages')\
        .exe(lambda a: sh(
            'npm install --save --save-exact'
            '   autoprefixer'
            '   csso'
            '   less'
        ))

    cmd('css').exe(lambda a: sh(
        'lessc {0}styles.less {0}styles.css && '
        'autoprefixer {0}styles.css {0}styles.css && '
        'csso {0}styles.css {0}styles.css'.format('mailur/theme/')
    ))

    cmd('test', add_help=False).exe(lambda a: (
        sh('py.test --ignore=node_modules --confcutdir=tests %s' % ' '.join(a))
    ))
    return parser, cmd


def get_full(argv):
    from mailur import Env, db, async

    with open('conf.json', 'br') as f:
        conf = json.loads(f.read().decode())

    env = Env(conf)

    parser, cmd = get_base(argv)
    cmd('sync')\
        .arg('-t', '--target', choices=sync.choices)\
        .arg('-l', '--only-labels', nargs='+')\
        .arg('email')\
        .exe(lambda a: sync(env, a.email, a.target, only_labels=a.only_labels))

    cmd('db-init')\
        .arg('-r', '--reset', action='store_true')\
        .exe(lambda a: db.init(env, a.reset))

    cmd('run')\
        .arg('-w', '--only-wsgi', action='store_true')\
        .arg('--wo-reloader', action='store_true')\
        .exe(lambda a: run(env, a.only_wsgi, not a.wo_reloader))

    cmd('async')\
        .arg('-H', '--host', default='127.0.0.1')\
        .arg('-P', '--port', type=int, default=5001)\
        .exe(lambda a: async.run(a.host, a.port))

    cmd('shell')\
        .exe(lambda a: shell(env))
    return parser


def main(argv=None):
    try:
        parser = get_full(argv)
    except ImportError as e:
        log.error(e, exc_info=0)
        parser, _ = get_base(argv)

    args, extra = parser.parse_known_args(argv)
    if getattr(args, 'cmd', None) == 'test':
        args.exe(extra)
        return

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
