# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2012 Trilio Data, Inc. All Rights Reserved.
#


import abc

import six
import contextlib
import os
import random
import sys
import time

import datetime 
import paramiko
import uuid

from taskflow import engines
from taskflow.utils import misc
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import graph_flow as gf
from taskflow import task
from taskflow import flow
from taskflow.utils import reflection

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp

import vmtasks
import workflow


LOG = logging.getLogger(__name__)

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

    def topology(self):
        topology = {}
        return dict(topology=topology)

    def discover(self):
        instances = []
        return dict(instances=self._store['instances'])

    def details(self):
        """Provides the workflow details in json format."""
        # workflow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            if isinstance(item, task.Task):
                taskdetails = {'name':item._name.split("_")[0], 'type':'Task'}
                taskdetails['input'] = []
                if len(item._name.split('_')) == 2:
                    nodename = item._name.split("_")[1]
                    for n in nodes['instances']:
                       if n['vm_id'] == nodename:
                          nodename = n['vm_name']
                    taskdetails['input'] = [['vm', nodename]]
                return taskdetails

            flowdetails = {}
            flowdetails['name'] = str(item).split("==")[0]
            flowdetails['type'] = str(item).split('.')[2]
            flowdetails['children'] = []
            for it in item:
                flowdetails['children'].append(recurseflow(it))

            return flowdetails

        nodes = self.discover()
        workflow = recurseflow(self._flow)
        return dict(workflow=workflow)
