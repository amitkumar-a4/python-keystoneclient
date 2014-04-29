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
        for workload_id in self._store['workloadids']:
            """
            Return workload topology
            """        
            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                    'context': context_dict,                # context dictionary
                    'workload_id': workload_id,             # workload_id
            }
            workload = self.db.workload_get(context, workload_id)
            for kvpair in workload.metadata:
                store[kvpair['key']] = kvpair['value']
            
            workflow_class = self._get_workflow_class(context, workload.workload_type_id)
            workflow = workflow_class("workload_workflow_details", store)
            workflow.initflow()

            self._flow.add(workflow._flow)
        
    def topology(self):
        # Fill in the topology information later, perhaps combine 
        # topology information from all workloads?
        topology = {'test3':'test3', 'test4':'test4'}
        return dict(topology=topology)

    def details(self):
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

    def discover(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = []
        for workload_id in self._store['workloadids']:
            """
            Return workload topology
            """        
            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                    'context': context_dict,                # context dictionary
                    'workload_id': workload_id,             # workload_id
            }
            workload = self.db.workload_get(context, workload_id)
            for kvpair in workload.metadata:
                store[kvpair['key']] = kvpair['value']
            
            workflow_class = self._get_workflow_class(context, workload.workload_type_id)
            workflow = workflow_class("workload_workflow_details", store)
            instances.append(workflow.discover())

        return dict(instances=instances)

    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
