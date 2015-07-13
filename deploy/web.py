from mailur import Env, app

app = app.create_app(Env().conf)

bind = 'localhost:8000'
workers = 4
accesslog = '-'
