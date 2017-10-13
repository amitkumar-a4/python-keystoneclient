# Copyright (c) 2014 TrilioData, Inc.

"""Installation script for Workloadmgr's/development virtualenv."""

from __future__ import print_function

import optparse
import os
import subprocess
import sys

import install_venv_common as install_venv


def print_help():
    help = """
    Workloadmanager development environment setup is complete.

    Workloadmanager development uses virtualenv to track and manage Python dependencies
    while in development and testing.

    To activate the Workloadmanager virtualenv for the extent of your current shell
    session you can run:

    $ source .venv/bin/activate

    Or, if you prefer, you can run commands in the virtualenv on a case by case
    basis by running:

    $ tools/with_venv.sh <your command>

    Also, make test will automatically use the virtualenv.
    """
    print(help)


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    venv = os.path.join(root, '.venv')
    if os.environ.get('venv'):
        venv = os.environ['venv']
    pip_requires = os.path.join(root, 'requirements.txt')
    test_requires = os.path.join(root, 'test-requirements.txt')
    project = 'Workloadmanager'
    py_version = "python%s.%s" % (sys.version_info[0], sys.version_info[1])
    install = install_venv.InstallVenv(root, venv, pip_requires, test_requires,
                                       py_version, project)
    options = install.parse_args(argv)
    install.check_python_version()
    install.check_dependencies()
    install.create_virtualenv(no_site_packages=options.no_site_packages)
    install.install_dependencies()
    print_help()


if __name__ == '__main__':
    main(sys.argv)
