# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2014 Trilio Data, Inc. All Rights Reserved.
#

import os
import time
import cPickle as pickle

from oslo.config import cfg

from taskflow import task

from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.compute import nova
from workloadmgr.vault import vault
from workloadmgr.openstack.common import log as logging

from workloadmgr.workloads import workload_utils
from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

vmtasks_opts = []

CONF = cfg.CONF
CONF.register_opts(vmtasks_opts)

def wait_for_nova_process( openstack_snapshot_id, params, result):
    try:
        tracker_metadata = {'snapshot_id': params['snapshot_id']}
        backup_target = vault.get_backup_target(params['backend_endpoint'])
        progress_tracking_directory = backup_target.get_progress_tracker_directory(tracker_metadata)
        hosts = result['hosts']
        snapshot_status = {}
        start_time = time.time()
        base_stat_map = {}

        # We need to look at progress of multiple hosts. For that we are
        # continuously watch at progress tracking file for each node
        # If there is no progress file from any node after 10 minutes then will assume that node is down.
        # If there is keyword like Down/Error , in that case considering the staus in error.
        while hosts:
            for host in hosts:
                async_task_status = {}
                file_path = os.path.join(progress_tracking_directory, host)

                if os.path.exists(file_path):

                    if not base_stat_map.has_key(host):
                        base_stat_map[host] = {'base_stat': os.stat(file_path), 'base_time': time.time()}

                    else:
                        progstat = os.stat(file_path)

                        # if we don't see any update to file time for 10 minutes, something is wrong
                        # deal with it.
                        # TODO: @Murali How much should we wait. Copying images can take hours.
                        if progstat.st_mtime > base_stat_map[host]['base_stat'].st_mtime:
                            base_stat_map[host]['base_stat'] = progstat
                            base_stat_map[host]['base_time'] = time.time()
                        elif time.time() - base_stat_map[host]['base_time'] > 600:
                            snapshot_status[host] = ("No update to %s modified time for last 10 minutes. "
                                                     "Contego may have errored. Aborting Operation")
                            hosts.remove(host)
                            continue

                    with open(file_path, 'r') as progress_tracking_file:
                        async_task_status['status'] = progress_tracking_file.readlines()
                        if async_task_status and 'status' in async_task_status and len(async_task_status['status']):
                            for line in async_task_status['status']:
                                if 'Down' in line:
                                    snapshot_status[host] = "Contego service Unreachable - " + line
                                    hosts.remove(host)
                                if 'Error' in line:
                                    snapshot_status[host] = "Data transfer failed - " + line
                                    hosts.remove(host)
                                if 'Completed' in line:
                                    snapshot_status[host] = "Completed"
                                    hosts.remove(host)
                else:
                    # If no progress file for any node in next ten minutes then marking status down for that node.
                    diff = time.time() - start_time
                    if diff >= 600:
                        hosts.remove(host)
                        snapshot_status[host] = "Contego service Unreachable."
        return snapshot_status

    except Exception as ex:
        LOG.exception(ex)


class CopyConfigFiles(task.Task):

    def execute(self, context, openstack_snapshot_id, params):
        return self.execute_with_log(context, openstack_snapshot_id, params)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'CopyConfigFiles.execute')
    def execute_with_log(self, context, openstack_snapshot_id, params):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        result = compute_service.vast_config_snapshot(cntx, openstack_snapshot_id, params)
        upload_status = wait_for_nova_process(openstack_snapshot_id, params, result)
        db.openstack_config_snapshot_update(cntx,{
                                    'upload_summary' : pickle.dumps(upload_status),
                                    }, openstack_snapshot_id)

    @autolog.log_method(Logger, 'CopyConfigFiles.revert')
    def revert_with_log(self, *args, **kwargs):
        pass

class ApplyRetentionPolicy(task.Task):

    def execute(self, context, openstack_workload_id):
        return self.execute_with_log(context, openstack_workload_id)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'ApplyRetentionPolicy.execute')
    def execute_with_log(self, context, openstack_workload_id):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        openstack_workload = db.openstack_workload_get(cntx, openstack_workload_id)
        jobschedule = pickle.loads(str(openstack_workload['jobschedule']))

        snapshots_to_keep = int(jobschedule['retention_policy_value'])

        snapshots = db.openstack_config_snapshot_get_all(cntx)

        if len(snapshots) > snapshots_to_keep:
            for snapshot in snapshots[snapshots_to_keep:]:
                workload_utils.openstack_config_snapshot_delete(cntx, snapshot.id)

    @autolog.log_method(Logger, 'ApplyRetentionPolicy.revert')
    def revert_with_log(self, *args, **kwargs):
        pass



