from back import app, views, async

web = app.create_app(views)
async = async.create_app()
