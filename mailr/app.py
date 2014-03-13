import glob
import os
import subprocess

from jinja2 import Environment, FileSystemLoader
from jinja2.ext import with_
from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.exceptions import HTTPException, abort
from werkzeug.serving import run_simple
from werkzeug.utils import cached_property, redirect
from werkzeug.wrappers import Request, Response
from werkzeug.wsgi import SharedDataMiddleware

from . import conf, theme_dir, attachments_dir, views, filters


def create_app():
    @Request.application
    def app(request):
        env = Env(request)
        try:
            response = env.run()
        except HTTPException as e:
            response = e
        env.session.save_cookie(response)
        return response
    return app


class Env:
    def __init__(self, request):
        self.url_map = views.url_map
        self.request = request
        self.adapter = self.url_map.bind_to_environ(request.environ)

        self.jinja = jinja = Environment(
            loader=FileSystemLoader(theme_dir),
            extensions=[with_],
            lstrip_blocks=True, trim_blocks=True
        )
        jinja.globals.update(url_for=self.url_for)
        jinja.filters.update(**filters.get_all())

    def run(self):
        endpoint, values = self.adapter.match()
        response = getattr(views, endpoint)(self, **values)
        if isinstance(response, str):
            return self.make_response(response)
        return response

    def render(self, template_name, **context):
        t = self.jinja.get_template(template_name)
        context.setdefault('request', self.request)
        return t.render(context)

    def make_response(self, response, **kw):
        kw.setdefault('content_type', 'text/html')
        return Response(response, **kw)

    def url_for(self, endpoint, _external=False, **values):
        return self.adapter.build(endpoint, values, force_external=_external)

    def redirect(self, endpoint, _code=302, **kw):
        return redirect(self.url_for(endpoint, **kw), code=_code)

    def abort(self, code, *a, **kw):
        abort(code, *a, **kw)

    @cached_property
    def session(self):
        return SecureCookie.load_cookie(
            self.request, secret_key=conf('cookie_secret').encode()
        )


def run():
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        subprocess.call('./manage.py lessc', shell=True)

    extra_files = [
        glob.glob(os.path.join(theme_dir, fmask)) +
        glob.glob(os.path.join(theme_dir, '*', fmask))
        for fmask in ['*.less', '*.css', '*.js']
    ]
    extra_files = sum(extra_files, [])

    app = SharedDataMiddleware(create_app(), {
        '/theme': theme_dir, '/attachments': attachments_dir
    })
    run_simple(
        '0.0.0.0', 5000, app,
        use_debugger=True, use_reloader=True,
        extra_files=extra_files
    )
