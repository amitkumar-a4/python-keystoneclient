# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
manages workloads


**Related Flags**

:workloads_topic:  What :mod:`rpc` topic to listen to (default:
                        `workloadmgr-workloads`).
:workloads_manager:  The module name of a class derived from
                          :class:`manager.Manager` (default:
                          :class:`workloadmgr.workload.manager.Manager`).

"""

from sqlalchemy import *
from datetime import datetime, timedelta
import time
import uuid
import cPickle as pickle

from oslo.config import cfg
from workloadmgr import context
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr import manager
from workloadmgr.virt import driver
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.apscheduler.scheduler import Scheduler
from workloadmgr.vault import swift
from workloadmgr.network import neutron


LOG = logging.getLogger(__name__)

workloads_manager_opts = [
    cfg.StrOpt('vault_service',
               default='workloadmgr.vault.swift',
               help='Vault to use for workloads.'),
]

scheduler_config = {'standalone': 'True'}

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)

def workload_callback(workload_id):
    """
    Callback
    """
    #TODO(gbasava): Implementation


class WorkloadMgr(manager.SchedulerDependentManager):
    """Manages workloads """

    RPC_API_VERSION = '1.0'

    def __init__(self, service_name=None, *args, **kwargs):

        self.service = importutils.import_module(FLAGS.vault_service)
        self.az = FLAGS.storage_availability_zone
        self.scheduler = Scheduler(scheduler_config)
        self.scheduler.start()

        super(WorkloadMgr, self).__init__(service_name='workloadscheduler',
                                            *args, **kwargs)
        self.driver = driver.load_compute_driver(None, None)

    def init_host(self):
        """
        Do any initialization that needs to be run if this is a standalone service.
        """

        ctxt = context.get_admin_context()

        LOG.info(_("Cleaning up incomplete workload operations"))

    def workload_create(self, context, workload_id):
        """
        Create a scheduled workload in the workload scheduler
        """
        try:
            workload = self.db.workload_get(context, workload_id)
            #TODO(gbasava): Change it to list of VMs when we support multiple VMs
            vm = self.db.workload_vms_get(context, workload_id)

            LOG.info(_('create_workload started, %s:' %workload_id))
            self.db.workload_update(context, workload_id, {'host': self.host,
                                     'service': FLAGS.vault_service})

            schjob = self.scheduler.add_interval_job(context, workload_callback, hours=24,
                                     name=workload['display_name'], args=[workload_id], 
                                     workload_id=workload_id)
            LOG.info(_('scheduled workload: %s'), schjob.id)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.workload_update(context, workload_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})

        self.db.workload_update(context, workload_id, {'status': 'available',
                                                         'availability_zone': self.az,
                                                         'schedule_job_id':schjob.id})
        LOG.info(_('create_workload finished. workload: %s'), workload_id)

    def workload_delete(self, context, workload_id):
        """
        Delete an existing workload
        """
        workload = self.db.workload_get(context, workload_id)
        LOG.info(_('delete_workload started, workload: %s'), workload_id)
        #TODO(gbasava): Implement

    def _get_metadata_value(self, vm_network_resource_backup, key):
        for metadata in vm_network_resource_backup.metadata:
            if metadata['key'] == key:
                return metadata['value']
                
    def _get_pit_resource_id(self, vm_network_resource_backup, key):
        for metadata in vm_network_resource_backup.metadata:
            if metadata['key'] == key:
                pit_id = metadata['value']
                return pit_id
            
    def _get_pit_resource(self, backupjobrun_vm_common_resources, pit_id):
        for backupjobrun_vm_resource in backupjobrun_vm_common_resources:
            if backupjobrun_vm_resource.resource_pit_id == pit_id:
                return backupjobrun_vm_resource   
            
    def _restore_networks(self, context, backupjobrun, new_net_resources):
        """
        Restore the networking configuration of VMs of the snapshot
        nic_mappings: Dictionary that holds the nic mappings. { nic_id : { network_id : network_uuid, etc. } }
        """
        try:
            network_service =  neutron.API()  

            backupjobrun_vm_common_resources = self.db.snapshot_vm_resources_get(context, backupjobrun.id, backupjobrun.id)           
            for backupjobrun_vm in self.db.snapshot_vm_get(context, backupjobrun.id):
                backupjobrun_vm_resources = self.db.snapshot_vm_resources_get(context, backupjobrun_vm.vm_id, backupjobrun.id)        
                for backupjobrun_vm_resource in backupjobrun_vm_resources:
                    if backupjobrun_vm_resource.resource_type == 'nic':                
                        vm_nic_backup = self.db.vm_network_resource_backup_get(context, backupjobrun_vm_resource.id)
                        #private network
                        pit_id = self._get_pit_resource_id(vm_nic_backup, 'network_id')
                        if pit_id in new_net_resources:
                            new_network = new_net_resources[pit_id]
                        else:
                            vm_nic_network = self._get_pit_resource(backupjobrun_vm_common_resources, pit_id)
                            vm_nic_network_backup = self.db.vm_network_resource_backup_get(context, vm_nic_network.id)
                            network = pickle.loads(str(vm_nic_network_backup.pickle))
                            params = {'name': network['name'],
                                      'tenant_id': context.tenant,
                                      'admin_state_up': network['admin_state_up'],
                                      'shared': network['shared'],
                                      'router:external': network['router:external']} 
                            new_network = network_service.create_network(context,**params)
                            new_net_resources.setdefault(pit_id,new_network)
                            
                        #private subnet
                        pit_id = self._get_pit_resource_id(vm_nic_backup, 'subnet_id')
                        if pit_id in new_net_resources:                        
                            new_subnet = new_net_resources[pit_id]
                        else:
                            vm_nic_subnet = self._get_pit_resource(backupjobrun_vm_common_resources, pit_id)
                            vm_nic_subnet_backup = self.db.vm_network_resource_backup_get(context, vm_nic_subnet.id)
                            subnet = pickle.loads(str(vm_nic_subnet_backup.pickle))
                            params = {'name': subnet['name'],
                                      'network_id': new_network['id'],
                                      'tenant_id': context.tenant,
                                      'cidr': subnet['cidr'],
                                      'ip_version': subnet['ip_version']} 
                            new_subnet = network_service.create_subnet(context,**params)
                            new_net_resources.setdefault(pit_id,new_subnet)
        
                        #external network
                        pit_id = self._get_pit_resource_id(vm_nic_backup, 'ext_network_id')
                        if pit_id in new_net_resources:
                            new_ext_network = new_net_resources[pit_id]
                        else:
                            vm_nic_ext_network = self._get_pit_resource(backupjobrun_vm_common_resources, pit_id)
                            vm_nic_ext_network_backup = self.db.vm_network_resource_backup_get(context, vm_nic_ext_network.id)
                            ext_network = pickle.loads(str(vm_nic_ext_network_backup.pickle))
                            params = {'name': ext_network['name'],
                                      'admin_state_up': ext_network['admin_state_up'],
                                      'shared': ext_network['shared'],
                                      'router:external': ext_network['router:external']} 
                            new_ext_network = network_service.create_network(context,**params)
                            new_net_resources.setdefault(pit_id,new_ext_network)
                            
                        #external subnet
                        pit_id = self._get_pit_resource_id(vm_nic_backup, 'ext_subnet_id')
                        if pit_id in new_net_resources:
                            new_ext_subnet = new_net_resources[pit_id]
                        else:
                            vm_nic_ext_subnet = self._get_pit_resource(backupjobrun_vm_common_resources, pit_id)
                            vm_nic_ext_subnet_backup = self.db.vm_network_resource_backup_get(context, vm_nic_ext_subnet.id)
                            ext_subnet = pickle.loads(str(vm_nic_ext_subnet_backup.pickle))
                            params = {'name': ext_subnet['name'],
                                      'network_id': new_ext_network['id'],
                                      'cidr': ext_subnet['cidr'],
                                      'ip_version': ext_subnet['ip_version']} 
                            new_ext_subnet = network_service.create_subnet(context,**params)
                            new_net_resources.setdefault(pit_id,new_ext_subnet)
                            
                        #router
                        pit_id = self._get_pit_resource_id(vm_nic_backup, 'router_id')
                        if pit_id in new_net_resources:
                            new_router = new_net_resources[pit_id]
                        else:
                            vm_nic_router = self._get_pit_resource(backupjobrun_vm_common_resources, pit_id)
                            vm_nic_router_backup = self.db.vm_network_resource_backup_get(context, vm_nic_router.id)
                            router = pickle.loads(str(vm_nic_router_backup.pickle))
                            params = {'name': router['name'],
                                      'tenant_id': context.tenant} 
                            new_router = network_service.create_router(context,**params)
                            new_net_resources.setdefault(pit_id,new_router)
                        
                        network_service.router_add_interface(context,new_router['id'], subnet_id=new_subnet['id'])
                        network_service.router_add_gateway(context,new_router['id'], new_ext_network['id'])
                        
            return
        except Exception as err:
            return;       
    def snapshot_hydrate(self, context, snapshot_id):
        """
        Restore VMs and all its LUNs from a workload
        """
        LOG.info(_('restore_snapshot started, restoring snapshot id: %(snapshot_id)s') % locals())
        snapshot = self.db.snapshot_get(context, snapshot_id)
        workload = self.db.workload_get(context, snapshot.backupjob_id)
        #self.db.snapshot_update(context, snapshot.id, {'status': 'restoring'})
        new_net_resources = {}
        self._restore_networks(context, snapshot, new_net_resources)           
        #TODO(gbasava): Pick the specified vault service from the snapshot
        vault_service = swift.SwiftBackupService(context)
        
        #restore each VM
        for vm in self.db.snapshot_vm_get(context, snapshot.id): 
            self.driver.hydrate_instance(workload, snapshot, vm, vault_service, new_net_resources, self.db, context)


    def snapshot_delete(self, context, snapshot_id):
        """
        Delete an existing snapshot
        """
        workload = self.db.workload_get(context, workload_id, workload_instance_id)
        #TODO(gbasava):Implement
 