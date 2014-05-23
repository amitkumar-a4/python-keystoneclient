# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement VMWare Cloud
specific flows
"""


from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog


LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_networks')
def snapshot_vm_networks(cntx, db, instances, snapshot):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_flavors')
def snapshot_vm_flavors(cntx, db, instances, snapshot):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.pause_vm')
def pause_vm(cntx, db, instance):
    return None    

@autolog.log_method(Logger, 'vmtasks_vcloud.unpause_vm')
def unpause_vm(cntx, db, instance):
    return None    

@autolog.log_method(Logger, 'vmtasks_vcloud.suspend_vm')
def suspend_vm(cntx, db, instance):
    return None
    
@autolog.log_method(Logger, 'vmtasks_vcloud.resume_vm')
def resume_vm(cntx, db, instance):
    return None
    
@autolog.log_method(Logger, 'vmtasks_vcloud.pre_snapshot_vm')
def pre_snapshot_vm(cntx, db, instance, snapshot):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm')
def snapshot_vm(cntx, db, instance, snapshot):
    return None
    
@autolog.log_method(Logger, 'vmtasks_vcloud.get_snapshot_data_size')
def get_snapshot_data_size(cntx, db, instance, snapshot):
    return None
    
@autolog.log_method(Logger, 'vmtasks_vcloud.upload_snapshot')
def upload_snapshot(cntx, db, instance, snapshot):
    return None
    
@autolog.log_method(Logger, 'vmtasks_vcloud.post_snapshot')
def post_snapshot(cntx, db, instance, snapshot):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm_flavor')
def restore_vm_flavor(cntx, db, instance, restore):
    return None
  
@autolog.log_method(Logger, 'vmtasks_vcloud.get_vm_nics')
def get_vm_nics(cntx, db, instance, restore, restored_net_resources): 
    return None
      
@autolog.log_method(Logger, 'vmtasks_vcloud.get_vm_restore_data_size')
def get_vm_restore_data_size(cntx, db, instance, restore):
    return None
        
@autolog.log_method(Logger, 'vmtasks_vcloud.get_vm_restore_data_size')
def get_restore_data_size(cntx, db, restore): 
    return None 

@autolog.log_method(Logger, 'vmtasks_vcloud.get_vm_restore_data_size')                    
def restore_vm_networks(cntx, db, restore):
    return None 

@autolog.log_method(Logger, 'vmtasks_vcloud.pre_restore_vm')
def pre_restore_vm(cntx, db, instance, restore):
    return None
    
@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm')                    
def restore_vm(cntx, db, instance, restore, restored_net_resources):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.post_restore_vm')
def post_restore_vm(cntx, db, instance, restore):
    return None 
    