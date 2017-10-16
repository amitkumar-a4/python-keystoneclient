#!/bin/bash

# Install autopep8
# Install pep8

#find . -name '*.py' -exec autopep8 --in-place --aggressive --aggressive --aggressive '{}' \;
pep8 --ignore=E501,E126,E122,E712

