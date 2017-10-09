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

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp
from workloadmgr import exception

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
        self._flow = None
        self._presnapshot = None
        self._snapshotmetadata = None
        self._snapshotvms = None
        self._postsnapshot = None

    def initflow(self, snapshotvms, presnapshot=None,
                 snapshotmetadata=None, postsnapshot=None, composite=False):

        if snapshotvms is None:
            raise exception.ErrorOccurred(
                "Failed to initialize the workflow: snapshotvms workflow is not set")

        # Check if any pre snapshot conditions
        if presnapshot is None:
            self._presnapshot = uf.Flow(self.name + "#Presnapshot")
            self._presnapshot.add(
                vmtasks.UnorderedPreSnapshot(
                    self._store['instances']))
        else:
            self._presnapshot = presnapshot

        # These are snapshot metadata workflows
        if snapshotmetadata is None:
            # create a network snapshot
            self._snapshotmetadata = lf.Flow(self.name + "#SnapshotMetadata")
            self._snapshotmetadata.add(
                vmtasks.SnapshotVMNetworks(
                    self.name + "#SnapshotVMNetworks"))

            # snapshot flavors of VMs
            self._snapshotmetadata.add(
                vmtasks.SnapshotVMFlavors(
                    self.name + "#SnapshotVMFlavors"))

            # snapshot security groups of VMs
            self._snapshotmetadata.add(
                vmtasks.SnapshotVMSecurityGroups(
                    self.name + "#SnapshotVMSecurityGroups"))
        else:
            self._snapshotmetadata = snapshotmetadata

        self._snapshotvms = snapshotvms

        # This is the post snapshot workflow
        if postsnapshot is None:
            # calculate the size of the snapshot
            self._postsnapshot = lf.Flow(self.name + "#Postsnapshot")
            self._postsnapshot.add(
                vmtasks.LinearSnapshotDataSize(
                    self._store['instances']))

            # Now lazily copy the snapshots of VMs to tvault appliance
            self._postsnapshot.add(
                vmtasks.LinearUploadSnapshot(
                    self._store['instances']))

            # block commit any changes back to the snapshot
            self._postsnapshot.add(
                vmtasks.LinearPostSnapshot(
                    self._store['instances']))

            if not composite:
                # apply retention policy
                self._postsnapshot.add(
                    vmtasks.ApplyRetentionPolicy("ApplyRetentionPolicy"))
        else:
            self._postsnapshot = postsnapshot

        self._flow = lf.Flow(self.name)

        self._flow.add(
            self._presnapshot,
            self._snapshotmetadata,
            self._snapshotvms,
            self._postsnapshot)

    @property
    def name(self):
        """A non-unique name for this workflow (human readable)."""
        return self._name

    @property
    def presnapshot(self):
        """Returns references to presnapshot workflow."""
        return self._presnapshot

    @property
    def snapshotmetadata(self):
        """Returns references to snapshot metadata workflow."""
        return self._snapshotmetadata

    @property
    def snapshotvms(self):
        """Returns references to snapshotvms workflow."""
        return self._snapshotvms

    @property
    def postsnapshot(self):
        """Returns references to postsnapshot workflow"""
        return self._postsnapshot

    def __str__(self):
        lines = ["%s: %s" % (reflection.get_class_name(self), self.name)]
        if hasattr(self, 'len'):
            lines.append("%s" % (len(self)))
        return "; ".join(lines)

    def topology(self):
        topology = {}
        return dict(topology=topology)

    def discover(self):
        pass

    def details(self):
        """Provides the workflow details in json format."""
        # workflow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            if isinstance(item, task.Task):
                taskdetails = {
                    'name': item._name.split("_")[0],
                    'type': 'Task'}
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
