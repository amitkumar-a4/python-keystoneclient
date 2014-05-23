# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

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
from workloadmgr.workloads import manager as workloadmgr
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp

import vmtasks
import workflow


LOG = logging.getLogger(__name__)

class CompositeWorkflow(workflow.Workflow):

    def __init__(self, name, store):
        super(CompositeWorkflow, self).__init__(name)
        self._store = store
        
    def initflow(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])

        self._flow = lf.Flow('CompositeFlow')

        # all we have to do is call into individual workflow init routine
        # Depending on the linear or parallel relations between the workloads,
        # we need to pause and resume the vms in that order. 
        # once we achieve that we can unpause the vms and upload the
        # snapshot in any order
        # Dig into each workflow
            
        # Aggregate all instances here
        self._store['instances'] = []

        workflows = []
        for workload_id in self._store['Workloads'].split(","):
            db = vmtasks.WorkloadMgrDB().db
            context_dict = dict([('%s' % key, value)
                              for (key, value) in cntx.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'context': context_dict,                # context dictionary
                'workload_id': workload_id,             # workload_id
            }

            workload = db.workload_get(cntx, workload_id)
            for kvpair in workload.metadata:
                store[kvpair['key']] = kvpair['value']

            workflow_class = workloadmgr.get_workflow_class(cntx, workload.workload_type_id)
            workflow = workflow_class("composite_workflow_initflow_" + workload_id, store)
            workflow.initflow()
            workflows.append(workflow)
            self._store['instances'].extend(workflow._store['instances'])

        for index,item in enumerate(self._store['instances']):
            self._store['instance_'+item['vm_id']] = item

        # Aggregate presnapshot workflows from all workloads
        presnapshot = uf.Flow(self.name + "#Presnapshot")
        for workflow in workflows:
            presnapshot.add(workflow.presnapshot)

        # Aggregate snapshotmetadata workflows from all workloads
        snapshotmetadata = uf.Flow(self.name + "#SnapshotMetadata")
        for workflow in workflows:
            snapshotmetadata.add(workflow.snapshotmetadata)
            # Snapshot Metadata operates on list of snapshots, so we only need to have one
            # snapshot vmnetworks and snapshot flavor
            break

        # Aggregate snapshotvms workflows from all workloads
        # REVISIT: lf is hardcoded, but should be fed from the workload definition itself
        snapshotvms = lf.Flow(self.name + "#SnapshotVMs")
        for workflow in workflows:
            snapshotvms.add(workflow.snapshotvms)

        # Aggregate snapshotmetadata workflows from all workloads
        postsnapshot = uf.Flow(self.name + "#PostSnapshot")
        for workflow in workflows:
            postsnapshot.add(workflow.postsnapshot)

        super(CompositeWorkflow, self).initflow(snapshotvms=snapshotvms, presnapshot=presnapshot, 
                                                snapshotmetadata=snapshotmetadata, postsnapshot=postsnapshot)
        
    def topology(self):
        # Fill in the topology information later, perhaps combine 
        # topology information from all workloads?
        topology = {'test3':'test3', 'test4':'test4'}
        return dict(topology=topology)

    def discover(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = []
        for workload_id in self._store['Workloads'].split(","):
            db = vmtasks.WorkloadMgrDB().db
            context_dict = dict([('%s' % key, value)
                              for (key, value) in cntx.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'context': context_dict,                # context dictionary
                'workload_id': workload_id,             # workload_id
            }

            workload = db.workload_get(cntx, workload_id)
            for kvpair in workload.metadata:
                store[kvpair['key']] = kvpair['value']

            workflow_class = workloadmgr.get_workflow_class(cntx, workload.workload_type_id)
            workflow = workflow_class("composite_workflow_discover_" + workload_id, store)
            workflow.initflow()
            instances.extend(workflow.discover()['instances'])

        return dict(instances=instances)

    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
