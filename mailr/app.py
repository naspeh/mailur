import os

from jinja2 import Environment, FileSystemLoader
from werkzeug.exceptions import HTTPException
from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response
from werkzeug.wsgi import SharedDataMiddleware

from . import views, filters

app_dir = os.path.abspath(os.path.dirname(__file__))
theme_dir = os.path.join(app_dir, 'theme')


def create_app():
    @Request.application
    def app(request):
        env = Env(request)
        try:
            return env.run()
        except HTTPException as e:
            return e
    return SharedDataMiddleware(app, {'/theme': theme_dir})


class Env:
    def __init__(self, request):
        self.url_map = views.url_map
        self.request = request
        self.adapter = self.url_map.bind_to_environ(request.environ)

        self.jinja = jinja = Environment(loader=FileSystemLoader(theme_dir))
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
        return t.render(context)

    def make_response(self, response, **kw):
        kw.setdefault('content_type', 'text/html')
        return Response(response, **kw)

    def url_for(self, endpoint, _external=False, **values):
        return self.adapter.build(endpoint, values, force_external=_external)


def run():
    app = create_app()
    run_simple('0.0.0.0', 5000, app, use_debugger=True, use_reloader=True)
