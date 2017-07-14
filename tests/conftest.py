import sys
from pathlib import Path
from subprocess import call

import pytest

root = (Path(__file__).parent / '..').resolve()
sys.path.insert(0, str(root))


@pytest.fixture
def setup():
    call('''
    rm -rf /home/vmail/test*
    ls -l /home/vmail
    bin/users
    ''', shell=True, cwd=root)
