#!/usr/bin/env python
import argparse
import pathlib
import sys
import time

root = pathlib.Path(__file__).resolve().parent.parent


def main(args=None):
    parser = argparse.ArgumentParser('Manage CLI')
    cmds = parser.add_subparsers(title='commands')

    def cmd(name, **kw):
        p = cmds.add_parser(name, **kw)
        p.set_defaults(cmd=name)
        p.arg = lambda *a, **kw: p.add_argument(*a, **kw) and p
        p.exe = lambda f: p.set_defaults(exe=f) or p
        return p

    cmd('icons').exe(lambda a: icons())
    cmd('web').exe(lambda a: web())
    cmd('test')\
        .exe(lambda a: run('pytest -q --cov=mailur --cov-report=term-missing'))
    cmd('lint')\
        .exe(lambda a: run('ci=%s bin/run-lint' % (1 if a.ci else '')))\
        .arg('--ci', action='store_true')

    args = parser.parse_args(sys.argv[1:])
    if not hasattr(args, 'cmd'):
        parser.print_usage()
        exit(2)
    elif hasattr(args, 'exe'):
        try:
            args.exe(args)
        except KeyboardInterrupt:
            raise SystemExit('^C')
    else:
        raise ValueError('Wrong subcommand')


def web():
    from gevent.subprocess import run
    from gevent.pool import Pool

    def api():
        run('bin/run-web', shell=True)

    def webpack():
        run('command -v yarn && yarn run dev || npm run dev', shell=True)

    try:
        pool = Pool()
        pool.spawn(api)
        pool.spawn(webpack)
        pool.join()
    except KeyboardInterrupt:
        time.sleep(1)


def run(cmd):
    from sys import exit
    from subprocess import call

    check = 'command -v pytest'
    if call(check, cwd=root, shell=True):
        raise SystemExit(
            'Test dependencies must be installed.\n'
            '$ pip install -e .[test]'
        )

    cmd = 'sh -xc %r' % cmd
    exit(call(cmd, cwd=root, shell=True))


def icons():
    import json
    import bottle

    font = root / 'assets/font'
    sel = (font / 'selection.json').read_text()
    sel = json.loads(sel)
    sel_pretty = json.dumps(sel, indent=2, ensure_ascii=False, sort_keys=True)
    (font / 'selection.json').write_text(sel_pretty)
    icons = [
        (i['properties']['name'], '\\%s' % hex(i['properties']['code'])[2:])
        for i in sel['icons']
    ]
    tpl = str((font / 'icons.less.tpl').resolve())
    txt = bottle.template(
        tpl, icons=icons,
        template_settings={'syntax': '{% %} % {{ }}'}
    )
    f = font / 'icons.less'
    f.write_text(txt)
    print('%s updated' % f)


if __name__ == '__main__':
    main()
