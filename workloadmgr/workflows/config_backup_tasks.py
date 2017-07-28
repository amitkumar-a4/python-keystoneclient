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
from workloadmgr.virt import driver
from workloadmgr.openstack.common import log as logging

from workloadmgr.workloads import workload_utils
from workloadmgr import autolog

from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

vmtasks_opts = []

CONF = cfg.CONF
CONF.register_opts(vmtasks_opts)


class CopyConfigFiles(task.Task):

    def execute(self, context, backup_id, host, params):
        return self.execute_with_log(context, backup_id, host, params)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'CopyConfigFiles.execute')
    def execute_with_log(self, context, backup_id, host, params):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        config_workload = db.config_workload_get(cntx, CONF.cloud_unique_id)
        backend_endpoint = config_workload.backup_media_target
        params['host'] = host

        metadata = {
            'resource_id': host + '_' + str( int(time.time()) ),
            'backend_endpoint': backend_endpoint,
            'snapshot_id': backup_id
        }
        params['metadata'] = metadata
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        status = virtdriver._vast_methods_call_by_function(compute_service.vast_config_backup,
                                                     cntx, backup_id,
                                                     params)
        virtdriver._wait_for_remote_nova_process(cntx, compute_service,
                                      metadata,
                                      backup_id,
                                      backend_endpoint)
        db.config_backup_update(cntx, backup_id, {
                                    'upload_summary' : pickle.dumps(status),
                                    })

    @autolog.log_method(Logger, 'CopyConfigFiles.revert')
    def revert_with_log(self, *args, **kwargs):
        pass

def UnorderedCopyConfigFiles(backup_id, hosts, params):
    flow = uf.Flow("copyconfigfilesuf")
    for host in hosts:
        flow.add(CopyConfigFiles(name="CopyConfigFile_" + host,
                                 rebind={'backup_id':'backup_id',
                                         'host':host,
                                         'params':'params'
                                        } ))
    return flow

def UnorderedCopyConfigFilesFromRemoteHost(backup_id, hosts, params):
        
    flow = uf.Flow("copyconfigfilesremotehostuf")
    compute_hosts = params['compute_hosts']
    params['target'] = 'controller'
    #If list of controller nodes is more than contego
    #nodes then targetting all requests to one node only
    if len(hosts) > len(compute_hosts):
        for host in hosts:
            params['remote_host'] = host
            flow.add(CopyConfigFiles(name="CopyConfigFileRemoteHost_" + compute_hosts[0],
                                 rebind={'backup_id':'backup_id',
                                         'host':compute_hosts[0],
                                         'params': params
                                        } ))
    else:
        #If If list of controller nodes is less than or 
        #equal that pairing each compute node with controller node.
        nodes = zip(compute_hosts, host)
        for compute_host,controller_host in nodes:
            params['remote_host'] = controller_host
            flow.add(CopyConfigFiles(name="CopyConfigFileRemoteHost_" + compute_host,
                                 rebind={'backup_id':'backup_id',
                                         'host':compute_host,
                                         'params': params
                                        } ))
    return flow


class ApplyRetentionPolicy(task.Task):

    def execute(self, context, config_workload_id):
        return self.execute_with_log(context, config_workload_id)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'ApplyRetentionPolicy.execute')
    def execute_with_log(self, context, config_workload_id):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        config_workload = db.config_workload_get(cntx, config_workload_id)
        jobschedule = pickle.loads(str(config_workload['jobschedule']))

        backups_to_keep = int(jobschedule['retention_policy_value'])

        backups = db.config_backup_get_all(cntx)

        if len(backups) > backups_to_keep:
            for backup in backups[backups_to_keep:]:
                workload_utils.config_backup_delete(cntx, backup.id)

    @autolog.log_method(Logger, 'ApplyRetentionPolicy.revert')
    def revert_with_log(self, *args, **kwargs):
        pass


