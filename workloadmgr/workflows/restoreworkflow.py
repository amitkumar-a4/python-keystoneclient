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

def get_vms(cntx, restore_id):
    db = vmtasks.WorkloadMgrDB().db
    restore = db.restore_get(cntx, restore_id)
    snapshot = db.snapshot_get(cntx, restore.snapshot_id)
    
    vms = []
    for snapshot_vm in db.snapshot_vms_get(cntx, snapshot.id): 
        vm = {'vm_id' : snapshot_vm.vm_id,
              'vm_name' : snapshot_vm.vm_name,
              'hypervisor_hostname' : 'None',
              'hypervisor_type' :  'QEMU'}
        vms.append(vm)
    return vms

class RestoreWorkflow(object):
    """
      Restore Workflow
    """

    def __init__(self, name, store):
        self._name = name
        self._store = store
        

    def initflow(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        self._store['instances'] =  get_vms(cntx, self._store['restore']['id'])
        for index,item in enumerate(self._store['instances']):
            self._store['instance_'+str(index)] = item
      
        self._flow = lf.Flow('RestoreFlow')
        
        # Check if any pre restore conditions 
        self._flow.add(vmtasks.UnorderedPreRestore(self._store['instances'])) 
        
        #restore networks
        self._flow.add(vmtasks.RestoreVMNetworks("RestoreVMNetworks", provides='restored_net_resources'))                  
        
        #linear restore VMs
        self._flow.add(vmtasks.LinearRestoreVMs(self._store['instances']))
        
        # unordered post restore 
        self._flow.add(vmtasks.UnorderedPostRestore(self._store['instances'])) 
    
          
    def execute(self):
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
