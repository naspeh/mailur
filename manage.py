#!/usr/bin/env python
import argparse
import functools as ft
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
        'Werkzeug '
        'aiohttp '
        'chardet '
        'lxml '
        'mistune '
        'psycopg2 '
        'pystache '
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


def run(env, no_reloader, only_wsgi):
    import signal
    import sys
    from multiprocessing import Process
    from werkzeug.serving import run_simple
    from werkzeug.wsgi import SharedDataMiddleware
    from mailur import app, async

    def run_wsgi():
        wsgi_app = SharedDataMiddleware(app.create_app(env.conf), {
            '/attachments': env('path_attachments'),
            '/theme': env('path_theme'),
        })
        run_simple('0.0.0.0', 5000, wsgi_app, use_debugger=True)

    if only_wsgi:
        return run_wsgi()

    main(['static'])
    ps = [
        Process(target=run_wsgi),
        Process(target=async.run, args=('127.0.0.1', 5001))
    ]
    for p in ps:
        p.start()
    pids = ' '.join(str(p.pid) for p in ps)
    log.info('Pids: %s', pids)

    if no_reloader:
        def close(signal, frame):
            for p in ps:
                p.terminate()
        signal.signal(signal.SIGINT, close)
    else:
        sh(
            'while inotifywait -e modify -r .;do kill {pids};{cmd};done'
            .format(pids=pids, cmd=' '.join(sys.argv))
        )


def shell(env):
    '''Start a new interactive python session'''
    namespace = {'env': env}
    try:
        from ptpython.repl import embed
        opts = {'history_filename': os.path.expanduser('~/.ptpython_history')}
        embed(namespace, **opts)
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
        .arg('--no-reloader', action='store_true')\
        .exe(lambda a: run(env, a.no_reloader, only_wsgi=a.only_wsgi))

    cmd('async')\
        .arg('-H', '--host', default='127.0.0.1')\
        .arg('-P', '--port', type=int, default=5001)\
        .exe(lambda a: async.run(a.host, a.port))

    cmd('shell')\
        .exe(lambda a: shell(env))

    cmd('test', add_help=False).exe(lambda a: (
        sh('py.test --ignore=node_modules --confcutdir=tests %s' % ' '.join(a))
    ))

    cmd('npm', help='update nodejs packages')\
        .exe(lambda a: sh(
            'npm install --save --save-exact'
            '   autoprefixer'
            '   csso'
            '   less'
            '   uglify-js'
            '   jshint'
            # js libs
            '   jquery'
            '   mousetrap'
            '   selectize'
        ))

    cmd('static').exe(lambda a: sh(
        # all.css
        'lessc {0}styles.less {0}build/styles.css &&'
        'autoprefixer {0}build/styles.css {0}build/styles.css &&'
        'cat'
        '   node_modules/selectize/dist/css/selectize.css'
        '   {0}build/styles.css'
        '   > {0}build/all.css &&'
        'csso {0}build/all.css {0}build/all.min.css &&'
        # all.js
        'cat'
        '   node_modules/jquery/dist/jquery.js'
        '   node_modules/mousetrap/mousetrap.js'
        '   node_modules/selectize/dist/js/standalone/selectize.js'
        '   {0}app.js'
        '   > {0}build/all.js &&'
        'uglifyjs -v -o {0}build/all.min.js {0}build/all.js &&'
        # theme version
        'cat mailur/theme/build/all.min.* | md5sum - | cut -c-32'
        '   > {0}build/version'
        .format(env('path_theme') + os.path.sep)
    ))

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
