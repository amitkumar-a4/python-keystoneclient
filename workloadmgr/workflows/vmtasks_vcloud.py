# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement VMWare Cloud
specific flows
"""

import cPickle as pickle
from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog
from workloadmgr.virt import driver
from workloadmgr.vault import vault
from workloadmgr import utils



LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')

@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_networks')
def snapshot_vm_networks(cntx, db, instances, snapshot):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_flavors')
def snapshot_vm_flavors(cntx, db, instances, snapshot):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_security_groups')        
def snapshot_vm_security_groups(cntx, db, instances, snapshot):
    return None    

@autolog.log_method(Logger, 'vmtasks_vcloud.pause_vm')
def pause_vm(cntx, db, instance):
    return suspend_vm(cntx, db, instance)

@autolog.log_method(Logger, 'vmtasks_vcloud.unpause_vm')
def unpause_vm(cntx, db, instance):
    return resume_vm(cntx, db, instance)    

@autolog.log_method(Logger, 'vmtasks_vcloud.suspend_vm')
def suspend_vm(cntx, db, instance):
    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    return virtdriver.suspend(cntx, db, instance)  
    
@autolog.log_method(Logger, 'vmtasks_vcloud.resume_vm')
def resume_vm(cntx, db, instance):
    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    return virtdriver.resume(cntx, db, instance)  
    
@autolog.log_method(Logger, 'vmtasks_vcloud.pre_snapshot_vm')
def pre_snapshot_vm(cntx, db, instance, snapshot):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.freeze_vm')
def freeze_vm(cntx, db, instance, snapshot):
    pass     

@autolog.log_method(Logger, 'vmtasks_vcloud.thaw_vm')
def thaw_vm(cntx, db, instance, snapshot):
    pass  
    
@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm')
def snapshot_vm(cntx, db, instance, snapshot):
    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    return virtdriver.snapshot_vm(cntx, db, instance, snapshot)  
    
@autolog.log_method(Logger, 'vmtasks_vcloud.get_snapshot_data_size')
def get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data):
    LOG.debug(_("instance: %(instance_id)s") %{'instance_id': instance['vm_id'],})
    vm_data_size = 0;
    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    vm_data_size = virtdriver.get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data)
    LOG.debug(_("vm_data_size: %(vm_data_size)s") %{'vm_data_size': vm_data_size,})
    return vm_data_size
    
@autolog.log_method(Logger, 'vmtasks_vcloud.upload_snapshot')
def upload_snapshot(cntx, db, instance, snapshot, snapshot_data):
    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    virtdriver.upload_snapshot(cntx, db, instance, snapshot, snapshot_data)  
    
@autolog.log_method(Logger, 'vmtasks_vcloud.post_snapshot')
def post_snapshot(cntx, db, instance, snapshot, snapshot_data):
    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    virtdriver.post_snapshot_vm(cntx, db, instance, snapshot, snapshot_data)
      
@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm_flavor')
def restore_vm_flavor(cntx, db, instance, restore):
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm_security_groups')        
def restore_vm_security_groups(cntx, db, restore):
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
def restore_vm(cntx, db, instance, restore, restored_net_resources, restored_security_groups):
    
    restored_compute_flavor = None #restore_vm_flavor(cntx, db, instance,restore)                      
    restored_nics = None #get_vm_nics( cntx, db, instance, restore, restored_net_resources)
    
    restore_obj = db.restore_get(cntx, restore['id']) 
    restore_options = pickle.loads(str(restore_obj.pickle))
    instance_options = utils.get_instance_restore_options(restore_options, instance['vm_id'], 'vmware')
    
    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    return virtdriver.restore_vm( cntx, db, instance, restore, 
                                  restored_net_resources,
                                  restored_security_groups,
                                  restored_compute_flavor,
                                  restored_nics,
                                  instance_options)    
    return None

@autolog.log_method(Logger, 'vmtasks_vcloud.post_restore_vm')
def post_restore_vm(cntx, db, instance, restore):
    return None 
    