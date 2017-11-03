# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Base classes for tvault workload types flow
All tvault tasks and flow should derive from these base classes
"""

import abc
import collections
import contextlib
import logging

import six

from taskflow import atom
from taskflow import task
from taskflow.utils import reflection

LOG = logging.getLogger(__name__)


class tVaultTask(Task):
    """Base class for tvault-defined tasks.

    Adds following features to Task:
        - keeps the name of the task and
        - inputs for the task
    """

    def __init__(self, name=None, provides=None, requires=None,
                 auto_extract=True, rebind=None):
        """Initialize task instance."""
        if provides is None:
            provides = self.default_provides
        super(tVaultTask, self).__init__(name, provides=provides)


@six.add_metaclass(abc.ABCMeta)
class tValutFlow(Flow):
    """The base abstract class of all tvault flow implementations
    """

    def __init__(self, name):
        self._name = str(name)
        super(tVaultFlow, self).__init__(name)
