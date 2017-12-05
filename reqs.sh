#!/bin/sh
set -eu

deps="
bottle
docopt
gevent
geventhttpclient
gunicorn
lxml
wheel
wsaccel
"

[ ! ${dev:-} ] || deps="
$deps

flake8
flake8-import-order
pytest
webtest
ipdb
"

echo $deps
