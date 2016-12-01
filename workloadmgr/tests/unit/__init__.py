# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.

"""
:mod:`workloadmgr.tests.unit` -- WorkloadMgr Unittests
=====================================================

"""

import eventlet

eventlet.monkey_patch()

# See http://code.google.com/p/python-nose/issues/detail?id=373
# The code below enables nosetests to work with i18n _() blocks
import __builtin__
setattr(__builtin__, '_', lambda x: x)