import contextlib
import json
import os
import pickle

root_dir = os.path.join(os.path.dirname(__file__))


@contextlib.contextmanager
def open_file(*names, mode='br'):
    path = os.path.join(root_dir, *names)
    with open(path, mode) as f:
        yield f


def read_file(*names, decode=True):
    with open_file(*names) as f:
        result = f.read()
    if decode:
        ftype = names[-1].rsplit('.', 1)[-1]
        filters = {
            'json': lambda r: json.loads(r.decode()),
            'pickle': pickle.loads
        }
        if ftype in filters:
            result = filters[ftype](result)
    return result
