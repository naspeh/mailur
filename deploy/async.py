from mailur import Env, async

env = Env()
app = async.create_app()

bind = 'localhost:9000'
worker_class = 'aiohttp.worker.GunicornWebWorker'
accesslog = '-'
reload = env('debug')
