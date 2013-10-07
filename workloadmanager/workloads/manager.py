# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
manages workloads


**Related Flags**

:workloads_topic:  What :mod:`rpc` topic to listen to (default:
                        `workloadmanager-workloads`).
:workloads_manager:  The module name of a class derived from
                          :class:`manager.Manager` (default:
                          :class:`workloadmanager.workload.manager.Manager`).

"""

from sqlalchemy import *
from datetime import datetime, timedelta
import time
import uuid

from oslo.config import cfg
from workloadmanager import context
from workloadmanager import exception
from workloadmanager import flags
from workloadmanager import manager
from workloadmanager.virt import driver
from workloadmanager.openstack.common import excutils
from workloadmanager.openstack.common import importutils
from workloadmanager.openstack.common import log as logging
from workloadmanager.apscheduler.scheduler import Scheduler
from workloadmanager.vault import swift


LOG = logging.getLogger(__name__)

workloads_manager_opts = [
    cfg.StrOpt('vault_service',
               default='workloadmanager.vault.swift',
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


class WorkloadManager(manager.SchedulerDependentManager):
    """Manages workloads """

    RPC_API_VERSION = '1.0'

    def __init__(self, service_name=None, *args, **kwargs):

        self.service = importutils.import_module(FLAGS.vault_service)
        self.az = FLAGS.storage_availability_zone
        self.scheduler = Scheduler(scheduler_config)
        self.scheduler.start()

        super(WorkloadManager, self).__init__(service_name='workloadscheduler',
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

    def snapshot_hydrate(self, context, snapshot_id):
        """
        Restore VMs and all its LUNs from a workload
        """
        LOG.info(_('restore_snapshot started, restoring snapshot id: %(snapshot_id)s') % locals())
        snapshot = self.db.snapshot_get(context, snapshot_id)
        workload = self.db.workload_get(context, snapshot.backupjob_id)
        #self.db.snapshot_update(context, snapshot.id, {'status': 'restoring'})
        #TODO(gbasava): Pick the specified vault service from the snapshot
        vault_service = swift.SwiftBackupService(context)
        
        #restore each VM
        for vm in self.db.snapshot_vm_get(context, snapshot.id): 
            self.driver.hydrate_instance(workload, snapshot, vm, vault_service, self.db, context)


    def snapshot_delete(self, context, snapshot_id):
        """
        Delete an existing snapshot
        """
        workload = self.db.workload_get(context, workload_id, workload_instance_id)
        #TODO(gbasava):Implement
 