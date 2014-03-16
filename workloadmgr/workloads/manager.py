# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Job scheduler manages WorkloadMgr


**Related Flags**

:workloads_topic:  What :mod:`rpc` topic to listen to (default:`workloadmgr-workloads`).
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
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.vault import vault


LOG = logging.getLogger(__name__)

workloads_manager_opts = [
]

scheduler_config = {'standalone': 'True'}

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)

def workload_callback(workload_id):
    """
    Callback
    """
    #TODO(gbasava): Implementation

class WorkloadMgrManager(manager.SchedulerDependentManager):
    """Manages WorkloadMgr """

    RPC_API_VERSION = '1.0'

    def __init__(self, service_name=None, *args, **kwargs):
        self.az = FLAGS.storage_availability_zone
        self.scheduler = Scheduler(scheduler_config)
        self.scheduler.start()
        super(WorkloadMgrManager, self).__init__(service_name='workloadscheduler',*args, **kwargs)
        
    def init_host(self):
        """
        Do any initialization that needs to be run if this is a standalone service.
        """

        ctxt = context.get_admin_context()

        LOG.info(_("Cleaning up incomplete operations"))
        
    def _get_workflow_class(self, context, workload_type_id):
        #TODO(giri): implement a driver model for the workload types
        workload_type = self.db.workload_type_get(context, workload_type_id)
        workflow_class_name = ''
        if(workload_type.display_name == 'Default'):
            workflow_class_name = 'workloadmgr.workflows.defaultworkflow.DefaultWorkflow'
        elif(workload_type.display_name == 'Serial'):
            workflow_class_name = 'workloadmgr.workflows.serialworkflow.SerialWorkflow'
        elif(workload_type.display_name == 'Parallel'):
            workflow_class_name = 'workloadmgr.workflows.parallelworkflow.ParallelWorkflow'
        elif(workload_type.display_name == 'MongoDB'):
            workflow_class_name = 'workloadmgr.workflows.mongodbflow.MongoDBWorkflow'   
        elif(workload_type.display_name == 'Hadoop'):
            workflow_class_name = 'workloadmgr.workflows.mongodbflow.HadoopWorkflow' 
        elif(workload_type.display_name == 'Cassandra'):
            workflow_class_name = 'workloadmgr.workflows.mongodbflow.CassandraWorkflow'             
                          
        parts = workflow_class_name.split('.')
        module = ".".join(parts[:-1])
        workflow_class = __import__( module )
        for comp in parts[1:]:
            workflow_class = getattr(workflow_class, comp)            
        return workflow_class        
        
    def _append_unique(self, list, new_item):
        for item in list:
            if item['id'] == new_item['id']:
                return
        list.append(new_item)
        
       

    def _get_metadata_value(self, vm_network_resource_snap, key):
        for metadata in vm_network_resource_snap.metadata:
            if metadata['key'] == key:
                return metadata['value']
                
    def _get_pit_resource_id(self, vm_network_resource_snap, key):
        for metadata in vm_network_resource_snap.metadata:
            if metadata['key'] == key:
                pit_id = metadata['value']
                return pit_id
            
    def _get_pit_resource(self, snapshot_vm_common_resources, pit_id):
        for snapshot_vm_resource in snapshot_vm_common_resources:
            if snapshot_vm_resource.resource_pit_id == pit_id:
                return snapshot_vm_resource            
                    
    def _restore_networks(self, context, production, snapshot, restore, new_net_resources):
        """
        Restore the networking configuration of VMs of the snapshot
        nic_mappings: Dictionary that holds the nic mappings. { nic_id : { network_id : network_uuid, etc. } }
        """
        network_service =  neutron.API(production=production)  
        snapshot_vm_common_resources = self.db.snapshot_vm_resources_get(context, snapshot.id, snapshot.id)           
        for snapshot_vm in self.db.snapshot_vms_get(context, snapshot.id):
            snapshot_vm_resources = self.db.snapshot_vm_resources_get(context, snapshot_vm.vm_id, snapshot.id)        
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type == 'nic':                
                    vm_nic_snapshot = self.db.vm_network_resource_snap_get(context, snapshot_vm_resource.id)
                    #private network
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'network_id')
                    if pit_id in new_net_resources:
                        new_network = new_net_resources[pit_id]
                    else:
                        vm_nic_network = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_network_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_network.id)
                        network = pickle.loads(str(vm_nic_network_snapshot.pickle))
                        params = {'name': network['name'] + '_' + restore.id,
                                  'tenant_id': context.tenant,
                                  'admin_state_up': network['admin_state_up'],
                                  'shared': network['shared'],
                                  'router:external': network['router:external']} 
                        new_network = network_service.create_network(context,**params)
                        new_net_resources.setdefault(pit_id,new_network)
                        restored_vm_resource_values = {'id': new_network['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'network',
                                                       'resource_name':  new_network['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                                        
                        
                    #private subnet
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'subnet_id')
                    if pit_id in new_net_resources:
                        new_subnet = new_net_resources[pit_id]
                    else:
                        vm_nic_subnet = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_subnet_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_subnet.id)
                        subnet = pickle.loads(str(vm_nic_subnet_snapshot.pickle))
                        params = {'name': subnet['name'] + '_' + restore.id,
                                  'network_id': new_network['id'],
                                  'tenant_id': context.tenant,
                                  'cidr': subnet['cidr'],
                                  'ip_version': subnet['ip_version']} 
                        new_subnet = network_service.create_subnet(context,**params)
                        new_net_resources.setdefault(pit_id,new_subnet)
                        restored_vm_resource_values = {'id': new_subnet['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'subnet',
                                                       'resource_name':  new_subnet['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                              
    
                    #external network
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'ext_network_id')
                    if pit_id in new_net_resources:
                        new_ext_network = new_net_resources[pit_id]
                    else:
                        vm_nic_ext_network = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_ext_network_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_ext_network.id)
                        ext_network = pickle.loads(str(vm_nic_ext_network_snapshot.pickle))
                        params = {'name': ext_network['name'] + '_' + restore.id,
                                  'admin_state_up': ext_network['admin_state_up'],
                                  'shared': ext_network['shared'],
                                  'router:external': ext_network['router:external']} 
                        new_ext_network = network_service.create_network(context,**params)
                        new_net_resources.setdefault(pit_id,new_ext_network)
                        restored_vm_resource_values = {'id': new_ext_network['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'network',
                                                       'resource_name':  new_ext_network['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                             
                        
                    #external subnet
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'ext_subnet_id')
                    if pit_id in new_net_resources:
                        new_ext_subnet = new_net_resources[pit_id]
                    else:
                        vm_nic_ext_subnet = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_ext_subnet_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_ext_subnet.id)
                        ext_subnet = pickle.loads(str(vm_nic_ext_subnet_snapshot.pickle))
                        params = {'name': ext_subnet['name'] + '_' + restore.id,
                                  'network_id': new_ext_network['id'],
                                  'cidr': ext_subnet['cidr'],
                                  'ip_version': ext_subnet['ip_version']} 
                        new_ext_subnet = network_service.create_subnet(context,**params)
                        new_net_resources.setdefault(pit_id,new_ext_subnet)
                        restored_vm_resource_values = {'id': new_ext_subnet['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'subnet',
                                                       'resource_name':  new_ext_subnet['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                              
                        
                    #router
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'router_id')
                    if pit_id in new_net_resources:
                        new_router = new_net_resources[pit_id]
                    else:
                        vm_nic_router = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_router_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_router.id)
                        router = pickle.loads(str(vm_nic_router_snapshot.pickle))
                        params = {'name': router['name'] + '_' + restore.id,
                                  'tenant_id': context.tenant} 
                        new_router = network_service.create_router(context,**params)
                        new_net_resources.setdefault(pit_id,new_router)
                        restored_vm_resource_values = {'id': new_router['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'router',
                                                       'resource_name':  new_router['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                                   
                    
                    try:
                        network_service.router_add_interface(context,new_router['id'], subnet_id=new_subnet['id'])
                        network_service.router_add_gateway(context,new_router['id'], new_ext_network['id'])
                    except Exception as err:
                        pass
        
    def workload_type_discover_instances(self, context, workload_type_id, metadata):
        """
        Discover instances of a workload_type
        """        
        context_dict = dict([('%s' % key, value)
                          for (key, value) in context.to_dict().iteritems()])            
        context_dict['conf'] =  None # RpcContext object looks for this during init
        store = {
            'context': context_dict,                # context dictionary
        }

        for key in metadata:
            store[key] = metadata[key]
        
        workflow_class = self._get_workflow_class(context, workload_type_id)
        workflow = workflow_class("discover_instances", store)
        instances = workflow.discover()
        return instances   

    def workload_get_topology(self, context, workload_id):
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
        workflow = workflow_class("workload_topology", store)
        topology = workflow.topology()
        return topology
    
    def workload_get_workflow_details(self, context, workload_id):
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
        details = workflow.details()
        return details
        
    def workload_create(self, context, workload_id):
        """
        Create a scheduled workload in the workload scheduler
        """
        try:
            workload = self.db.workload_get(context, workload_id)
            vm = self.db.workload_vms_get(context, workload_id)

            LOG.info(_('create_workload started, %s:' %workload_id))
            self.db.workload_update(context, 
                                    workload_id, 
                                    {'host': self.host})

            schjob = self.scheduler.add_interval_job(context, workload_callback, hours=24,
                                     name=workload['display_name'], args=[workload_id], 
                                     workload_id=workload_id)
            LOG.info(_('scheduled workload: %s'), schjob.id)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.workload_update(context, workload_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})

        self.db.workload_update(context, 
                                workload_id, 
                                {'status': 'available',
                                 'availability_zone': self.az,
                                 'schedule_job_id':schjob.id})
        
        LOG.info(_('create_workload finished. workload: %s'), workload_id)

    def workload_snapshot(self, context, snapshot_id):
        """
        Take a snapshot of the workload
        """
        LOG.info(_('snapshot of workload started, snapshot_id %s' %snapshot_id))
        
        try:
            snapshot = self.db.snapshot_get(context, snapshot_id)
            snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, snapshot.workload_id)
            full_snapshot_exists = False
            for snapshot in snapshots:
                if snapshot.snapshot_type == 'full' and snapshot.status == 'available':
                    full_snapshot_exists = True
                    break
    
            snapshot = self.db.snapshot_get(context, snapshot_id)
            if snapshot.snapshot_type != 'full' and full_snapshot_exists == True:
                snapshot.snapshot_type = 'incremental'
            else:
                snapshot.snapshot_type = 'full'

            self.db.snapshot_update(context, snapshot.id, {'snapshot_type': snapshot.snapshot_type})
           
            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'connection': FLAGS.sql_connection,     # taskflow persistence connection
                'context': context_dict,                # context dictionary
                'snapshot': dict(snapshot.iteritems()), # snapshot dictionary
                'workload_id': snapshot.workload_id,    # workload_id                
            }
            workload = self.db.workload_get(context, snapshot.workload_id)
            for kvpair in workload.metadata:
                store[kvpair['key']] = kvpair['value']
                
            workflow_class = self._get_workflow_class(context, workload.workload_type_id)
            workflow = workflow_class(workload.display_name, store)
            workflow.initflow()
            self.db.snapshot_update(context, snapshot.id, {'status': 'executing'})
            workflow.execute()
            self.db.snapshot_update(context, snapshot.id, {'status': 'available'})
            return 
         
        except Exception as ex:
            msg = _("Error Creating Workload Snapshot %(snapshot_id)s with failure: %(exception)s")
            LOG.debug(msg, {'snapshot_id': snapshot_id, 'exception': ex})
            LOG.exception(ex)
            self.db.snapshot_update(context, snapshot.id, {'status': 'error'}) 
            return;          
            

    def workload_delete(self, context, workload_id):
        """
        Delete an existing workload
        """
        LOG.info(_('deleting workload: %s'), workload_id)
        snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id)
        for snapshot in snapshots:
            self.snapshot_delete(context, snapshot['id'])
        self.db.workload_delete(context, workload_id)


    def snapshot_restore(self, context, restore_id):
        """
        Restore VMs and all its LUNs from a snapshot
        """
        LOG.info(_('restore_snapshot started, restore id: %(restore_id)s') % locals())
        try:
            restore = self.db.restore_get(context, restore_id)
            snapshot = self.db.snapshot_get(context, restore.snapshot_id)
            workload = self.db.workload_get(context, snapshot.workload_id)
            
            new_net_resources = {}
            if restore.restore_type == 'test':
                self._restore_networks(context, False, snapshot, restore, new_net_resources)
            else:
                self._restore_networks(context, True, snapshot, restore, new_net_resources)    
            vault_service = vault.get_vault_service(context)
            
            #restore each VM 
            #TODO(giri): If one VM restore fails, rollback the whole transaction
            for vm in self.db.snapshot_vms_get(context, snapshot.id): 
                virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
                restored_instance = virtdriver.snapshot_restore(workload, snapshot, restore, vm, vault_service, new_net_resources, self.db, context)
                restored_vm_values = {'vm_id': restored_instance.id,
                                      'vm_name':  restored_instance.name,    
                                      'restore_id': restore.id,
                                      'status': 'available'}
                restored_vm = self.db.restored_vm_create(context,restored_vm_values)    
                           
            self.db.restore_update(context, restore.id, {'status': 'completed'})
        except Exception as ex:
            msg = _("Error Restoring %(restore_id)s with failure: %(exception)s")
            LOG.debug(msg, {'restore_id': restore_id, 'exception': ex})
            LOG.exception(ex)
            self.db.restore_update(context, restore.id, {'status': 'error'}) 
            return;  

    def snapshot_delete(self, context, snapshot_id):
        """
        Delete an existing snapshot
        """
        LOG.info(_('deleting snapshot %s'), snapshot_id)        
        self.db.snapshot_delete(context, snapshot_id)
        
    def restore_delete(self, context, restore_id):
        """
        Delete an existing restore 
        """
        LOG.info(_('deleting restore %s'), restore_id)
        self.db.restore_delete(context, restore_id)        
 