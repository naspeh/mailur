#!/usr/bin/env python
import argparse
import functools
import glob
import json
import logging
import os
import subprocess

log = logging.getLogger(__name__)


def sh(cmd):
    log.info(cmd)
    return subprocess.call(cmd, shell=True)


def sync(env, email, target=None, **kwargs):
    from mailur import syncer

    func = functools.partial(syncer.sync_gmail, env, email, **kwargs)
    if target in (None, 'fast'):
        func()
    elif target == 'bodies':
        func(bodies=True)
    elif target == 'thrids':
        syncer.update_thrids(env)
    elif target == 'full':
        for target in sync.choices[:-1]:
            sync(env, email, target, **kwargs)
sync.choices = ['fast', 'bodies', 'thrids', 'full']


def run(env, only_wsgi):
    from werkzeug.serving import run_simple
    from werkzeug.wsgi import SharedDataMiddleware
    from mailur import app

    if not only_wsgi and os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        main(['lessc'])

    extra_files = (
        glob.glob(os.path.join(env('path_theme'), fmask)) +
        glob.glob(os.path.join(env('path_theme'), '*', fmask))
        for fmask in ['*.less', '*.css', '*.js']
    )
    extra_files = sum(extra_files, [])

    wsgi_app = SharedDataMiddleware(app.create_app(env.conf), {
        '/attachments': env('path_attachments'),
        '/theme': env('path_theme'),
    })
    run_simple(
        '0.0.0.0', 5000, wsgi_app,
        use_debugger=True, use_reloader=True,
        extra_files=extra_files
    )


def shell(env):
    '''Start a new interactive python session'''
    namespace = {'env': env}
    banner = 'Interactive shell'
    try:
        import bpython
        bpython.embed(locals_=namespace, banner=banner)
    except ImportError:
        from code import interact
        interact(banner, local=namespace)


def get_base(argv):
    parser = argparse.ArgumentParser('mail')
    cmds = parser.add_subparsers(help='commands')

    def cmd(name, **kw):
        p = cmds.add_parser(name, **kw)
        p.set_defaults(cmd=name)
        p.arg = lambda *a, **kw: p.add_argument(*a, **kw) and p
        p.exe = lambda f: p.set_defaults(exe=f) and p
        return p

    requirements = (
        'Stache '
        'Werkzeug '
        'cchardet '
        'lxml '
        'premailer '
        'psycopg2 '
        'requests '
        'valideer '
    )
    cmd('reqs', help='update requirements.txt file')\
        .arg('-w', '--wheels', action='store_true')\
        .exe(lambda a: sh(''.join([
            (
                'pip install wheel && '
                'pip wheel -w ../wheels/ {requirements} &&'
                'pip uninstall -y wheel &&'
                .format(requirements=requirements)
                if a.wheels else ''
            ),
            (
                'rm -rf $VIRTUAL_ENV && '
                'virtualenv $VIRTUAL_ENV && '
                'pip install --no-index -f ../wheels {requirements} && '
                'pip freeze | sort > requirements.txt'
                .format(requirements=requirements)
            )
        ])))

    cmd('node', help='install node packages')\
        .exe(lambda a: sh(
            'npm install'
            '   autoprefixer@5.1.0'
            '   csso@1.3.11'
            '   less@2.5.0'
        ))

    cmd('lessc').exe(lambda a: sh(
        'lessc {0}styles.less {0}styles.css && '
        'autoprefixer {0}styles.css {0}styles.css && '
        'csso {0}styles.css {0}styles.css'.format('mailur/theme/')
    ))

    cmd('test', add_help=False).exe(lambda a: (
        sh('py.test --ignore=node_modules --confcutdir=tests %s' % ' '.join(a))
    ))
    return parser, cmd


def get_full(argv):
    from mailur import Env, db

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
        .exe(lambda a: run(env, a.only_wsgi))

    cmd('shell')\
        .exe(lambda a: shell(env))
    return parser


def main(argv=None):
    try:
        parser = get_full(argv)
    except ImportError as e:
        log.exception(e)
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
