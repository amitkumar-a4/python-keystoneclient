#!/usr/bin/env python
# Copyright (c) 2014 TrilioData, Inc.

# Print a list and return with error if any executable files are found.
# Compatible with both python 2 and 3.

import os.path
import stat
import sys

if len(sys.argv) < 2:
    print("Usage: %s <directory>" % sys.argv[0])
    sys.exit(1)

directory = sys.argv[1]

executable = []

for root, mydir, myfile in os.walk(directory):
    for f in myfile:
        path = os.path.join(root, f)
        mode = os.lstat(path).st_mode
        if stat.S_IXUSR & mode:
            executable.append(path)

if executable:
    print("Executable files found:")
    for f in executable:
        print(f)

    sys.exit(1)
