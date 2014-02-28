# -*- coding: utf-8 -*-

# Copyright (C) 2012 Trilio Data, Inc. All Rights Reserved.
#


import abc

import six

from taskflow.utils import reflection


@six.add_metaclass(abc.ABCMeta)

class Workflow(object):
    """The base abstract class of all workflows implementations.

    A workflow is a base class for all workflows that are defined in  the
    tvault appliance. These base class defines set of abstract classes for
    managing workflows on the appliance.

    all other workflows are derived from this base class.

    workflows are expected to provide the following methods/properties:

    - discover
    - topology
    - details
    """

    def __init__(self, name):
        self._name = str(name)

    @property
    def name(self):
        """A non-unique name for this workflow (human readable)."""
        return self._name

    def __str__(self):
        lines = ["%s: %s" % (reflection.get_class_name(self), self.name)]
        lines.append("%s" % (len(self)))
        return "; ".join(lines)

    @abc.abstractmethod
    def discover(self):
        """Discover number of VMs that will be part of the workflow."""

    @abc.abstractmethod
    def topology(self):
        """Discovers the logical topology of the scaleout application."""

    @abc.abstractmethod
    def details(self):
        """Provides the workflow details in json format."""

