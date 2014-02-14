import contextlib
import json
import os

root_dir = os.path.join(os.path.dirname(__file__))


@contextlib.contextmanager
def open_file(*names, mode='br'):
    path = os.path.join(root_dir, *names)
    with open(path, mode) as f:
        yield f


def read_file(*names, decode=True):
    with open_file(*names) as f:
        result = f.read()
    if decode and names[-1].endswith('.json'):
        result = json.loads(result.decode())
    return result
