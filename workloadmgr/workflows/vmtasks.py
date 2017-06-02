#secgroup vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement application
specific flows

"""

import os
import uuid
import cPickle as pickle
from Queue import Queue
import json
import shutil

from oslo.config import cfg

from taskflow import engines
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow import task

from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.virt import driver
from workloadmgr.virt import qemuimages
from workloadmgr.vault import vault
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import jsonutils
from workloadmgr.openstack.common import timeutils
from workloadmgr.workloads import workload_utils
from workloadmgr import autolog
from workloadmgr import utils

import vmtasks_openstack
import vmtasks_vcloud

from workloadmgr import exception

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

vmtasks_opts = []

CONF = cfg.CONF
CONF.register_opts(vmtasks_opts)


POWER_STATES = {
    0: "NO STATE",
    1: "RUNNING",
    2: "BLOCKED",
    3: "PAUSED",
    4: "SHUTDOWN",
    5: "SHUTOFF",
    6: "CRASHED",
    7: "SUSPENDED",
    8: "FAILED",
    9: "BUILDING",
}

class NoneTask(task.Task):
    def execute(self):
        pass
    
    def revert(self, *args, **kwargs):
        pass

class RestoreVMNetworks(task.Task):
    def execute(self, context, target_platform, restore):
        return self.execute_with_log(context, target_platform, restore)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    

    @autolog.log_method(Logger, 'RestoreVMNetworks.execute')
    def execute_with_log(self, context, target_platform, restore):
        # Restore the networking configuration of VMs
        self.db = db = WorkloadMgrDB().db
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.target_platform = target_platform

        db.restore_get_metadata_cancel_flag(cntx, restore['id'])
      
        if target_platform == 'openstack':
            self.restored_net_resources = vmtasks_openstack.restore_vm_networks(cntx, db, restore)
        else:
            self.restored_net_resources = vmtasks_vcloud.restore_vm_networks(cntx, db, restore)

        return self.restored_net_resources

    @autolog.log_method(Logger, 'RestoreVMNetworks.revert') 
    def revert_with_log(self, *args, **kwargs):
        try:
            if self.restored_net_resources:
                if self.target_platform == 'openstack':
                    vmtasks_openstack.delete_vm_networks(self.cntx,
                                                         self.restored_net_resources)
                else:
                    vmtasks_vcloud.delete_vm_networks(self.cntx,
                                                      self.restored_net_resources)
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass

class RestoreSecurityGroups(task.Task):
    def execute(self, context, target_platform, restore):
        return self.execute_with_log(context, target_platform, restore)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    

    @autolog.log_method(Logger, 'RestoreSecurityGroups.execute')
    def execute_with_log(self, context, target_platform, restore):
        # Restore the security groups
        self.db = db = WorkloadMgrDB().db
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.target_platform = target_platform

        self.security_groups = None
        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        if target_platform == 'openstack':
            self.security_groups =  vmtasks_openstack.restore_vm_security_groups(cntx, db, restore)
        else:
            self.security_groups =  vmtasks_vcloud.restore_vm_security_groups(cntx, db, restore)

        return self.security_groups

    @autolog.log_method(Logger, 'RestoreSecurityGroups.revert') 
    def revert_with_log(self, *args, **kwargs):
        try:
            if self.security_groups:
                if self.target_platform == 'openstack':
                    vmtasks_openstack.delete_vm_security_groups(self.cntx,
                                                        self.security_groups)
                else:
                    vmtasks_vcloud.delete_vm_security_groups(self.cntx,
                                                        self.security_groups)
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass

class RestoreKeypairs(task.Task):
    def execute(self, context, target_platform, instances, restore):
        return self.execute_with_log(context, target_platform, instances, restore)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreKeypairs.execute')
    def execute_with_log(self, context, target_platform, instances, restore):
        # Restore keypairs
        self.db = db = WorkloadMgrDB().db
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.target_platform = target_platform

        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        if target_platform == 'openstack':
            vmtasks_openstack.restore_keypairs(cntx, db, instances)

        return

    @autolog.log_method(Logger, 'RestoreKeypairs.revert') 
    def revert_with_log(self, *args, **kwargs):
        pass


class PreRestore(task.Task):

    def execute(self, context, target_platform, instance, restore):
        return self.execute_with_log(context, target_platform, instance, restore)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PreRestore.execute')
    def execute_with_log(self, context, target_platform, instance, restore):
        # pre processing of restore
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db

        db.restore_get_metadata_cancel_flag(cntx, restore['id'])   

        if target_platform == 'openstack':
            return vmtasks_openstack.pre_restore_vm(cntx, db, instance, restore)
        else:
            return vmtasks_vcloud.pre_restore_vm(cntx, db, instance, restore)

    @autolog.log_method(Logger, 'PreRestore.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.restore_update(cntx, kwargs['restore']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass

class RestoreVM(task.Task):

    def execute(self, context, target_platform, instance, restore, 
                restored_net_resources, restored_security_groups):
        return self.execute_with_log(context, target_platform, instance, restore, 
                                     restored_net_resources, restored_security_groups)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'RestoreVM.execute')
    def execute_with_log(self, context, target_platform, instance, restore, 
                         restored_net_resources, restored_security_groups):
        # Snapshot the VM
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        if target_platform == 'openstack':
            ret_val = vmtasks_openstack.restore_vm(cntx, db, instance, restore, 
                                                   restored_net_resources, restored_security_groups)
        else:
            ret_val = vmtasks_vcloud.restore_vm(cntx, db, instance, restore, 
                                                restored_net_resources, restored_security_groups)
        
        return {'vm_name':ret_val.vm_name, 'vm_id': ret_val.vm_id, 'uuid': ret_val.vm_id}
    
    @autolog.log_method(Logger, 'RestoreVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.restore_update(cntx, kwargs['restore']['id'], {'status': 'error',})
            if kwargs['target_platform'] == 'openstack':
                vmtasks_openstack.delete_restored_vm(cntx, db, kwargs['instance'], kwargs['restore'])
            else:
                vmtasks_vcloud.delete_restored_vm(cntx, db, kwargs['instance'], kwargs['restore'])             
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass        


class RestoreVMData(task.Task):

    def execute(self, context, target_platform, instance, restore):
        return self.execute_with_log(context, target_platform, instance, restore)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'RestoreVM.execute')
    def execute_with_log(self, context, target_platform, instance, restore):
        # Restore the VM Data
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        ret_val = vmtasks_openstack.restore_vm_data(cntx, db, instance, restore)
        
        return {'vm_name':ret_val.vm_name, 'vm_id': ret_val.vm_id, 'uuid': ret_val.vm_id}
    
    @autolog.log_method(Logger, 'RestoreVMData.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.restore_update(cntx, kwargs['restore']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass        


class PowerOnVM(task.Task):

    def execute(self, context, target_platform, instance, restore, restored_instance):
        return self.execute_with_log(context, target_platform, instance, restore, restored_instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PowerOnVM.execute')
    def execute_with_log(self, context, target_platform, instance, restore, restored_instance):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        if target_platform == 'openstack':
            return vmtasks_openstack.poweron_vm(cntx, instance, restore, restored_instance)
        else:
            return vmtasks_vcloud.poweron_vm(cntx, instance, restore, restored_instance)

    @autolog.log_method(Logger, 'PowerOnVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.restore_update(cntx, kwargs['restore']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass


class PowerOffVM(task.Task):

    def execute(self, context, target_platform, instance, restore, restored_instance):
        return self.execute_with_log(context, target_platform, instance, restore, restored_instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PowerOffVM.execute')
    def execute_with_log(self, context, target_platform, instance, restore, restored_instance):
        # PowerOff the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        if target_platform == 'openstack':
            return vmtasks_openstack.poweroff_vm(cntx, instance, restore, restored_instance)
        else:
            return vmtasks_vcloud.poweroff_vm(cntx, instance, restore, restored_instance)

    @autolog.log_method(Logger, 'PowerOffVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.restore_update(cntx, kwargs['restore']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass


class SetVMMetadata(task.Task):

    def execute(self, context, target_platform, instance, restore, restored_instance):
        return self.execute_with_log(context, target_platform, instance, restore, restored_instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'SetVMMetadata.execute')
    def execute_with_log(self, context, target_platform, instance, restore, restored_instance):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        if target_platform == 'openstack':
            return vmtasks_openstack.set_vm_metadata(cntx, db, instance, restore, restored_instance)
        else:
            return vmtasks_vcloud.set_vm_metadata(cntx, db, instance, restore, restored_instance)

    @autolog.log_method(Logger, 'SetVMMetadata.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.restore_update(cntx, kwargs['restore']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass


class PostRestore(task.Task):

    def execute(self, context, target_platform, instance, restore):
        return self.execute_with_log(context, target_platform, instance, restore)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PostRestore.execute')    
    def execute_with_log(self, context, target_platform, instance, restore):
        # post processing of restore
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db

        db.restore_get_metadata_cancel_flag(cntx, restore['id'])

        if target_platform == 'openstack':
            ret_val = vmtasks_openstack.post_restore_vm(cntx, db, instance, restore)
        else:
            ret_val = vmtasks_vcloud.post_restore_vm(cntx, db, instance, restore)        

        return ret_val

    @autolog.log_method(Logger, 'PostRestore.revert')    
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.restore_update(cntx, kwargs['restore']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass            

class SnapshotVMNetworks(task.Task):
        
    def execute(self, context, source_platform, instances, snapshot):
        return self.execute_with_log(context, source_platform, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    

    @autolog.log_method(Logger, 'SnapshotVMNetworks.execute')
    def execute_with_log(self, context, source_platform, instances, snapshot):
        # Snapshot the networking configuration of VMs
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        # refresh the VM configuration such as network etc
        if source_platform == "vmware":
            compute_service = nova.API(production=True)
            search_opts = {}
            search_opts['vmref'] = '1'
            for instance in instances:
                newinst = compute_service.get_server_by_id(cntx,
                                           instance['vm_metadata']['vmware_uuid'],
                                           search_opts=search_opts)

        return vmtasks_openstack.snapshot_vm_networks(cntx, db, instances, snapshot)
        """
        if source_platform == 'openstack':
            return vmtasks_openstack.snapshot_vm_networks(cntx, db, instances, snapshot)
        else:
            return vmtasks_vcloud.snapshot_vm_networks(cntx, db, instances, snapshot)
        """

    @autolog.log_method(Logger, 'SnapshotVMNetworks.revert') 
    def revert_with_log(self, *args, **kwargs):
        pass
        
class SnapshotVMFlavors(task.Task):

    def execute(self, context, source_platform, instances, snapshot):
        return self.execute_with_log(context, source_platform, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
      
    @autolog.log_method(Logger, 'SnapshotVMFlavors.execute')
    def execute_with_log(self, context, source_platform, instances, snapshot):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
  
        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        return vmtasks_openstack.snapshot_vm_flavors(cntx, db, instances, snapshot)
        """
        if source_platform == 'openstack':
            return vmtasks_openstack.snapshot_vm_flavors(cntx, db, instances, snapshot)
        else:
            return vmtasks_vcloud.snapshot_vm_flavors(cntx, db, instances, snapshot)
        """
          
    @autolog.log_method(Logger, 'SnapshotVMFlavors.revert')
    def revert_with_log(self, *args, **kwargs):
        pass
    
class SnapshotVMSecurityGroups(task.Task):

    def execute(self, context, source_platform, instances, snapshot):
        return self.execute_with_log(context, source_platform, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
      
    @autolog.log_method(Logger, 'SnapshotVMSecurityGroups.execute')
    def execute_with_log(self, context, source_platform, instances, snapshot):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        if source_platform == 'openstack':
            return vmtasks_openstack.snapshot_vm_security_groups(cntx, db, instances, snapshot)
        else:
            return vmtasks_vcloud.snapshot_vm_security_groups(cntx, db, instances, snapshot)
          
    @autolog.log_method(Logger, 'SnapshotVMSecurityGroups.revert')
    def revert_with_log(self, *args, **kwargs):
        pass    
                            
class PauseVM(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
    
    @autolog.log_method(Logger, 'PauseVM.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # Pause the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        if POWER_STATES[instance['vm_power_state']] != 'RUNNING':
            return

        if source_platform == 'openstack':
            return vmtasks_openstack.pause_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.pause_vm(cntx, db, instance)


    @autolog.log_method(Logger, 'PauseVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db

            if POWER_STATES[kwargs['instance']['vm_power_state']] != 'RUNNING':
                return        

            if kwargs['source_platform'] == 'openstack':
                return vmtasks_openstack.unpause_vm(cntx, db, kwargs['instance'])
            else:
                return vmtasks_vcloud.unpause_vm(cntx, db, kwargs['instance'])  
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',})    
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass                     
        
class UnPauseVM(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'UnPauseVM.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # UnPause the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if POWER_STATES[instance['vm_power_state']] != 'RUNNING':
            return

        if source_platform == 'openstack':
            return vmtasks_openstack.unpause_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.unpause_vm(cntx, db, instance)

    @autolog.log_method(Logger, 'UnPauseVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass
        
class SuspendVM(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'SuspendVM.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if POWER_STATES[instance['vm_power_state']] != 'RUNNING':
            return
        if source_platform == 'openstack':
            return vmtasks_openstack.suspend_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.suspend_vm(cntx, db, instance)

    @autolog.log_method(Logger, 'SuspendVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            if POWER_STATES[kwargs['instance']['vm_power_state']] != 'RUNNING':
                return        
            if kwargs['source_platform'] == 'openstack':
                return vmtasks_openstack.resume_vm(cntx, db, kwargs['instance'])
            else:
                return vmtasks_vcloud.resume_vm(cntx, db, kwargs['instance'])
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass             

class ResumeVM(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'ResumeVM.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        if POWER_STATES[instance['vm_power_state']] != 'RUNNING':
            return
        if source_platform == 'openstack':
            return vmtasks_openstack.resume_vm(cntx, db, instance)
        else:
            return vmtasks_vcloud.resume_vm(cntx, db, instance)

    @autolog.log_method(Logger, 'ResumeVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass             
    
class PreSnapshot(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PreSnapshot.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # pre processing of snapshot
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db

        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])
        
        if source_platform == 'openstack':
            return vmtasks_openstack.pre_snapshot_vm(cntx, db, instance, snapshot)
        else:
            return vmtasks_vcloud.pre_snapshot_vm(cntx, db, instance, snapshot)
 
    @autolog.log_method(Logger, 'PreSnapshot.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass               
        
class FreezeVM(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'FreezeVM.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # freeze an instance
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        if POWER_STATES[instance['vm_power_state']] != 'RUNNING':
            return        

        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        if source_platform == 'openstack':
            return vmtasks_openstack.freeze_vm(cntx, db, instance, snapshot)
        else:
            return vmtasks_vcloud.freeze_vm(cntx, db, instance, snapshot)


    @autolog.log_method(Logger, 'FreezeVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            if kwargs['source_platform'] == 'openstack':
                return vmtasks_openstack.thaw_vm(cntx, db, kwargs['instance'], kwargs['snapshot'])
            else:
                return vmtasks_vcloud.thaw_vm(cntx, db, kwargs['instance'], kwargs['snapshot'])
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass                              

class ThawVM(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'ThawVM.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # freeze an instance
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        if POWER_STATES[instance['vm_power_state']] != 'RUNNING':
            return        
        if source_platform == 'openstack':
            return vmtasks_openstack.thaw_vm(cntx, db, instance, snapshot)
        else:
            return vmtasks_vcloud.thaw_vm(cntx, db, instance, snapshot)

    @autolog.log_method(Logger, 'ThawVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass
           
class SnapshotVM(task.Task):

    def execute(self, context, source_platform, instance, snapshot):
        return self.execute_with_log(context, source_platform, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'SnapshotVM.execute')
    def execute_with_log(self, context, source_platform, instance, snapshot):
        # Snapshot the VM
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        if source_platform == 'openstack':
            ret_val = vmtasks_openstack.snapshot_vm(cntx, db, instance, snapshot)
        else:
            ret_val = vmtasks_vcloud.snapshot_vm(cntx, db, instance, snapshot)
        
        return ret_val
    
    @autolog.log_method(Logger, 'SnapshotVM.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'],
                                  kwargs['snapshot']['id'], {'status': 'error',})        
            db.vm_recent_snapshot_update(cntx, kwargs['instance']['vm_id'],
                                  {'snapshot_id': kwargs['snapshot']['id']})
    
            if 'result' in kwargs:
                result = kwargs['result']
                if kwargs['source_platform'] == 'openstack':
                    vmtasks_openstack.revert_snapshot(cntx, db, kwargs['instance'],
                                   kwargs['snapshot'], result)
                else:
                    vmtasks_vcloud.revert_snapshot(cntx, db, kwargs['instance'],
                                   kwargs['snapshot'], result)
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass                     
  
class SnapshotDataSize(task.Task):

    def execute(self, context, source_platform, instance, snapshot, snapshot_data):
        return self.execute_with_log(context, source_platform, instance, snapshot, snapshot_data)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    
    
    @autolog.log_method(Logger, 'GetSnapshotDataSize.execute')    
    def execute_with_log(self, context, source_platform, instance, snapshot, snapshot_data):
        # Snapshot the VM
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])

        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])
        
        if source_platform == 'openstack':
            snapshot_data_ex = vmtasks_openstack.get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data)
        else:
            snapshot_data_ex = vmtasks_vcloud.get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data)

        db.snapshot_vm_update(cntx, instance['vm_id'], snapshot_obj.id, {'size': snapshot_data_ex['vm_data_size'],})
        
        return snapshot_data_ex        
    @autolog.log_method(Logger, 'GetSnapshotDataSize.revert')    
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',}) 
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass             
            
class UploadSnapshot(task.Task):

    def execute(self, context, source_platform, instance, snapshot, snapshot_data_ex):
        return self.execute_with_log(context, source_platform, instance, snapshot, snapshot_data_ex)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'UploadSnapshot.execute')    
    def execute_with_log(self, context, source_platform, instance, snapshot, snapshot_data_ex):
        # Upload snapshot data to swift endpoint
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        
        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        snapshot_data_size = 0
        for vm in db.snapshot_vms_get(cntx, snapshot_obj.id):
            snapshot_data_size = snapshot_data_size + vm.size 
        LOG.debug(_("snapshot_data_size: %(snapshot_data_size)s") %{'snapshot_data_size': snapshot_data_size,})
        db.snapshot_update(cntx, snapshot_obj.id, {'size': snapshot_data_size,})
        
        if source_platform == 'openstack':
            ret_val = vmtasks_openstack.upload_snapshot(cntx, db, instance, snapshot, snapshot_data_ex)
        else:
            ret_val = vmtasks_vcloud.upload_snapshot(cntx, db, instance, snapshot, snapshot_data_ex)
        
        db.snapshot_vm_update(cntx, instance['vm_id'], snapshot_obj.id, {'status': 'available',})  
        
        return ret_val      
                
    @autolog.log_method(Logger, 'UploadSnapshot.revert')    
    def revert_with_log(self, *args, **kwargs):
        cntx = amqp.RpcContext.from_dict(kwargs['context'])
        db = WorkloadMgrDB().db
        db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',})
      
class PostSnapshot(task.Task):

    def execute(self, context, source_platform, instance, snapshot, snapshot_data):
        return self.execute_with_log(context, source_platform, instance, snapshot, snapshot_data)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PostSnapshot.execute')    
    def execute_with_log(self, context, source_platform, instance, snapshot, snapshot_data):
        # post processing of snapshot for ex. block commit
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db

        if source_platform == 'openstack':
            ret_val = vmtasks_openstack.post_snapshot(cntx, db, instance, snapshot, snapshot_data)
        else:
            ret_val = vmtasks_vcloud.post_snapshot(cntx, db, instance, snapshot, snapshot_data)        

        db.vm_recent_snapshot_update(cntx, instance['vm_id'], {'snapshot_id': snapshot['id']})
 
        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        return ret_val

    @autolog.log_method(Logger, 'PostSnapshot.revert')    
    def revert_with_log(self, *args, **kwargs):
        try:
            cntx = amqp.RpcContext.from_dict(kwargs['context'])
            db = WorkloadMgrDB().db
            db.snapshot_vm_update(cntx, kwargs['instance']['vm_id'], kwargs['snapshot']['id'], {'status': 'error',})
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass             

class ApplyRetentionPolicy(task.Task):

    def execute(self, context, source_platform, instances, snapshot):
        return self.execute_with_log(context, source_platform, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
      
    @autolog.log_method(Logger, 'ApplyRetentionPolicy.execute')
    def execute_with_log(self, context, source_platform, instances, snapshot):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

        if source_platform == 'openstack':
            return vmtasks_openstack.apply_retention_policy(cntx, db, instances, snapshot)
        else:
            return vmtasks_vcloud.apply_retention_policy(cntx, db, instances, snapshot)
          
    @autolog.log_method(Logger, 'ApplyRetentionPolicy.revert')
    def revert_with_log(self, *args, **kwargs):       
        pass
    
class PrepareBackupImage(task.Task):
    """
       Downloads objects in the backup chain and creates linked qcow2 image
    """

    def execute(self, context, mount_id, snapshot_id, vm_resource_id):
        return self.execute_with_log(context, mount_id, snapshot_id, vm_resource_id)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'PrepareBackupImage.execute')
    def execute_with_log(self, context, mount_id, snapshot_id, vm_resource_id):

        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        snapshot_obj = db.snapshot_get(cntx, snapshot_id)
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        snapshot_vm_resource = db.snapshot_vm_resource_get(cntx, vm_resource_id)

        backup_endpoint = self.db.get_metadata_value(workload_obj.metadata,
                                                     'backup_media_target')
        backup_target = vault.get_backup_target(backup_endpoint)

        snapshot_vm_resource_object_store_transfer_time =\
              workload_utils.download_snapshot_vm_resource_from_object_store(cntx,
                                                                             mount_id,
                                                                             snapshot_id,
                                                                             snapshot_vm_resource.id)

        snapshot_vm_object_store_transfer_time = snapshot_vm_resource_object_store_transfer_time
        snapshot_vm_data_transfer_time  =  snapshot_vm_resource_object_store_transfer_time
        temp_directory = os.path.join("/var/triliovault", mount_id, vm_resource_id)
        try:
            shutil.rmtree( temp_directory )
        except OSError as exc:
            pass
        fileutils.ensure_tree(temp_directory)

        commit_queue = Queue() # queue to hold the files to be committed

        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
        disk_format = db.get_metadata_value(vm_disk_resource_snap.metadata, 'disk_format')
        disk_filename_extention = db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format')

        restored_file_path =temp_directory + '/' + vm_disk_resource_snap.id + \
                                '_' + snapshot_vm_resource.resource_name + '.' \
                                + disk_filename_extention
        restored_file_path = restored_file_path.replace(" ", "")            

        vault_path = os.path.join(backup_target.mount_path,
                                  vm_disk_resource_snap.vault_path)
        image_attr = qemuimages.qemu_img_info(vault_path)
        if disk_format == 'qcow2' and image_attr.file_format == 'raw':
            qemuimages.convert_image(vault_path, restored_file_path, 'qcow2')
        else:
            shutil.copyfile(vault_path, restored_file_path)

        while vm_disk_resource_snap.vm_disk_resource_snap_backing_id is not None:
            vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(cntx,
                                                    vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            disk_format = db.get_metadata_value(vm_disk_resource_snap_backing.metadata,'disk_format')
            snapshot_vm_resource_backing = db.snapshot_vm_resource_get(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
            restored_file_path_backing =temp_directory + '/' + vm_disk_resource_snap_backing.id + \
                                            '_' + snapshot_vm_resource_backing.resource_name + '.' \
                                            + disk_filename_extention
            restored_file_path_backing = restored_file_path_backing.replace(" ", "")
            vault_path = os.path.join(backup_target.mount_path,
                                      vm_disk_resource_snap_backing.vault_path)
            image_attr = qemuimages.qemu_img_info(vault_path)
            if disk_format == 'qcow2' and image_attr.file_format == 'raw':
                qemuimages.convert_image(vault_path, restored_file_path_backing, 'qcow2')
            else:
                shutil.copyfile(vault_path, restored_file_path_backing)
  
            #rebase
            image_info = qemuimages.qemu_img_info(restored_file_path)
            image_backing_info = qemuimages.qemu_img_info(restored_file_path_backing)

            #increase the size of the base image
            if image_backing_info.virtual_size < image_info.virtual_size :
                qemuimages.resize_image(restored_file_path_backing, image_info.virtual_size)  

            #rebase the image                            
            qemuimages.rebase_qcow2(restored_file_path_backing, restored_file_path)

            commit_queue.put(restored_file_path)
            vm_disk_resource_snap = vm_disk_resource_snap_backing
            restored_file_path = restored_file_path_backing

        while commit_queue.empty() is not True:
            file_to_commit = commit_queue.get_nowait()
            try:
                LOG.debug('Commiting QCOW2 ' + file_to_commit)
                qemuimages.commit_qcow2(file_to_commit)
            except Exception, ex:
                LOG.exception(ex)                       

            if restored_file_path != file_to_commit:
                utils.delete_if_exists(file_to_commit)

        image_info = qemuimages.qemu_img_info(restored_file_path)
        self.virtual_size = image_info.virtual_size
        self.restored_file_path = restored_file_path

        return (restored_file_path, image_info.virtual_size)

    @autolog.log_method(Logger, 'PrepareBackupImage.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            if self.restored_file_path:
                os.remove(self.restored_file_path)
        except:
            pass
        
    
def UnorderedPreSnapshot(instances):
    flow = uf.Flow("presnapshotuf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + item['vm_id'])
        flow.add(PreSnapshot("PreSnapshot_" + item['vm_id'], rebind=rebind_dict))

    return flow

def UnorderedFreezeVMs(instances):
    flow = uf.Flow("freezevmsuf")
    for index,item in enumerate(instances):
        flow.add(FreezeVM("FreezeVM_" + item['vm_id'], rebind=dict(instance = "instance_" + item['vm_id'])))
    return flow

def LinearFreezeVMs(instances):
    flow = lf.Flow("freezevmslf")
    for index,item in enumerate(instances):
        flow.add(FreezeVM("FreezeVM_" + item['vm_id'], rebind=dict(instance = "instance_" + item['vm_id'])))
    
    return flow

def UnorderedPauseVMs(instances):
    flow = uf.Flow("pausevmsuf")
    if instances[0]['pause_at_snapshot'] == True:
       for index,item in enumerate(instances):
            flow.add(PauseVM("PauseVM_" + item['vm_id'],
                     rebind=dict(instance = "instance_" + item['vm_id'])))
    else:
        flow.add(NoneTask("UnorderedPauseVMs"))
    return flow

# Assume there is dependency between instances
# pause each VM in the order that appears in the array.

def LinearPauseVMs(instances):
    flow = lf.Flow("pausevmslf")
    if instances[0]['pause_at_snapshot'] == True:
        for index,item in enumerate(instances):
            flow.add(PauseVM("PauseVM_" + item['vm_id'],
                     rebind=dict(instance = "instance_" + item['vm_id'])))
    else:
        flow.add(NoneTask("LinearPauseVMs"))
    
    return flow

# Assume there is no ordering dependency between instances
# snapshot each VM in parallel.

def UnorderedSnapshotVMs(instances):
    flow = uf.Flow("snapshotvmuf")
    for index,item in enumerate(instances):
        flow.add(SnapshotVM("SnapshotVM_" + item['vm_id'], rebind=dict(instance = "instance_" + item['vm_id']), 
                            provides='snapshot_data_' + str(item['vm_id'])))
    
    return flow


# Assume there is dependency between instances
# snapshot each VM in the order that appears in the array.

def LinearSnapshotVMs(instances):
    flow = lf.Flow("snapshotvmlf")
    for index,item in enumerate(instances):
        flow.add(SnapshotVM("SnapshotVM_" + item['vm_id'], rebind=dict(instance = "instance_" + item['vm_id']), 
                            provides='snapshot_data_' + str(item['vm_id'])))
    
    return flow

# Assume there is no ordering dependency between instances
# resume each VM in parallel. Usually there should not be any
# order in which vms should be resumed.

def UnorderedUnPauseVMs(instances):
    flow = uf.Flow("unpausevmsuf")
    for index,item in enumerate(instances):
        if item['pause_at_snapshot'] == True:
            flow.add(UnPauseVM("UnPauseVM_" + item['vm_id'],
                     rebind=dict(instance = "instance_" + item['vm_id'])))
        else:
             flow.add(NoneTask("UnorderedUnPauseVMs" + item['vm_id']))
    
    return flow

def LinearUnPauseVMs(instances):
    flow = lf.Flow("unpausevmslf")
    for index,item in enumerate(instances):
        if item['pause_at_snapshot'] == True:
            flow.add(UnPauseVM("UnPauseVM_" + item['vm_id'],
                     rebind=dict(instance = "instance_" + item['vm_id'])))
        else:
             flow.add(NoneTask("LinearUnPauseVMs" + item['vm_id']))

    return flow

def UnorderedThawVMs(instances):
    flow = uf.Flow("thawvmsuf")
    for index,item in enumerate(instances):
        flow.add(ThawVM("ThawVM_" + item['vm_id'], rebind=dict(instance = "instance_" + item['vm_id'])))
    return flow

def LinearThawVMs(instances):
    flow = lf.Flow("thawvmslf")
    for index,item in enumerate(instances):
        flow.add(ThawVM("ThawVM_" + item['vm_id'], rebind=dict(instance = "instance_" + item['vm_id'])))
    
    return flow

def UnorderedSnapshotDataSize(instances):
    flow = uf.Flow("snapshotdatasizeuf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + item['vm_id'], snapshot_data = "snapshot_data_" + str(item['vm_id']))
        flow.add(SnapshotDataSize("SnapshotDataSize_" + item['vm_id'], rebind=rebind_dict,
                                  provides='snapshot_data_ex_' + str(item['vm_id'])))
    
    return flow

def LinearSnapshotDataSize(instances):
    flow = lf.Flow("snapshotdatasizelf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + item['vm_id'], snapshot_data = "snapshot_data_" + str(item['vm_id']))
        flow.add(SnapshotDataSize("SnapshotDataSize_" + item['vm_id'], rebind=rebind_dict,
                                  provides='snapshot_data_ex_' + str(item['vm_id'])))
    
    return flow

def UnorderedUploadSnapshot(instances):
    flow = uf.Flow("uploadsnapshotuf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + item['vm_id'], snapshot_data_ex = "snapshot_data_ex_" + str(item['vm_id']))
        flow.add(UploadSnapshot("UploadSnapshot_" + item['vm_id'], rebind=rebind_dict))
    
    return flow

def LinearUploadSnapshot(instances):
    flow = lf.Flow("uploadsnapshotlf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + item['vm_id'],
                           snapshot_data_ex = "snapshot_data_ex_" + str(item['vm_id']))
        flow.add(UploadSnapshot("UploadSnapshot_" + item['vm_id'], rebind=rebind_dict))
    
    return flow

def UnorderedPostSnapshot(instances):
    flow = uf.Flow("postsnapshotuf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + item['vm_id'],
                           snapshot_data = "snapshot_data_" + str(item['vm_id']))
        flow.add(PostSnapshot("PostSnapshot_" + item['vm_id'], rebind=rebind_dict))

    return flow

def LinearPostSnapshot(instances):
    flow = lf.Flow("postsnapshotlf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + item['vm_id'],
                            snapshot_data = "snapshot_data_" + str(item['vm_id']))
        flow.add(PostSnapshot("PostSnapshot_" + item['vm_id'], rebind=rebind_dict))

    return flow

def CreateVMSnapshotDBEntries(context, instances, snapshot):
    #create an entry for the VM in the workloadmgr database
    cntx = amqp.RpcContext.from_dict(context)
    db = WorkloadMgrDB().db
    for instance in instances:
        options = {'vm_id': instance['vm_id'],
                   'vm_name': instance['vm_name'],
                   'metadata': instance['vm_metadata'],
                   'snapshot_id': snapshot['id'],
                   'snapshot_type': snapshot['snapshot_type'],
                   'status': 'creating',}
        snapshot_vm = db.snapshot_vm_create(cntx, options)


def UnorderedPreRestore(instances):
    flow = uf.Flow("prerestoreuf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + str(index))
        flow.add(PreRestore("PreRestore_" + item['vm_id'], rebind=rebind_dict))

    return flow

# Assume there is no ordering dependency between instances
# restore each VM in parallel.

def UnorderedRestoreVMs(instances):
    flow = uf.Flow("restorevmuf")
    for index,item in enumerate(instances):
        flow.add(RestoreVM("RestoreVM_" + item['vm_id'], 
                           rebind=dict(instance = "instance_" + str(index)),
                           provides='restored_instance_' + str(index)))
    
    return flow

# Assume there is dependency between instances
# snapshot each VM in the order that appears in the array.

def LinearRestoreVMs(instances):
    flow = lf.Flow("restorevmlf")
    for index,item in enumerate(instances):
        flow.add(RestoreVM("RestoreVM_" + item['vm_id'], 
                           rebind=dict(instance = "instance_" + str(index)),
                           provides='restored_instance_' + str(index)))
    
    return flow

# Assume there is dependency between instances
# snapshot each VM in the order that appears in the array.

def LinearRestoreVMsData(instances):
    flow = lf.Flow("restorevmdatalf")
    for index,item in enumerate(instances):
        flow.add(RestoreVMData("RestoreVMData_" + item['vm_id'],
                               rebind=dict(instance="instance_" + str(index))))
    
    return flow


def LinearPowerOnVMs(instances):
    flow = lf.Flow("poweronvmlf")
    for index,item in enumerate(instances):
        rebind_dict = dict(restored_instance = "restored_instance_" + str(index), instance = "instance_" + str(index))
        flow.add(PowerOnVM("PowerOnVM_" + item['vm_id'], rebind=rebind_dict))
    return flow

def LinearPowerOffVMs(instances):
    flow = lf.Flow("poweroffvmlf")
    for index,item in enumerate(instances):
        rebind_dict = dict(restored_instance = "restored_instance_" + str(index), instance = "instance_" + str(index))
        flow.add(PowerOffVM("PowerOffVM_" + item['vm_id'], rebind=rebind_dict))
    return flow

def LinearSetVMsMetadata(instances):
    flow = lf.Flow("setvmsmetadata")
    for index,item in enumerate(instances):
        rebind_dict = dict(restored_instance = "restored_instance_" + str(index), instance = "instance_" + str(index))
        flow.add(SetVMMetadata("SetVMMetadata_" + item['vm_id'], rebind=rebind_dict))
    return flow

def UnorderedPostRestore(instances):
    flow = uf.Flow("postrestoreuf")
    for index,item in enumerate(instances):
        rebind_dict = dict(instance = "instance_" + str(index))
        flow.add(PostRestore("PostRestore_" + item['vm_id'], rebind=rebind_dict))

    return flow

def LinearPrepareBackupImages(context, instance, snapshotobj):
    flow = lf.Flow("processbackupimageslf")
    db = WorkloadMgrDB().db
    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        flow.add(PrepareBackupImage("PrepareBackupImage" + snapshot_vm_resource.id,
                                    rebind=dict(vm_resource_id=snapshot_vm_resource.id),
                                    provides=('restore_file_path_' + str(snapshot_vm_resource.id),
                                              'image_virtual_size_' + str(snapshot_vm_resource.id))))
    return flow
