#!/bin/bash

# Install autopep8
# Install pep8

autopep8  -r --in-place .
#find . -name '*.py' -exec autopep8 --in-place --aggressive --aggressive --aggressive '{}' \;
pep8 --ignore=E501,E126,E122,E712,E402,E265,E266,E731
