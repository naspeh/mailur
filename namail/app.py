import json

from jinja2 import Environment, FileSystemLoader
from jinja2.ext import with_
from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.exceptions import HTTPException, abort
from werkzeug.utils import cached_property, redirect
from werkzeug.wrappers import Request as _Request, Response

from . import conf, views, filters


class Request(_Request):
    @cached_property
    def json(self):
        return json.loads(self.data.decode())


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
            loader=FileSystemLoader(conf.theme_dir),
            extensions=[with_],
            lstrip_blocks=True, trim_blocks=True
        )
        jinja.globals.update(url_for=self.url_for, conf=conf, env=self)
        jinja.filters.update(**filters.get_all())

    def run(self):
        endpoint, values = self.adapter.match()
        response = getattr(views, endpoint)(self, **values)
        if isinstance(response, str):
            return self.make_response(response)
        return response

    def render(self, template_name, context):
        t = self.jinja.get_template(template_name)
        context.setdefault('request', self.request)
        return t.render(context)

    def make_response(self, response, **kw):
        kw.setdefault('content_type', 'text/html')
        return Response(response, **kw)

    def url_for(self, endpoint, _external=False, **values):
        return self.adapter.build(endpoint, values, force_external=_external)

    def redirect(self, location, code=302):
        return redirect(location, code)

    def redirect_for(self, endpoint, _code=302, **values):
        return redirect(self.url_for(endpoint, **values), code=_code)

    def abort(self, code, *a, **kw):
        abort(code, *a, **kw)

    @cached_property
    def session(self):
        return SecureCookie.load_cookie(
            self.request, secret_key=conf('cookie_secret').encode()
        )

    def login(self):
        self.session['logined'] = True

    @property
    def is_logined(self):
        return self.session.get('logined')
