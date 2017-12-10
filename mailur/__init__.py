import functools as ft
import inspect
import logging
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    datefmt='%Y-%m-%d %H:%M:%S%Z',
    format='[%(asctime)s][%(process)s][%(levelname).3s] %(message)s'
)


def fn_desc(func, *a, **kw):
    args = ', '.join(
        [repr(i) for i in a] +
        (['**%r' % kw] if kw else [])
    )
    maxlen = 80
    if len(args) > maxlen:
        args = '%s...' % args[:maxlen]
    name = getattr(func, 'name', None)
    if not name:
        name = getattr(func, '__name__', None)
    if not name:
        name = str(func)
    return '%s(%s)' % (name, args)


def fn_time(func, desc=None):
    @contextmanager
    def timing(*a, **kw):
        start = time.time()
        try:
            yield
        finally:
            d = desc if desc else fn_desc(func, *a, **kw)
            log.debug('## %s: done for %.2fs', d, time.time() - start)

    def inner_fn(*a, **kw):
        with timing(*a, **kw):
            return func(*a, **kw)

    def inner_gen(*a, **kw):
        with timing(*a, **kw):
            yield from func(*a, **kw)

    inner = inner_gen if inspect.isgeneratorfunction(func) else inner_fn
    return ft.wraps(func)(inner)
