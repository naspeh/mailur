#!/usr/bin/env python
import logging

import mail

logging.basicConfig(
    format='%(levelname)s %(filename)s|%(lineno)d %(asctime)s # %(message)s',
    datefmt='%H:%M:%S', level=logging.DEBUG
)

if __name__ == '__main__':
    try:
        mail.parse_args()
    except KeyboardInterrupt:
        raise SystemExit(1)
