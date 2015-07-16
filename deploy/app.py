from mailur import Env, app, async

env = Env()
web = app.create_app(env.conf)
async = async.create_app()
