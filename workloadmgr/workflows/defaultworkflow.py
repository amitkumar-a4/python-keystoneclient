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
            if hypervisor.hypervisor_hostname == vm_instance.__dict__['OS-EXT-SRV-ATTR:host']:
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

                 
def InitFlow(store):
    cntx = amqp.RpcContext.from_dict(store['context'])
     
    store['instances'] =  get_vms(cntx, store['snapshot']['workload_id'])
    for index,item in enumerate(store['instances']):
        store['instance_'+str(index)] = item

  
    flow = lf.Flow('DefaultFlow')
    
    #create an entry for the VM in the workloadmgr database
    flow.add(vmtasks.CreateVMSnapshotDBEntries("CreateVMSnapshotDBEntries_" + store['snapshot']['id']))
    
    #create a network snapshot
    flow.add(vmtasks.SnapshotVMNetworks("SnapshotVMNetworks" + store['snapshot']['id']))
    
    #snapshot flavors of VMs
    flow.add(vmtasks.SnapshotVMFlavors("SnapshotVMFlavors" + store['snapshot']['id']))    

    # This is an unordered pausing of VMs. 
    flow.add(vmtasks.UnorderedPauseVMs(store['instances']))

    # Unordered snapshot of VMs. 
    flow.add(vmtasks.UnorderedSnapshotVMs(store['instances']))

    flow.add(vmtasks.UnorderedUnPauseVMs(store['instances']))

    # Now lazily copy the snapshots of VMs to tvault appliance
    flow.add(vmtasks.UnorderedUploadSnapshot(store['instances']))

    # block commit any changes back to the snapshot
    flow.add(vmtasks.UnorderedPostSnapshot(store['instances']))

    return flow

'''
SerialWorkflow Requires the following inputs in store:

    'connection': FLAGS.sql_connection,     # taskflow persistence connection
    'context': context_dict,                # context dictionary
    'snapshot': snapshot,                   # snapshot dictionary
'''

class DefaultWorkflow(workflow.Workflow):
    """
      Default Workflow
    """

    def __init__(self, name, store):
        super(DefaultWorkflow, self).__init__(name)
        self._store = store
        self._flow = InitFlow(self._store)

    def topology(self):
        pass

    def details(self):
        # Details the flow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            
            if isinstance(item, task.Task):
                return [{'name':str(item), 'type':'Task'}]

            flowdetails = {}
            flowdetails['name'] = str(item)
            flowdetails['type'] = item.__class__.__name__
            flowdetails['children'] = []
            for it in item:
                flowdetails['children'].append(recurseflow(it))

            return flowdetails

        return recurseflow(self._flow)

    def discover(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        return get_vms(cntx, self._store['snapshot']['workload_id'])

    def execute(self):
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)

