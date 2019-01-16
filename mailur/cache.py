from . import conf

store = {}


def key(name):
    return conf['USER'], name


def get(name, default=None):
    return store.get(key(name), default)


def set(name, value):
    store[key(name)] = value


def rm(name):
    store.pop(key(name), None)


def clear():
    for key in list(store.keys()):
        if key[0] == conf['USER']:
            del store[key]


def exists(name):
    return key(name) in store
