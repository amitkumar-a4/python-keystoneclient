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


FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


class API(base.Base):
    """API for interacting with the workloadmgr."""

    def __init__(self, db_driver=None):
        self.workloads_rpcapi = workloads_rpcapi.WorkloadAPI()
        super(API, self).__init__(db_driver)

    def workload_get(self, context, workload_id):
        rv = self.db.workload_get(context, workload_id)
        return dict(rv.iteritems())

    def workload_show(self, context, workload_id):
        rv = self.db.workload_show(context, workload_id)
        return dict(rv.iteritems())
    
    def workload_get_all(self, context, search_opts={}):
        if context.is_admin:
            workloads = self.db.workload_get_all(context)
        else:
            workloads = self.db.workload_get_all_by_project(context,
                                                        context.project_id)

        return workloads
    
    def workload_create(self, context, name, description, instance_id,
               vault_service, hours=int(24), availability_zone=None):
        """
        Make the RPC call to create a workload.
        """
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'display_name': name,
                   'display_description': description,
                   'hours':hours,
                   'status': 'creating',
                   'vault_service': vault_service,
                   'host': socket.gethostname(), }

        workload = self.db.workload_create(context, options)

        #TODO(gbasava):  We will need to iterate thru the list of VMs when we support multiple VMs
        
        vminstance = {'workload_id': workload.id,
                      'vm_id': instance_id}
        vm = self.db.workload_vms_create(context, vminstance)
        
        self.workloads_rpcapi.workload_create(context,
                                         workload['host'],
                                         workload['id'])

        return workload
    
    def workload_delete(self, context, workload_id):
        """
        Make the RPC call to delete a workload.
        """
        workload = self.workload_get(context, workload_id)
        if workload['status'] not in ['available', 'error']:
            msg = _('Backup status must be available or error')
            raise exception.InvalidBackupJob(reason=msg)

        self.db.workload_update(context, workload_id, {'status': 'deleting'})
        self.workloads_rpcapi.workload_delete(context,
                                         workload['host'],
                                         workload['id'])

    def snapshot_get(self, context, snapshot_id):
        rv = self.db.snapshot_get(context, snapshot_id)
        return dict(rv.iteritems())

    def snapshot_show(self, context, snapshot_id):
        rv = self.db.snapshot_show(context, snapshot_id)
        return dict(rv.iteritems())
    
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
        Make the RPC call to delete a snapshot.
        """
        snapshot = self.snapshot_get(context, snapshot_id)
        if snapshot['status'] not in ['available', 'error']:
            msg = _('snapshot status must be available or error')
            raise exception.InvalidBackupJob(reason=msg)

        self.db.snapshot_update(context, snapshot_id, {'status': 'deleting'})
        self.workloads_rpcapi.snapshot_delete(context,
                                                   snapshot['id'])
    def snapshot_hydrate(self, context, snapshot_id):
        """
        Make the RPC call to restore a snapshot.
        """
        snapshot = self.snapshot_get(context, snapshot_id)
        workload = self.workload_get(context, snapshot['backupjob_id'])
        if snapshot['status'] != 'available':
            msg = _('snapshot status must be available')
            raise exception.InvalidBackupJob(reason=msg)
        
        #GIRI 'host' is temporarily hardcoded 
        workload['host'] = 'td-sea-srv02'
        self.workloads_rpcapi.snapshot_hydrate(context, workload['host'], snapshot['id'])
        #TODO(gbasava): Return the restored instances

