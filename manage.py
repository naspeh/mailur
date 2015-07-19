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
        'unidecode '
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

    func = ft.partial(syncer.locked_sync_gmail, env, email, **kwargs)
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


def grun(name, extra):
    extra = '--timeout 300 --graceful-timeout=0 %s' % (extra or '')
    sh(
        'PYTHONPATH=.:./deploy/ '
        'gunicorn app:{name} -c deploy/{name}.conf.py {extra}'
        .format(name=name, extra=extra)
    )


def run(env):
    from multiprocessing import Process

    def process(name):
        return Process(target=grun, args=[name, '--pid=/tmp/g-%s.pid' % name])

    main(['static'])
    for p in [process('web'), process('async')]:
        p.start()

    sh(
        'while inotifywait -e modify -r .;'
        '   do ./manage.py static;cat /tmp/g-*.pid | xargs kill -s HUP;done'
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
        pgdata='/var/lib/postgres/data',
        dotfiles='/home/dotfiles'
    )
    ctx = {
        'cwd': os.getcwd(),
        'path': path,
        'manage': '{[src]}/m'.format(path),
        'dbname': env('pg_dbname')
    }

    if opts['docker']:
        sh('''
        r="$(docker inspect --format='{{{{ .State.Running }}}}' mailur)"
        ([ "true" == "$r" ] || (
            docker run -d --net=host --name=mailur \
                -v {cwd}:{path[src]} naspeh/web \
            &&
            docker exec -i mailur \
                /bin/bash -c "cat >> /root/.ssh/authorized_keys" \
                < ~/.ssh/id_rsa.pub
            sleep 5
        ))
        '''.format(**ctx))
        opts['ssh'] = 'root@localhost -p2200'

    cmd = []
    if opts['dot']:
        cmd.append('''
        pacman --noconfirm -Sy python-requests &&
        ([ -d {path[dotfiles]} ] || mkdir {path[dotfiles]}) &&
        cd {path[dotfiles]} &&
        ([ -d .git ] || git clone https://github.com/naspeh/dotfiles.git .) &&
        git pull && ./manage.py init --boot vim zsh bin
        ''')

    if opts['pkgs']:
        cmd.append(
            'pacman --noconfirm -Sy'
            '  python-virtualenv gcc libxslt'
            '  postgresql'
            '  rsync'
            '  inotify-tools'
            '  npm'
        )

    cmd.append('''
    rsync -v {path[src]}/deploy/nginx-site.conf /etc/nginx/site-mailur.conf &&
    rsync -v {path[src]}/deploy/supervisor.ini /etc/supervisor.d/mailur.ini &&
    rsync -v {path[src]}/deploy/fcrontab /etc/fcrontab/10-mailur &&
    cat /etc/fcrontab/* | fcrontab - &&
    ([ -d {path[src]} ] || (
       git clone https://github.com/naspeh/mailur.git {path[src]}
    )) &&
    cd {path[src]} && git pull;
    ([ -d {path[attachments]} ] || (
        mkdir {path[attachments]} &&
        chown http:http {path[attachments]}
    ))
    ''')

    if opts['env']:
        cmd.append('''
        ([ -d {path[env]} ] || (
            mkdir -p {path[env]} && virtualenv {path[env]}
        )) &&
        ([ -d {path[wheels]} ] || mkdir -p {path[wheels]}) &&
        {manage} reqs -c &&
        echo '../env' > .venv
        ''')

    if opts['db']:
        cmd.append('''
        ([ -f {path[pgdata]}/postgresql.conf ] ||
            sudo -upostgres \
                initdb --locale en_US.UTF-8 -E UTF8 -D {path[pgdata]}
        ) &&
        ([ -d /run/postgresql ] || (
            mkdir -m 0775 /run/postgresql &&
            chown postgres:postgres /run/postgresql
        )) &&
        supervisorctl update && supervisorctl restart postgres &&
        psql -Upostgres -hlocalhost -c "CREATE DATABASE {dbname}";
        {manage} db-init
        ''')

    cmd.append(
        'supervisorctl update &&'
        'supervisorctl pid async web nginx | xargs kill -s HUP'
    )

    cmd = '\n'.join(cmd).format(**ctx)
    if opts['ssh']:
        sh('ssh {} "{}"'.format(opts['ssh'], cmd.replace('"', '\\"')))
    else:
        sh(cmd)


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
    from mailur import Env, db

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

    cmd('run').exe(lambda a: run(env))
    cmd('web', add_help=False).exe(lambda a: grun('web', ' '.join(a)))
    cmd('async', add_help=False).exe(lambda a: grun('async', ' '.join(a)))

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
        .arg('-s', '--ssh')\
        .arg('--dot', action='store_true')\
        .arg('-c', '--docker', action='store_true')\
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
    if getattr(args, 'cmd', None) in ('test', 'async', 'web'):
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
