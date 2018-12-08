import hashlib
import hmac
import json
import os
import subprocess
import sys
from multiprocessing.dummy import Pool

from werkzeug.exceptions import abort
from werkzeug.wrappers import Request, Response

from . import cli, conf, log, new_log_dir, pretty_json

pool = Pool()


@Request.application
def app(request):
    check_signature = hmac.compare_digest(
        get_signature(request.data),
        request.headers.get('X-Hub-Signature', '')
    )
    if not check_signature:
        return abort(400)

    event = request.headers.get('X-GitHub-Event')
    if event != 'push':
        log.info('skip %r event', event)
        return Response('skip %r event' % event)

    data = json.loads(request.data)
    sha = data['after']
    if sha == '0000000000000000000000000000000000000000':
        log.info('skip %r event: %r deleted', event, data['ref'])
        return Response('%r deleted' % data['ref'])

    logs = new_log_dir(sha)
    log_file = logs / ('hook-%s.json' % event)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(pretty_json([dict(request.headers), data]))

    env = {
        'sha': sha,
        'ref': data['ref'],
        'logs': logs,
        'email': data['pusher']['email'],
    }
    cmd = '%s -m ci.cli' % sys.executable
    pool.apply_async(subprocess.call, (cmd,), {
        'env': dict(os.environ, **env),
        'shell': True,
        'cwd': cli.root,
    })
    return Response('%s' % logs)


def get_signature(body):
    sha1 = hmac.new(conf.secret.encode(), body, hashlib.sha1).hexdigest()
    return 'sha1=' + sha1
