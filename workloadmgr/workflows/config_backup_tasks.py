# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2014 Trilio Data, Inc. All Rights Reserved.
#

import time
import copy
import cPickle as pickle

from itertools import cycle
from oslo.config import cfg
from taskflow import task

from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.compute import nova
from workloadmgr.virt import driver
from workloadmgr.openstack.common import log as logging

from workloadmgr.workloads import workload_utils
from workloadmgr import autolog

from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

CONF = cfg.CONF


class CopyConfigFiles(task.Task):
    def execute(self, context, backup_id, host, target, params):
        return self.execute_with_log(context, backup_id, host, target, params)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'CopyConfigFiles.execute')
    def execute_with_log(self, context, backup_id, host, target, params):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        config_workload = db.config_workload_get(cntx)
        backend_endpoint = config_workload.backup_media_target
        params['host'] = host
        params['target'] = target

        target_host = host
        target_host_data = 'config_data'
        if target == 'controller':
            remote_node = params['remote_host_creds']['hostname']
            target_host_data = 'config_data for remote node: %s' % (remote_node)
        elif target == 'database':
            target_host_data = 'database'

        metadata = {
            'resource_id': host + '_' + str(int(time.time())),
            'backend_endpoint': backend_endpoint,
            'snapshot_id': backup_id
        }
        params['metadata'] = metadata

        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        LOG.info("vast_config_backup called for backup_id: %s" %backup_id)
        virtdriver._vast_methods_call_by_function(compute_service.vast_config_backup,
                                                  cntx, backup_id,
                                                  params)
        try:
            upload_status = virtdriver._wait_for_remote_nova_process(cntx, compute_service,
                                                                     metadata,
                                                                     backup_id,
                                                                     backend_endpoint)
            if upload_status is True:
                upload_status = 'Completed'
        except Exception as ex:
            upload_status = _("%(exception)s") % {'exception': ex}
            LOG.exception(ex)

        config_backup = db.config_backup_get(cntx, backup_id)
        config_metadata = config_backup.metadata
        backup_summary = None
        for metadata in config_metadata:
            if metadata['key'] == "backup_summary":
                backup_summary = metadata['value']
                break
        '''
        backupsummary sample:
        backup_summary = {'Host1':
                              {
                                  'config_files': 'status',
                                  'database': 'status'
                              }
                          }
        '''
        if backup_summary:
            backup_summary = pickle.loads(str(backup_summary))
        else:
            backup_summary = {}

        if backup_summary.get(target_host, None):
            backup_summary[target_host][target_host_data] = upload_status
        else:
            backup_summary[target_host] = {target_host_data: upload_status}

        backup_summary = pickle.dumps(backup_summary)
        metadata = {'backup_summary': backup_summary}

        if upload_status == 'Completed':
            metadata['status'] = 'available'
        else:
            metadata['warning_msg'] = "All backup jobs are not completed successfully. Please see backup summary."

        values = {'metadata': metadata}
        db.config_backup_update(cntx, backup_id, values)

    @autolog.log_method(Logger, 'CopyConfigFiles.revert')
    def revert_with_log(self, *args, **kwargs):
        pass


def UnorderedCopyConfigFiles(backup_id, hosts, target, params):
    flow = uf.Flow("copyconfigfilesuf")
    for host in hosts:
        flow.add(CopyConfigFiles(name="CopyConfigFile_" + host,
                                 rebind={'backup_id': 'backup_id',
                                         'host': host,
                                         'target': target,
                                         'params': 'params'
                                         }))
    return flow


def UnorderedCopyConfigFilesFromRemoteHost(backup_id, controller_nodes, target, params):
    """
    If list of controller nodes is more than trusted compute nodes 
    then pairing each controller node to compute nodes in  cycle
    For ex:
    cont nodes = node1, node2, node3, node4
    comp_nodes = comp1, comp2
    In this case pairing would be 
    (node1, comp1) (node2, comp2)(node3, comp1)(node4, comp2)

    if we have controller nodes less than or equal to trusted
    computed nodes then there would be one to one pairing
    """
    flow = uf.Flow("copyconfigfilesremotehostuf")
    trusted_nodes = params['trusted_nodes']
    target = 'controller'

    nodes = zip(controller_nodes, cycle(trusted_nodes.keys())) \
        if len(controller_nodes) > len(trusted_nodes.keys()) \
        else zip(controller_nodes, trusted_nodes)

    for controller_host, trusted_node in nodes:
        compute_host = trusted_nodes[trusted_node]['hostname']
        params['remote_host_creds'] = copy.deepcopy(trusted_nodes[trusted_node])
        params['remote_host_creds']['hostname'] = controller_host
        LOG.info("Backing controller node: %s from compute node: %s" %(controller_host,compute_host))
        flow.add(CopyConfigFiles(name="CopyConfigFileRemoteHost_" + controller_host,
                                 rebind={'backup_id': 'backup_id',
                                         'host': compute_host,
                                         'target': target,
                                         'params': 'params'
                                         }))
    return flow


class ApplyRetentionPolicy(task.Task):
    def execute(self, context):
        return self.execute_with_log(context)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'ApplyRetentionPolicy.execute')
    def execute_with_log(self, context):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        config_workload = db.config_workload_get(cntx)
        jobschedule = pickle.loads(str(config_workload['jobschedule']))

        backups_to_keep = int(jobschedule['retention_policy_value'])

        backups = db.config_backup_get_all(cntx)

        if len(backups) > backups_to_keep:
            for backup in backups[backups_to_keep:]:
                LOG.info("Deleting backup %s" %backup.id)
                workload_utils.config_backup_delete(cntx, backup.id)

    @autolog.log_method(Logger, 'ApplyRetentionPolicy.revert')
    def revert_with_log(self, *args, **kwargs):
        pass

