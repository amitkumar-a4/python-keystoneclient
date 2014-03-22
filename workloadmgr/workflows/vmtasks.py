# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement application
specific flows

"""

import os
import uuid
import cPickle as pickle

from taskflow import engines
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow import task
from taskflow.utils import reflection

from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.virt import driver
from workloadmgr.vault import vault
from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog

import vmtasks_openstack
import vmtasks_vcloud

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

      
class SnapshotVMNetworks(task.Task):
        
    def execute(self, context, instances, snapshot):
        return self.execute_with_log(context, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    

    @autolog.log_method(Logger, 'SnapshotVMNetworks.execute')
    def execute_with_log(self, context, instances, snapshot):
        # Snapshot the networking configuration of VMs
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        
        if True:
            return vmtasks_openstack.snapshot_vm_networks(cntx, db, instances, snapshot)
        else:
            return vmtasks_vcloud.snapshot_vm_networks(cntx, db, instances, snapshot)

    @autolog.log_method(Logger, 'SnapshotVMNetworks.revert') 
    def revert_with_log(self, *args, **kwargs):
        pass
        
class SnapshotVMFlavors(task.Task):

    def execute(self, context, instances, snapshot):
        return self.execute_with_log(context, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
      
    @autolog.log_method(Logger, 'SnapshotVMFlavors.execute')
    def execute_with_log(self, context, instances, snapshot):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if True:
            return vmtasks_openstack.snapshot_vm_flavors(cntx, db, instances, snapshot)
        else:
            return vmtasks_vcloud.snapshot_vm_flavors(cntx, db, instances, snapshot)
          
    @autolog.log_method(Logger, 'SnapshotVMFlavors.revert')
    def revert_with_log(self, *args, **kwargs):
        pass
                            
class PauseVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
    
    @autolog.log_method(Logger, 'PauseVM.execute')
    def execute_with_log(self, context, instance):
        # Pause the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if True:
            return vmtasks_openstack.pause_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.pause_vm(cntx, db, instance)

    @autolog.log_method(Logger, 'PauseVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass
        
class UnPauseVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'UnPauseVM.execute')
    def execute_with_log(self, context, instance):
        # UnPause the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if True:
            return vmtasks_openstack.unpause_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.unpause_vm(cntx, db, instance)

    @autolog.log_method(Logger, 'UnPauseVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     

class SuspendVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'SuspendVM.execute')
    def execute_with_log(self, context, instance):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if True:
            return vmtasks_openstack.suspend_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.suspend_vm(cntx, db, instance)

    @autolog.log_method(Logger, 'SuspendVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
            
class ResumeVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'ResumeVM.execute')
    def execute_with_log(self, context, instance):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if True:
            return vmtasks_openstack.resume_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.resume_vm(cntx, db, instance)

    @autolog.log_method(Logger, 'ResumeVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
    
class PreSnapshot(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PreSnapshot.execute')
    def execute_with_log(self, context, instance, snapshot):
        # pre processing of snapshot
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        if True:
            return vmtasks_openstack.pre_snapshot_vm(cntx, db, instance, snapshot)
        else:
            return vmtasks_vcloud.pre_snapshot_vm(cntx, db, instance, snapshot)

    @autolog.log_method(Logger, 'PreSnapshot.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
           
class SnapshotVM(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'SnapshotVM.execute')
    def execute_with_log(self, context, instance, snapshot):
        # Snapshot the VM
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        if True:
            return vmtasks_openstack.snapshot_vm(cntx, db, instance, snapshot)
        else:
            return vmtasks_vcloud.snapshot_vm(cntx, db, instance, snapshot)
        
    @autolog.log_method(Logger, 'SnapshotVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
                
class SnapshotDataSize(task.Task):

    def execute(self, context, instances, snapshot):
        return self.execute_with_log(context, instances, snapshot)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    
    
    @autolog.log_method(Logger, 'GetSnapshotDataSize.execute')    
    def execute_with_log(self, context, instances, snapshot):
        # Snapshot the VM
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        
        if True:
            snapshot_data_size = vmtasks_openstack.compute_snapshot_data_size(cntx, db, instances, snapshot)
        else:
            snapshot_data_size = vmtasks_vcloud.compute_snapshot_data_size(cntx, db, instances, snapshot)
        
        db.snapshot_update(cntx, snapshot_obj.id, {'size': snapshot_data_size,})
                
    @autolog.log_method(Logger, 'GetSnapshotDataSize.revert')    
    def revert_with_log(self, *args, **kwargs):
        pass    
            
class UploadSnapshot(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'UploadSnapshot.execute')    
    def execute_with_log(self, context, instance, snapshot):
        # Upload snapshot data to swift endpoint
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        
        if True:
            return vmtasks_openstack.upload_snapshot(cntx, db, instance, snapshot)
        else:
            return vmtasks_vcloud.upload_snapshot(cntx, db, instance, snapshot)
        
        db.snapshot_vm_update(cntx, instance['vm_id'], snapshot_obj.id, {'status': 'available',})        
                
    @autolog.log_method(Logger, 'UploadSnapshot.revert')    
    def revert_with_log(self, *args, **kwargs):
        pass
      
class PostSnapshot(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PostSnapshot.execute')    
    def execute_with_log(self, context, instance, snapshot):
        # post processing of snapshot for ex. block commit
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db

        if True:
            ret_val = vmtasks_openstack.post_snapshot(cntx, db, instance, snapshot)
        else:
            ret_val = vmtasks_vcloud.post_snapshot(cntx, db, instance, snapshot)        
        
        db.vm_recent_snapshot_update(cntx, instance['vm_id'], {'snapshot_id': snapshot['id']})
        return ret_val

    @autolog.log_method(Logger, 'PostSnapshot.revert')    
    def revert_with_log(self, *args, **kwargs):
        pass

def UnorderedPauseVMs(instances):
    flow = uf.Flow("pausevmsuf")
    for index,item in enumerate(instances):
        flow.add(PauseVM("PauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    return flow

# Assume there is dependency between instances
# pause each VM in the order that appears in the array.
def LinearPauseVMs(instances):
    flow = lf.Flow("pausevmslf")
    for index,item in enumerate(instances):
        flow.add(PauseVM("PauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

# Assume there is no ordering dependency between instances
# snapshot each VM in parallel.
def UnorderedSnapshotVMs(instances):
    flow = uf.Flow("snapshotvmuf")
    for index,item in enumerate(instances):
        flow.add(SnapshotVM("SnapshotVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

# Assume there is dependency between instances
# snapshot each VM in the order that appears in the array.
def LinearSnapshotVMs(instances):
    flow = lf.Flow("snapshotvmlf")
    for index,item in enumerate(instances):
        flow.add(SnapshotVM("SnapshotVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

# Assume there is no ordering dependency between instances
# resume each VM in parallel. Usually there should not be any
# order in which vms should be resumed.
def UnorderedUnPauseVMs(instances):
    flow = uf.Flow("unpausevmsuf")
    for index,item in enumerate(instances):
        flow.add(UnPauseVM("UnpauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def LinearUnPauseVMs(instances):
    flow = lf.Flow("unpausevmslf")
    for index,item in enumerate(instances):
        flow.add(UnPauseVM("UnPauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def UnorderedUploadSnapshot(instances):
    flow = uf.Flow("uploadsnapshotuf")
    for index,item in enumerate(instances):
        flow.add(UploadSnapshot("UploadSnapshot_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def UnorderedPostSnapshot(instances):
    flow = uf.Flow("postsnapshotuf")
    for index,item in enumerate(instances):
        flow.add(PostSnapshot("PostSnapshot_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))

    return flow

def CreateVMSnapshotDBEntries(context, instances, snapshot):
    #create an entry for the VM in the workloadmgr database
    cntx = amqp.RpcContext.from_dict(context)
    db = WorkloadMgrDB().db
    for instance in instances:
        options = {'vm_id': instance['vm_id'],
                   'vm_name': instance['vm_name'],
                   'snapshot_id': snapshot['id'],
                   'snapshot_type': snapshot['snapshot_type'],
                   'status': 'creating',}
        snapshot_vm = db.snapshot_vm_create(cntx, options)

