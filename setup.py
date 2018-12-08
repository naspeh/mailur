#!/usr/bin/env python
import setuptools

# http://setuptools.readthedocs.io/en/latest/setuptools.html
# > Configuring setup() using setup.cfg files
# > Note New in 30.3.0 (8 Dec 2016).
if not setuptools.__version__ > '30.3':
    raise SystemExit('"setuptools >= 30.3.0" is required')

setuptools.setup()
