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


def ssh(host, cmd):
    return sh('ssh %s "%s"' % (host, cmd.replace('"', '\\"')))


def reqs(dev=False):
    requirements = (
        'Werkzeug '
        'aiohttp '
        'chardet '
        'dnspython3 '
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


def docker(env, opts):
    opts['cwd'] = os.getcwd()
    opts['host'] = 'root@localhost'
    opts['port'] = 2200
    opts['manage'] = (
        'source {path_env}/bin/activate && cd {path_src} && ./manage.py'
        .format(**opts)
    )
    ssh_ = ft.partial(ssh, '{host} -p{port}'.format(**opts))

    sh('''
    running="$(docker inspect --format='{{{{ .State.Running }}}}' mailur)"
    ([ "true" == "$running" ] || (
       docker run -d --net=host --name=mailur \
           -v {cwd}:{path_src} naspeh/sshd \
       &&
       docker exec -i mailur \
           /bin/bash -c "cat >> /root/.ssh/authorized_keys" \
           < ~/.ssh/id_rsa.pub
        sleep 5
    ))
    '''.format(**opts))

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
           nginx \
           uwsgi uwsgi-plugin-python \
           postgresql \
           rsync
        ''')

    sh('rsync -rv -e \"ssh -p{port}\" docker/etc/ {host}:/etc/'.format(**opts))
    ssh_('''
    supervisorctl update
    ([ -d {path_src} ] || (
       ssh-keyscan github.com >> ~/.ssh/known_hosts &&
       mkdir -p {path_src} &&
       git clone git@github.com:naspeh/mailur.git {path_src}
    ))
    '''.format(**opts))

    if opts['env']:
        ssh_('''
        ([ -d {path_env} ] || mkdir -p {path_env} && virtualenv {path_env}) &&
        ([ -d {path_env}/../wheels ] || mkdir -p {path_env}/../wheels) &&
        {manage} reqs &&
        touch {path_src}/../reload
        '''.format(**opts))

    if opts['db']:
        ssh_('''
        ([ -f {path_pgdata}/postgresql.conf ] ||
            sudo -upostgres \
                initdb --locale en_US.UTF-8 -E UTF8 -D {path_pgdata}
        ) &&
        supervisorctl restart postgres &&
        psql -Upostgres -hlocalhost -c "CREATE DATABASE mailur_dev";
        {manage} db-init
        '''.format(**opts))


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


def get_env():
    from mailur import Env

    with open('conf.json', 'br') as f:
        conf = json.loads(f.read().decode())

    return Env(conf)


def get_app():
    from mailur import app

    env = get_env()
    return app.create_app(env.conf)


def get_full(argv):
    from mailur import db, async

    env = get_env()

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
    cmd('docker')\
        .arg('--dot', action='store_true')\
        .arg('--env', action='store_true')\
        .arg('--pkgs', action='store_true')\
        .arg('--db', action='store_true')\
        .arg('--path-src', default='/var/local/mailur/src')\
        .arg('--path-env', default='/var/local/mailur/env')\
        .arg('--path-pgdata', default='/var/lib/postgres/data')\
        .exe(lambda a: docker(env, a.__dict__))

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
