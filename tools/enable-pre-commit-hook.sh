#!/usr/bin/env python
# Copyright (c) 2014 TrilioData, Inc.

PRE_COMMIT_SCRIPT = .git / hooks / pre - commit

make_hook() {
    echo "exec ./run_tests.sh -N -p" >> $PRE_COMMIT_SCRIPT
    chmod + x $PRE_COMMIT_SCRIPT

    if [-w $PRE_COMMIT_SCRIPT - a - x $PRE_COMMIT_SCRIPT]
    then
    echo "pre-commit hook was created successfully"
    else
    echo "unable to create pre-commit hook"
    fi
}

# NOTE(jk0): Make sure we are in cinder's root directory before adding the hook.
if [! -d ".git"]
then
    echo "unable to find .git; moving up a directory"
    cd ..
    if [-d ".git"]
    then
        make_hook
    else
        echo "still unable to find .git; hook not created"
    fi
else
    make_hook
fi
