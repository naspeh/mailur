#!/bin/bash
cd $(dirname "$0")
activate="$(cat .venv)/bin/activate"
source $activate
./manage.py $@
