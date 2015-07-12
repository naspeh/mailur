from mailur import Env, app, async

wsgi = app.create_app(Env().conf)
async = async.create_app()
