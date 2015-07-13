#!/usr/bin/env python
import argparse
import functools as ft
import logging
import os
import subprocess as sp
from pathlib import Path

log = logging.getLogger(__name__)


def sh(cmd):
    log.info(cmd)
    code = sp.call(cmd, shell=True)
    if code:
        raise SystemExit(code)
    return 0


def ssh(host, cmd):
    return sh('ssh %s "%s"' % (host, cmd.replace('"', '\\"')))


def reqs(dev=False, clear=False):
    requirements = (
        'Werkzeug '
        'aiohttp '
        'chardet '
        'dnspython3 '
        'gunicorn '
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
        (
            'rm -rf $VIRTUAL_ENV && virtualenv $VIRTUAL_ENV && '
            if clear else ''
        ) +
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
        Process(target=async.run)
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


def deploy(env, opts):
    root = Path('/var/local/mailur')
    path = dict(
        src=str(root / 'src'),
        env=str(root / 'env'),
        attachments=str(root / 'attachments'),
        wheels=str(root / 'wheels'),
        pgdata='/var/lib/postgres/data'
    )
    ctx = {
        'cwd': os.getcwd(),
        'path': path,
        'host': 'root@localhost',
        'port': 2200,
        'manage': '{[src]}/m'.format(path)
    }
    ssh_ = ft.partial(ssh, '{host} -p{port}'.format(**ctx))

    sh('''
    running="$(docker inspect --format='{{{{ .State.Running }}}}' mailur)"
    ([ "true" == "$running" ] || (
       docker run -d --net=host --name=mailur \
           -v {cwd}:{path[src]} naspeh/web \
       &&
       docker exec -i mailur \
           /bin/bash -c "cat >> /root/.ssh/authorized_keys" \
           < ~/.ssh/id_rsa.pub
        sleep 5
    ))
    '''.format(**ctx))

    if opts['dot']:
        ssh_('''
        pacman --noconfirm -Sy python-requests
        ([ -d {dest} ] || mkdir /home/dotfiles)
        cd {dest} &&
        ([ -d .git ] || git clone https://github.com/naspeh/dotfiles.git .) &&
        git pull && ./manage.py init --boot vim zsh bin dev
        '''.format(dest='/home/dotfiles'))

    if opts['pkgs']:
        ssh_('''
        pacman --noconfirm -Sy \
           python-virtualenv gcc libxslt \
           systemd postgresql \
           rsync \
           inotify-tools
        ''')

    ssh_('''
    rsync -v {path[src]}/deploy/nginx-site.conf /etc/nginx/site-mailur.conf &&
    rsync -v {path[src]}/deploy/supervisor.ini /etc/supervisor.d/mailur.ini &&
    supervisorctl update &&
    ([ -d {path[src]} ] || (
       ssh-keyscan github.com >> ~/.ssh/known_hosts &&
       mkdir -p {path[src]} &&
       git clone git@github.com:naspeh/mailur.git {path[src]}
    )) &&
    ([ -d {path[attachments]} ] || mkdir {path[attachments]}) &&
    chown http:http {path[attachments]}
    '''.format(**ctx))

    if opts['env']:
        ssh_('''
        ([ -d {path[env]} ] || (
            mkdir -p {path[env]} && virtualenv {path[env]}
        )) &&
        ([ -d {path[wheels]} ] || mkdir -p {path[wheels]}) &&
        {manage} reqs -c &&
        echo '../env' > .venv
        '''.format(**ctx))

    if opts['db']:
        ssh_('''
        ([ -f {path[pgdata]}/postgresql.conf ] ||
            sudo -upostgres \
                initdb --locale en_US.UTF-8 -E UTF8 -D {path[pgdata]}
        ) &&
        supervisorctl restart postgres &&
        psql -Upostgres -hlocalhost -c "CREATE DATABASE mailur_dev";
        {manage} db-init
        '''.format(**ctx))

    ssh_('supervisorctl pid async web nginx | xargs kill -s HUP')


def get_app():
    from mailur import Env, app

    return app.create_app(Env().conf)


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
        .arg('-c', '--clear', action='store_true')\
        .exe(lambda a: reqs(a.dev, a.clear))
    return parser, cmd


def get_full(argv):
    from mailur import Env, db, async

    env = Env()

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
        .arg('-P', '--port', type=int, default=9000)\
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
        '   node_modules/normalize.css/normalize.css'
        '   {0}selectize.css'
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
    cmd('deploy')\
        .arg('--dot', action='store_true')\
        .arg('-e', '--env', action='store_true')\
        .arg('-p', '--pkgs', action='store_true')\
        .arg('-d', '--db', action='store_true')\
        .exe(lambda a: deploy(env, a.__dict__))

    cmd('touch').exe(lambda a: sh(
        './manage.py static &&'
        'supervisorctl pid async web nginx | xargs kill -s HUP'
    ))
    return parser


def main(argv=None):
    try:
        parser = get_full(argv)
    except ImportError as e:
        log.error(e, exc_info=0)
        parser, _ = get_base(argv)

    args, extra = parser.parse_known_args(argv)
    if getattr(args, 'cmd', None) in ('test', 'gunicorn'):
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
