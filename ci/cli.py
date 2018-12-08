import base64
import json
import os
import pathlib
import smtplib
import sys
import time
import urllib.error
import urllib.request
from email.message import Message
from multiprocessing.dummy import Pool
from subprocess import call, check_output

from . import conf, log, new_log_dir, pretty_json

root = pathlib.Path(__file__).resolve().parent.parent
pool = Pool()
logs = os.environ.get('logs')
sha = os.environ.get('sha')
ref = os.environ.get('ref', 'master')
email = os.environ.get('email')


def main(args=None):
    if args is None:
        args = sys.argv[1:]
    try:
        process()
    except KeyboardInterrupt:
        raise SystemExit('^C')


def process(**args):
    global logs, sha

    if not sha:
        output = check_output('git rev-parse HEAD', shell=True, cwd=root)
        sha = output.decode().strip()

    if logs:
        logs = pathlib.Path(logs)
    else:
        logs = new_log_dir(sha)

    sh('ci-build', exit=True)

    pool.map(sh, ('ci-lint', 'ci-test'))

    # sh('ci-clean')


def sh(target, exit=False):
    started = time.time()
    gh_post_status(target, 'pending')
    log_file = logs / ('%s.log' % target.rsplit('/', 1)[-1])
    log.info('%r is running: log_file=%s', target, log_file)
    cmd = (
        '(time (sha={sha} ref={ref} bin/{target})) 2>&1'
        '  | ts "[%Y-%m-%d %H:%M:%S]"'
        '  | tee -a {path}'
        '  | aha -w --black >> {path}.htm;'
        '[ "0" = "${{PIPESTATUS[0]}}" ] && true'
        .format(target=target, sha=sha, ref=ref, path=log_file)
    )
    code = call(cmd, shell=True, executable='/bin/bash', cwd=root)
    success = code == 0
    state = 'success' if success else 'failure'
    duration = time.time() - started
    duration = '%dm%ds' % (duration // 60, duration % 60)
    gh_post_status(target, state, desc=duration)
    if not success:
        with open('%s.htm' % log_file, 'rb') as f:
            payload = f.read()
        notify(payload)
    if exit and not success:
        raise SystemExit(code)
    return success


def gh_post_status(context, state, desc=None, target_url=None):
    data = {
        'context': context,
        'state': state,
        'target_url': target_url,
        'description': desc,
    }
    if conf.github_basic:
        path = 'repos/naspeh/mailur/statuses/%s' % sha
        data = gh_call(path, data, info=(context, state))
    else:
        data.update({'!': 'wasn\'t sent to Github'})
    log_file = logs / ('!%s-%s.json' % (state, context))
    log_file.write_text(pretty_json(data))


def gh_auth():
    b64auth = base64.b64encode(conf.github_basic.encode()).decode()
    headers = {'Authorization': 'Basic %s' % b64auth}
    return headers


def gh_call(url, data=None, method=None, info=None):
    if not url.startswith('https://'):
        url = 'https://api.github.com/' + url
    try:
        if data is not None:
            method = 'POST'
            data = json.dumps(data).encode()
        req = urllib.request.Request(url, headers=gh_auth(), method=method)
        res = urllib.request.urlopen(req, data=data)
        log.debug('%s info=%r url=%r', res.status, info, url)
        return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        log.error(
            '%s, code=%s url=%r \nposted_data=%s\nerror=%s',
            e,
            e.code,
            url,
            pretty_json(data),
            pretty_json(e.fp.read()),
        )


def notify(payload):
    if conf.smtp_host is None or email is None:
        return

    log.info('sending notification for %s' % email)
    msg = Message()
    msg['From'] = conf.smtp_user
    msg['To'] = email
    msg['Subject'] = conf.notify_subj
    msg.set_type('text/html')
    msg.set_payload(payload)

    con = smtplib.SMTP('smtp.gmail.com', 587)
    con.ehlo()
    con.starttls()
    con.login(conf.smtp_user, conf.smtp_pass)
    con.send_message(msg)


if __name__ == '__main__':
    main()
