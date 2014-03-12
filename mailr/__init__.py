import logging
import os
import time

log = logging.getLogger(__name__)
app_dir = os.path.abspath(os.path.dirname(__file__))
theme_dir = os.path.join(app_dir, 'theme')
attachments_dir = os.path.join(app_dir, 'attachments')


class Timer:
    __slots__ = ('start', 'finish')

    def __init__(self):
        self.reset()

    def reset(self):
        self.start = time.time()

    @property
    def duration(self):
        self.finish = time.time()
        return self.finish - self.start

    def time(self, reset=True):
        duration = self.duration
        if reset:
            self.reset()
        return duration
