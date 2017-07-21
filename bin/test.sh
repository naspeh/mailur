#!/bin/bash
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
set -exuo pipefail

root=$(dirname $(readlink -f $0))
lxc_name=mlr-test
lxc-destroy -fn $lxc_name || true

export lxc_name
$root/lxc

cat << EOF | ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no $(lxc-info -n $lxc_name -iH)
set -exuo pipefail

cd /opt/mailur
bin/install
bin/devel
set +ux
. env/bin/activate
set -ux
pytest -v
python -c 'import mailur.app'
EOF
