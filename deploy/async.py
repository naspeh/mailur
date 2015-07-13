from mailur import async

app = async.create_app()

bind = 'localhost:9000'
worker_class = 'aiohttp.worker.GunicornWebWorker'
accesslog = '-'
