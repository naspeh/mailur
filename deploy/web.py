from mailur import Env, app

env = Env()
app = app.create_app(env.conf)

bind = 'localhost:8000'
workers = 4
accesslog = '-'
reload = env('debug')
