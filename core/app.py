import datetime as dt
import json
from urllib.parse import urlsplit, parse_qs, urlencode

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
        env.session.save_cookie(response, max_age=dt.timedelta(days=7))
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

    def url_for(self, endpoint, values=None, **kw):
        return self.adapter.build(endpoint, values, **kw)

    def url(self, url, params=None):
        if not params:
            return url

        url = urlsplit(url)
        query = parse_qs(url.query)
        query.update((k, str(v)) for k, v in params.items())
        url = url._replace(query=urlencode(query))
        return url.geturl()

    def redirect(self, location, code=302):
        return redirect(location, code)

    def redirect_for(self, endpoint, values=None, code=302):
        return redirect(self.url_for(endpoint, values), code=code)

    def abort(self, code, *a, **kw):
        abort(code, *a, **kw)

    def make_response(self, response=None, **kw):
        kw.setdefault('content_type', 'text/html')
        return self.Response(response, **kw)

    def to_json(self, response, **kw):
        kw.setdefault('content_type', 'application/json')
        r = json.dumps(response, ensure_ascii=False, default=str)
        return self.Response(r, **kw)
