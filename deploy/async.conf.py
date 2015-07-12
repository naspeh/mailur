from pathlib import Path

bind = 'localhost:9000'
worker_class = 'aiohttp.worker.GunicornWebWorker'
accesslog = '-'
pythonpath = str(Path(__file__).parent)
