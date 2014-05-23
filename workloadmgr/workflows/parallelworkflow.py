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
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp

import vmtasks
import workflow


LOG = logging.getLogger(__name__)

def get_vms(cntx, workload_id):
    db = vmtasks.WorkloadMgrDB().db
    
    compute_service = nova.API(production=True)
    instances = compute_service.get_servers(cntx, admin=True)
    hypervisors = compute_service.get_hypervisors(cntx)

    vms = []
    for vm in db.workload_vms_get(cntx, workload_id):
        vm_instance = None
        for instance in instances:
            if vm.vm_id == instance.id:
                vm_instance = instance
                break;
        if vm_instance == None:
            pass #TODO(giri): Throw exception
        
        vm_hypervisor = None
        for hypervisor in hypervisors:
            if hypervisor.hypervisor_hostname == vm_instance.__dict__['OS-EXT-SRV-ATTR:hypervisor_hostname']:
                vm_hypervisor = hypervisor
        if vm_hypervisor == None:
            pass #TODO(giri): Throw exception
                   
        vm = {'vm_id' : vm_instance.id,
              'vm_name' : vm_instance.name,
              'vm_flavor_id' : vm_instance.flavor['id'],
              'hypervisor_hostname' : vm_hypervisor.hypervisor_hostname,
              'hypervisor_type' :  vm_hypervisor.hypervisor_type}
        vms.append(vm)
    return vms

"""
ParallelWorkflow Requires the following inputs in store:

    'connection': FLAGS.sql_connection,     # taskflow persistence connection
    'context': context_dict,                # context dictionary
    'snapshot': snapshot,                   # snapshot dictionary
"""

class ParallelWorkflow(workflow.Workflow):
    """
      Parallel Workflow
    """

    def __init__(self, name, store):
        super(ParallelWorkflow, self).__init__(name)
        self._store = store
        

    def initflow(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        self._store['instances'] =  get_vms(cntx, self._store['workload_id'])
        for index,item in enumerate(self._store['instances']):
            self._store['instance_'+ item['vm_id']] = item
      
        _snapshotvms = lf.Flow(self.name + "#SnapshotVMs")
        
        # This is an unordered pausing of VMs. 
        _snapshotvms.add(vmtasks.UnorderedPauseVMs(self._store['instances']))
        
        # Unordered snapshot of VMs. 
        _snapshotvms.add(vmtasks.UnorderedSnapshotVMs(self._store['instances']))
    
        # This is an unordered unpasuing of VMs. 
        _snapshotvms.add(vmtasks.UnorderedUnPauseVMs(self._store['instances']))
        
        super(ParallelWorkflow, self).initflow(_snapshotvms)
    
          
    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
