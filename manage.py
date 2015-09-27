#!/usr/bin/env python
import argparse
import functools as ft
import logging
import os
import subprocess as sp
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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
        'bcrypt '
        'chardet '
        'dnspython3 '
        'gunicorn '
        'lxml '
        'mistune '
        'psycopg2 '
        'pystache '
        'requests '
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


def for_all(func):
    def inner(env, *a, **kw):
        if env.username:
            return func(env, *a, **kw)

        for username in env.users:
            env.username = username
            try:
                func(env, *a, **kw)
            except Exception as e:
                log.exception(e)
            except SystemExit:
                pass
    return ft.wraps(func)(inner)


@for_all
def sync(env, target, disabled=False, **kw):
    from mailur import syncer

    skip = (
        'no email' if not env.email else
        'disabled' if not disabled and not env('enabled') else
        None
    )
    ending = 'Skip couse %r' % skip if skip else env.email
    log.info('Sync %r for %r; %s', target, env.username, ending)
    if skip:
        return

    sync = ft.partial(syncer.locked_sync_gmail, env, env.email)
    if target == 'fast':
        return sync(fast=True)
    elif target == 'full':
        return sync(fast=False)

sync.choices = ['fast', 'full']


@for_all
def parse(env, limit=1000, offset=0):
    from mailur import syncer
    from mailur.helpers import Timer

    sql = 'SELECT count(id) FROM emails WHERE raw IS NOT NULL'
    count = env.sql(sql).fetchone()[0] - offset
    if count <= 0:
        return

    log.info('Parse %s emails for %r', count, env.username)

    timer, done = Timer(), 0
    for offset in range(offset, count, limit):
        i = env.sql('''
        SELECT id FROM emails
        WHERE raw IS NOT NULL
        ORDER BY created DESC
        LIMIT %s OFFSET %s
        ''' % (limit, offset))
        for row in i:
            raw = env.sql('SELECT raw FROM emails WHERE id=%s', [row['id']])
            raw = raw.fetchone()[0].tobytes()
            data = syncer.get_parsed(env, raw, row['id'])
            env.emails.update(dict(data), 'id=%s', [row['id']])
            env.db.commit()
            done += 1
        log.info('  - done %s for %.2f', done, timer.duration)


@for_all
def thrids(env, clear=False):
    from mailur import syncer

    log.info('Update thread ids for %r', env.username)
    if clear:
        log.info('  * Clear thrids')
        env.sql('UPDATE emails SET thrid = NULL RETURNING id')

    syncer.update_thrids(env)


def grun(name, extra):
    extra = '--timeout=300 --graceful-timeout=0 %s' % (extra or '')
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


@for_all
def migrate(env, init=False):
    from mailur import db

    if init:
        db.init(env)
    env.username = env.username  # reset db connection

    for col in ('to', 'fr', 'cc', 'bcc', 'reply_to', 'sender', 'refs'):
        env.sql('''
        UPDATE emails SET "{col}" = '{{}}' WHERE "{col}" IS NULL;
        ALTER TABLE emails ALTER COLUMN "{col}" SET NOT NULL;
        '''.format(col=col))
    env.db.commit()


def deploy(opts):
    root = Path('/var/local/mailur')
    path = dict(
        src=str(root / 'src'),
        env=str(root / 'env'),
        attachments=str(root / 'attachments'),
        wheels=str(root / 'wheels'),
        pgdata='/var/lib/postgres/data',
        log='/var/log',
        dotfiles='/home/dotfiles',
    )
    ctx = {
        'cwd': os.getcwd(),
        'path': path,
        'manage': '{[src]}/m'.format(path),
    }

    if opts['docker']:
        sh('''
        r="$(docker inspect --format='{{{{ .State.Running }}}}' mailur)"
        ([ "true" == "$r" ] || (
            docker run -d --net=host --name=mailur \
                -v {cwd}:{path[src]} \
                -v {cwd}/../attachments:{path[attachments]} \
                -v {cwd}/../pgdata:{path[pgdata]} \
                -v {cwd}/../log:{path[log]} \
                {docker_image} \
            &&
            docker exec -i mailur \
                /bin/bash -c "cat >> /root/.ssh/authorized_keys" \
                < ~/.ssh/id_rsa.pub
            sleep 5
        ))
        '''.format(docker_image=opts['docker_image'], **ctx))

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
            '   python-virtualenv'
            '   gcc'
            '   libxslt'  # for lxml
            '   pkg-config'  # for cffi
            '   postgresql'
            '   rsync'
            '   inotify-tools'
            '   npm'
        )

    cmd.append('''
    ([ -d {path[src]} ] || (
       git clone https://github.com/naspeh/mailur.git {path[src]}
    )) &&
    cd {path[src]} && git pull;
    ([ -d {path[attachments]} ] || mkdir {path[attachments]}) &&
    chown http:http {path[attachments]}
    rsync -v {path[src]}/deploy/nginx-site.conf /etc/nginx/site-mailur.conf &&
    rsync -v {path[src]}/deploy/supervisor.ini /etc/supervisor.d/mailur.ini &&
    rsync -v {path[src]}/deploy/fcrontab /etc/fcrontab/10-mailur &&
    cat /etc/fcrontab/* | fcrontab - &&
    PATH="./node_modules/.bin;$PATH" {manage} static &&
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
        ([ -d {path[pgdata]} ] && chown -R postgres:postgres {path[pgdata]}) &&
        ([ -f {path[pgdata]}/postgresql.conf ] ||
            sudo -upostgres \
                initdb --locale en_US.UTF-8 -E UTF8 -D {path[pgdata]}
        ) &&
        ([ -d /run/postgresql ] || (
            mkdir -m 0775 /run/postgresql &&
            chown postgres:postgres /run/postgresql
        )) &&
        supervisorctl update && supervisorctl restart postgres &&
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

    cmd('deploy')\
        .arg('-s', '--ssh', default="root@localhost -p2200")\
        .arg('--dot', action='store_true')\
        .arg('-c', '--docker', action='store_true')\
        .arg('-i', '--docker-image', default='naspeh/web')\
        .arg('-e', '--env', action='store_true')\
        .arg('-p', '--pkgs', action='store_true')\
        .arg('-d', '--db', action='store_true')\
        .exe(lambda a: deploy(a.__dict__))
    return parser, cmd


def get_full(argv):
    from mailur import Env, db

    env = Env()

    parser, cmd = get_base(argv)
    cmd('sync')\
        .arg('-t', '--target', default='fast', choices=sync.choices)\
        .arg('-l', '--only', nargs='*', help='sync only these labels')\
        .arg('-d', '--disabled', action='store_true')\
        .arg('-u', '--username')\
        .exe(lambda a: (
            sync(Env(a.username), a.target, a.disabled, only=a.only))
        )

    cmd('parse')\
        .arg('-u', '--username')\
        .arg('-l', '--limit', type=int, default=1000)\
        .arg('-o', '--offset', type=int, default=0)\
        .exe(lambda a: parse(Env(a.username), a.limit, a.offset))

    cmd('thrids')\
        .arg('-u', '--username')\
        .arg('-c', '--clear', action='store_true')\
        .exe(lambda a: thrids(Env(a.username), a.clear))

    cmd('db-init')\
        .arg('username')\
        .arg('-r', '--reset', action='store_true')\
        .arg('-p', '--password')\
        .exe(lambda a: db.init(Env(a.username), a.password, a.reset))

    cmd('migrate')\
        .arg('-i', '--init', action='store_true')\
        .exe(lambda a: migrate(env, a.init))

    cmd('shell').exe(lambda a: shell(env))
    cmd('run').exe(lambda a: run(env))
    cmd('web', add_help=False).exe(lambda a: grun('web', ' '.join(a)))
    cmd('async', add_help=False).exe(lambda a: grun('async', ' '.join(a)))

    cmd('test', add_help=False).exe(lambda a: (
        sh('py.test --ignore=node_modules --confcutdir=tests %s' % ' '.join(a))
    ))

    cmd('npm', help='update nodejs packages')\
        .exe(lambda a: sh(
            'npm install --save --save-exact'
            '   less'
            '   postcss-cli'
            '   autoprefixer'
            '   clean-css'
            '   core-js'
            '   browserify'
            '   babelify'
            '   partialify'
            '   uglify-js'
            # js linting
            '   jshint'
            '   eslint'
            # libs
            '   normalize.css'
            '   history'
            '   lodash'
            '   mousetrap'
            '   vue'
            '   wjbryant/taboverride'
            '   whatwg-fetch'
            '   insignia'
            '   horsey'
        ))

    cmd('static').exe(lambda a: sh(
        # all.css
        'lessc {0}styles.less {0}build/styles.css &&'
        'cat'
        '   node_modules/normalize.css/normalize.css'
        '   {0}build/styles.css'
        '   > {0}build/all.css &&'
        'postcss --use autoprefixer -o {0}build/all.css {0}build/all.css &&'
        'cleancss {0}build/all.css -o {0}build/all.min.css &&'
        # all.js
        'browserify -d -o {0}build/all.js {0}app.js &&'
        'uglifyjs -vcm -o {0}build/all.min.js {0}build/all.js &&'
        # theme version
        'cat mailur/theme/build/all.min.* | md5sum - | cut -c-32'
        '   > {0}build/version'
        .format(env('path_theme') + os.path.sep)
    ))

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
