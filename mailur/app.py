import datetime as dt
import json
from pathlib import Path
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
        finally:
            if env.username:
                env.db.rollback()
        env.session.save_cookie(response, max_age=dt.timedelta(days=3))
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
    Response = Response

    def __init__(self, views):
        super().__init__()
        self.views = views
        self.url_map = views.url_map
        self.theme_dir = Path(self('path_theme'))

        self.theme_version = self.load_asset('build/version').strip()
        self.templates = {
            n.stem: self.load_asset(n)
            for n in self.theme_dir.glob('*.mustache')
        }

    def set_request(self, request):
        self.request = request
        self.adapter = self.url_map.bind_to_environ(request.environ)
        self.username = self.session.get('username')

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

    def make_response(self, response=None, **kw):
        kw.setdefault('content_type', 'text/html')
        return self.Response(response, **kw)

    def to_json(self, response, **kw):
        kw.setdefault('content_type', 'application/json')
        r = json.dumps(response, ensure_ascii=False, default=str)
        return self.Response(r, **kw)

    def load_asset(self, name):
        path = (self.theme_dir / name) if isinstance(name, str) else name
        with path.open('br') as f:
            return f.read().decode()

    def render(self, name, ctx=None):
        from pystache import Renderer

        render = Renderer(partials=self.templates).render
        tpl = self.templates[name]
        return render(tpl, ctx)
