import json
import os
from urllib.parse import urlencode

from werkzeug.exceptions import HTTPException, abort
from werkzeug.utils import cached_property, redirect
from werkzeug.wrappers import Request as _Request, Response

from . import Env


class Request(_Request):
    @cached_property
    def json(self):
        return json.loads(self.data.decode())


def create_app(views):
    env = WebEnv(views)

    @Request.application
    def app(request):
        env.set_request(request)
        try:
            response = env.wsgi()
        except HTTPException as e:
            response = e
        env.session.save_cookie(response)
        return response

    if env('debug'):
        from werkzeug.debug import DebuggedApplication
        from werkzeug.wsgi import SharedDataMiddleware

        app = SharedDataMiddleware(DebuggedApplication(app), {
            '/attachments': env('path_attachments'),
            '/theme': env('path_theme'),
        })
    return app


class WebEnv(Env):
    def __init__(self, views):
        super().__init__()
        self.views = views
        self.url_map = views.url_map

        with open(os.path.join(self('path_theme'), 'build/version')) as f:
            self.theme_version = f.read()

    def set_request(self, request):
        self.request = request
        self.adapter = self.url_map.bind_to_environ(request.environ)

    def wsgi(self):
        endpoint, values = self.adapter.match()
        response = getattr(self.views, endpoint)(self, **values)
        if isinstance(response, str):
            return self.make_response(response)
        return response

    def url_for(self, endpoint, _args=None, _external=False, **values):
        url = self.adapter.build(endpoint, values, force_external=_external)
        return self.url(url, _args)

    def url(self, url, args):
        return '%s?%s' % (url, urlencode(args)) if args else url

    def redirect(self, location, code=302):
        return redirect(location, code)

    def redirect_for(self, endpoint, _args=None, _code=302, **values):
        return redirect(self.url_for(endpoint, _args, **values), code=_code)

    def abort(self, code, *a, **kw):
        abort(code, *a, **kw)

    @cached_property
    def session(self):
        return self.get_session(self.request)

    def login(self, email):
        self.session['email'] = email

    @property
    def is_logined(self):
        return self.session.get('email')

    def make_response(self, response, **kw):
        kw.setdefault('content_type', 'text/html')
        return Response(response, **kw)

    def to_json(self, response, **kw):
        kw.setdefault('content_type', 'application/json')
        r = json.dumps(response, ensure_ascii=False, default=str, indent=2)
        return Response(r, **kw)

    def render(self, name, ctx):
        from pystache import render

        with open(os.path.join(self('path_theme'), '%s.mustache' % name)) as f:
            tpl = f.read()
        return render(tpl, ctx)

    def render_body(self, name, ctx):
        body = self.render(name, ctx)
        name = 'all' if self('debug') else 'all.min'
        return self.render('base', {
            'body': body,
            'cssfile': '/theme/build/%s.css?%s' % (name, self.theme_version),
            'jsfile': '/theme/build/%s.js?%s' % (name, self.theme_version)
        })
