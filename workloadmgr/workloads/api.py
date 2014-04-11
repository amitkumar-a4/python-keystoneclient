# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to the  workloadmgr service.
"""
import socket

from eventlet import greenthread

from workloadmgr.workloads import rpcapi as workloads_rpcapi
from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.image import glance


FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)

class API(base.Base):
    """API for interacting with the Workload Manager."""

    def __init__(self, db_driver=None):
        self.workloads_rpcapi = workloads_rpcapi.WorkloadMgrAPI()
        super(API, self).__init__(db_driver)
        
    def workload_type_get(self, context, workload_type_id):
        workload_type = self.db.workload_type_get(context, workload_type_id)
        workload_type_dict = dict(workload_type.iteritems())
        metadata = {}
        for kvpair in workload_type.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_type_dict['metadata'] = metadata        
        return workload_type_dict

    def workload_type_show(self, context, workload_type_id):
        workload_type = self.db.workload_type_get(context, workload_type_id)
        workload_type_dict = dict(workload_type.iteritems())
        metadata = {}
        for kvpair in workload_type.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_type_dict['metadata'] = metadata
        return workload_type_dict
    
    def workload_type_get_all(self, context, search_opts={}):
        workload_types = self.db.workload_types_get(context)
        return workload_types
    
    def workload_type_create(self, context, name, description, metadata):
        """
        Create a workload_type. No RPC call is made
        """
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'display_name': name,
                   'display_description': description,
                   'status': 'available',
                   'metadata': metadata,}

        workload_type = self.db.workload_type_create(context, options)
        return workload_type
    
    def workload_type_delete(self, context, workload_type_id):
        """
        Delete a workload_type. No RPC call is made
        """
        workload_type = self.workload_type_get(context, workload_type_id)
        if workload_type['status'] not in ['available', 'error']:
            msg = _('WorkloadType status must be available or error')
            raise exception.InvalidWorkloadMgr(reason=msg)

        #TODO(giri): check if this workload_type is referenced by other workloads
                    
        self.db.workload_type_delete(context, workload_type_id)
        
    def workload_type_discover_instances(self, context, workload_type_id, metadata):
        """
        Discover Instances of a workload_type. RPC call is made
        """
        return self.workloads_rpcapi.workload_type_discover_instances(context,
                                                                      socket.gethostname(),
                                                                      workload_type_id,
                                                                      metadata) 

    def workload_get(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        
        workload_vm_ids = []
        for workload_vm in self.db.workload_vms_get(context, workload.id):
            workload_vm_ids.append(workload_vm.vm_id)  
        workload_dict['vm_ids'] = workload_vm_ids
        
        metadata = {}
        for kvpair in workload.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_dict['metadata'] = metadata        
                
        return workload_dict

    def workload_show(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        
        workload_vm_ids = []
        for workload_vm in self.db.workload_vms_get(context, workload.id):
            workload_vm_ids.append(workload_vm.vm_id)  
        workload_dict['vm_ids'] = workload_vm_ids
        
        metadata = {}
        for kvpair in workload.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_dict['metadata'] = metadata 
                
        return workload_dict
    
    def workload_get_all(self, context, search_opts={}):
        if context.is_admin:
            workloads = self.db.workload_get_all(context)
        else:
            workloads = self.db.workload_get_all_by_project(context,
                                                        context.project_id)

        return workloads
    
    def workload_create(self, context, name, description, instances,
                        workload_type_id, metadata,
                        hours=int(24), availability_zone=None):
        """
        Make the RPC call to create a workload.
        """
        compute_service = nova.API(production=True)
        instances_with_name = compute_service.get_servers(context,admin=True)
        #TODO(giri): optimize this lookup
        for instance in instances:
            for instance_with_name in instances_with_name:
                if instance['instance-id'] == instance_with_name.id:
                    instance['instance-name'] = instance_with_name.name 
                   
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'display_name': name,
                   'display_description': description,
                   'hours':hours,
                   'status': 'creating',
                   'workload_type_id': workload_type_id,
                   'metadata' : metadata,
                   'host': socket.gethostname(), }

        workload = self.db.workload_create(context, options)
        for instance in instances:
            values = {'workload_id': workload.id,
                      'vm_id': instance['instance-id'],
                      'vm_name': instance['instance-name']}
            vm = self.db.workload_vms_create(context, values)
        
        self.workloads_rpcapi.workload_create(context,
                                              workload['host'],
                                              workload['id'])
        
        return workload
    
    def workload_delete(self, context, workload_id):
        """
        Delete a workload. No RPC call is made
        """
        workload = self.workload_get(context, workload_id)
        if workload['status'] not in ['available', 'error']:
            msg = _('Workload status must be available or error')
            raise exception.InvalidWorkloadMgr(reason=msg)

        snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id)
        if len(snapshots) > 0:
            msg = _('This workload contains snapshots')
            raise exception.InvalidWorkloadMgr(reason=msg)
                    
        self.db.workload_delete(context, workload_id)
        
    def workload_get_workflow(self, context, workload_id):
        """
        Get the workflow of the workload. RPC call is made
        """
        return self.workloads_rpcapi.workload_get_workflow_details(context,
                                                                   socket.gethostname(),
                                                                   workload_id)    
    def workload_get_topology(self, context, workload_id):
        """
        Get the topology of the workload. RPC call is made
        """
        return self.workloads_rpcapi.workload_get_topology(context,
                                                           socket.gethostname(),
                                                           workload_id)                
             

    def workload_snapshot(self, context, workload_id, snapshot_type, name, description):
        """
        Make the RPC call to snapshot a workload.
        """
        workload = self.workload_get(context, workload_id)
        if workload['status'] in ['running']:
            msg = _('Workload snapshot job is already executing, ignoring this execution')
            raise exception.InvalidWorkloadMgr(reason=msg)

        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'workload_id': workload_id,
                   'snapshot_type': snapshot_type,
                   'display_name': name,
                   'display_description': description,                   
                   'status': 'creating',}
        snapshot = self.db.snapshot_create(context, options)
        self.workloads_rpcapi.workload_snapshot(context, workload['host'], snapshot['id'])
        return snapshot

    def snapshot_get(self, context, snapshot_id):
        rv = self.db.snapshot_get(context, snapshot_id)
        snapshot_details  = dict(rv.iteritems())
        instances = []
        try:
            vms = self.db.snapshot_vms_get(context, snapshot_id)
            for vm in vms:
                instances.append(dict(vm.iteritems()))
        except Exception as ex:
            pass
        snapshot_details.setdefault('instances', instances)    
        return snapshot_details

    def snapshot_show(self, context, snapshot_id):
        rv = self.db.snapshot_show(context, snapshot_id)
        snapshot_details  = dict(rv.iteritems())
        instances = []
        try:
            vms = self.db.snapshot_vms_get(context, snapshot_id)
            for vm in vms:
                instances.append(dict(vm.iteritems()))
        except Exception as ex:
            pass
        snapshot_details.setdefault('instances', instances)    
        return snapshot_details
    
    def snapshot_get_all(self, context, workload_id=None):
        if workload_id:
            snapshots = self.db.snapshot_get_all_by_project_workload(
                                                    context,
                                                    context.project_id,
                                                    workload_id)
        elif context.is_admin:
            snapshots = self.db.snapshot_get_all(context)
        else:
            snapshots = self.db.snapshot_get_all_by_project(
                                        context,context.project_id)
        return snapshots
    
    def snapshot_delete(self, context, snapshot_id):
        """
        Delete a workload snapshot. No RPC call required
        """
        snapshot = self.snapshot_get(context, snapshot_id)
        if snapshot['status'] not in ['available', 'error']:
            msg = _('Snapshot status must be available or error')
            raise exception.InvalidWorkloadMgr(reason=msg)
        
        restores = self.db.restore_get_all_by_project_snapshot(context, context.project_id, snapshot_id)
        for restore in restores:
            if restore.restore_type == 'test':
                msg = _('This workload snapshot contains testbubbles')
                raise exception.InvalidWorkloadMgr(reason=msg)      

        self.db.snapshot_delete(context, snapshot_id)
        
    def snapshot_restore(self, context, snapshot_id, test, name, description):
        """
        Make the RPC call to restore a snapshot.
        """
        snapshot = self.snapshot_get(context, snapshot_id)
        workload = self.workload_get(context, snapshot['workload_id'])
        if snapshot['status'] != 'available':
            msg = _('Snapshot status must be available')
            raise exception.InvalidWorkloadMgr(reason=msg)
        
        restore_type = "restore"
        if test:
            restore_type = "test"
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'snapshot_id': snapshot_id,
                   'restore_type': restore_type,
                   'display_name': name,
                   'display_description': description,
                   'status': 'restoring',}
        restore = self.db.restore_create(context, options)
        self.workloads_rpcapi.snapshot_restore(context, workload['host'], restore['id'])
        return restore

    def restore_get(self, context, restore_id):
        rv = self.db.restore_get(context, restore_id)
        restore_details  = dict(rv.iteritems())
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id)
        restore_details.setdefault('workload_id', snapshot.workload_id)
                
        instances = []
        try:
            vms = self.db.restore_vm_get(context, restore_id)
            for vm in vms:
                instances.append(dict(vm.iteritems()))
        except Exception as ex:
            pass
        restore_details.setdefault('instances', instances)    
        return restore_details

    def restore_show(self, context, restore_id):
        rv = self.db.restore_show(context, restore_id)
        restore_details  = dict(rv.iteritems())
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id)
        restore_details.setdefault('workload_id', snapshot.workload_id)
        
        instances = []
        try:
            vms = self.db.restored_vm_get(context, restore_id)
            for vm in vms:
                instances.append({'id':vm.vm_id, 'name':vm.vm_name})
        except Exception as ex:
            pass
        restore_details.setdefault('instances', instances) 
        
        networks_list = []
        subnets_list = []
        routers_list = []
        flavors_list = []
        try:
            resources = self.db.restored_vm_resources_get(context, restore_id, restore_id)
            for resource in resources:
                if resource.resource_type == 'network':
                    networks_list.append({'id':resource.id, 'name':resource.resource_name})
                elif resource.resource_type == 'subnet':
                    subnets_list.append({'id':resource.id, 'name':resource.resource_name})
                elif resource.resource_type == 'router':
                    routers_list.append({'id':resource.id, 'name':resource.resource_name})   
                elif resource.resource_type == 'flavor':
                    flavors_list.append({'id':resource.id, 'name':resource.resource_name}) 
        except Exception as ex:
            pass        
        restore_details.setdefault('networks', networks_list) 
        restore_details.setdefault('subnets', subnets_list)
        restore_details.setdefault('routers', routers_list) 
        restore_details.setdefault('flavors', flavors_list) 
                
        return restore_details
    
    def restore_get_all(self, context, snapshot_id=None):
        if snapshot_id:
            restores = self.db.restore_get_all_by_project_snapshot(
                                                    context,
                                                    context.project_id,
                                                    snapshot_id)
        elif context.is_admin:
            restores = self.db.restore_get_all(context)
        else:
            restores = self.db.restore_get_all_by_project(
                                        context,context.project_id)
        return restores
    
    def restore_delete(self, context, restore_id):
        """
        Delete a workload restore. RPC call may be required
        """
        restore_details = self.restore_show(context, restore_id)
        if restore_details['status'] not in ['available', 'error']:
            msg = _('Restore or Testbubble status must be completed or error')
            raise exception.InvalidWorkloadMgr(reason=msg)

        if restore_details['restore_type'] == 'test':
            network_service =  neutron.API(production=False)
            compute_service = nova.API(production=False)
        else:
            network_service =  neutron.API(production=True)
            compute_service = nova.API(production=True)
            
        image_service = glance.get_default_image_service(production= (restore_details['restore_type'] != 'test'))                    
            
        for instance in restore_details['instances']:
            try:
                vm = compute_service.get_server_by_id(context, instance['id'])
                compute_service.delete(context, instance['id']) 
                image_service.delete(context, vm.image['id'])
                #TODO(giri): delete the cinder volumes
            except Exception as exception:
                msg = _("Error deleting instance %(instance_id)s with failure: %(exception)s")
                LOG.debug(msg, {'instance_id': instance['id'], 'exception': exception})
                LOG.exception(exception)
        for router in restore_details['routers']:
            try:
                network_service.delete_router(context,router['id'])
            except Exception as exception:
                msg = _("Error deleting router %(router_id)s with failure: %(exception)s")
                LOG.debug(msg, {'router_id': router['id'], 'exception': exception})
                LOG.exception(exception)                
        for subnet in restore_details['subnets']:
            try:
                network_service.delete_subnet(context,subnet['id'])
            except Exception as exception:
                msg = _("Error deleting subnet %(subnet_id)s with failure: %(exception)s")
                LOG.debug(msg, {'subnet_id': subnet['id'], 'exception': exception})
                LOG.exception(exception)                   
        for network in restore_details['networks']:
            try:
                network_service.delete_network(context,network['id'])
            except Exception as exception:
                msg = _("Error deleting network %(network_id)s with failure: %(exception)s")
                LOG.debug(msg, {'network_id': network['id'], 'exception': exception})
                LOG.exception(exception) 
                
        for flavor in restore_details['flavors']:
            try:
                compute_service.delete_flavor(context,flavor['id'])
            except Exception as exception:
                msg = _("Error deleting flavor %(flavor_id)s with failure: %(exception)s")
                LOG.debug(msg, {'flavor_id': flavor['id'], 'exception': exception})
                LOG.exception(exception)                                     

        self.db.restore_delete(context, restore_id)
        
