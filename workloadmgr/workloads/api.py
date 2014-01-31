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


FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)

class API(base.Base):
    """API for interacting with the Workload Manager."""

    def __init__(self, db_driver=None):
        self.workloads_rpcapi = workloads_rpcapi.WorkloadMgrAPI()
        super(API, self).__init__(db_driver)

    def workload_get(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        workload_vm_ids = []
        for workload_vm in self.db.workload_vms_get(context, workload.id):
           workload_vm_ids.append(workload_vm.vm_id)  
        workload_dict['vm_ids'] = workload_vm_ids
        return workload_dict

    def workload_show(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        workload_vm_ids = []
        for workload_vm in self.db.workload_vms_get(context, workload.id):
            workload_vm_ids.append(workload_vm.vm_id)  
        workload_dict['vm_ids'] = workload_vm_ids
        return workload_dict
    
    def workload_get_all(self, context, search_opts={}):
        if context.is_admin:
            workloads = self.db.workload_get_all(context)
        else:
            workloads = self.db.workload_get_all_by_project(context,
                                                        context.project_id)

        return workloads
    
    def workload_create(self, context, name, description, instances,
               vault_service, hours=int(24), availability_zone=None):
        """
        Make the RPC call to create a workload.
        """
        compute_service = nova.API(production=True)
        instances_with_name = compute_service.get_servers(context,all_tenants=True)
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
                   'vault_service': vault_service,
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
        for snapshot in snapshots:
            self.snapshot_delete(context, snapshot['id'])

        self.db.workload_delete(context, workload_id)

    def workload_snapshot(self, context, workload_id, full):
        """
        Make the RPC call to snapshot a workload.
        """
        workload = self.workload_get(context, workload_id)
        if workload['status'] in ['running']:
            msg = _('Workload snapshot job is already executing, ignoring this execution')
            raise exception.InvalidWorkloadMgr(reason=msg)
        if full == True:
            snapshot_type = 'full'
        else:
            snapshot_type = 'incremental'
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'workload_id': workload_id,
                   'snapshot_type': snapshot_type,
                   'status': 'creating',}
        snapshot = self.db.snapshot_create(context, options)
        self.workloads_rpcapi.workload_snapshot(context, workload['host'], snapshot['id'])
        return snapshot

    def snapshot_get(self, context, snapshot_id):
        rv = self.db.snapshot_get(context, snapshot_id)
        snapshot_details  = dict(rv.iteritems())
        vms = self.db.snapshot_vm_get(context, snapshot_id)
        instances = []
        for vm in vms:
            instances.append(dict(vm.iteritems()))
        snapshot_details.setdefault('instances', instances)    
        return snapshot_details

    def snapshot_show(self, context, snapshot_id):
        rv = self.db.snapshot_show(context, snapshot_id)
        snapshot_details  = dict(rv.iteritems())
        vms = self.db.snapshot_vm_get(context, snapshot_id)
        instances = []
        for vm in vms:
            instances.append(dict(vm.iteritems()))
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

        self.db.snapshot_delete(context, snapshot_id)
        
    def snapshot_restore(self, context, snapshot_id, test):
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
                   'status': 'restoring',}
        restore = self.db.restore_create(context, options)
        self.workloads_rpcapi.snapshot_restore(context, workload['host'], restore['id'])
        return restore
        #TODO(gbasava): Return the restored instances

