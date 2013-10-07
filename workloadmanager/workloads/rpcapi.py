# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Client side of the workload RPC API.
"""

from workloadmanager import flags
from workloadmanager.openstack.common import log as logging
from workloadmanager.openstack.common import rpc
import workloadmanager.openstack.common.rpc.proxy


LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class WorkloadAPI(workloadmanager.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the workloadmanager rpc API.

    API version history:

        1.0 - Initial version.
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(WorkloadAPI, self).__init__(
            topic=FLAGS.workloads_topic,
            default_version=self.BASE_RPC_API_VERSION)

    def workload_create(self, ctxt, host, workload_id):
        LOG.debug("create_workload in rpcapi backup_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_create',
                                workload_id=workload_id),
                  topic=topic)

    def workload_execute(self, ctxt, host, snapshot_id):
        LOG.debug("execute_workload in rpcapi snapshot_id %s", snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_execute',
                                snapshot_id=snapshot_id),
                  topic=topic)

    def workload_prepare(self, ctxt, host, snapshot_id):
        LOG.debug("prepare_workload in rpcapi snapshot_id %s", snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_prepare',
                                snapshot_id=snapshot_id),
                  topic=topic)

    def workload_delete(self, ctxt, host, workload_id):
        LOG.debug("delete_workload  rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('workload_delete', workload_id=workload_id),
                  topic=topic)

    def snapshot_hydrate(self, ctxt, host, snapshot_id):
        LOG.debug("hydrate_backup in rpcapi snapshot_id %s", 
                              snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("restore queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('snapshot_hydrate',snapshot_id=snapshot_id),
                  topic=topic)
        
    def snapshot_delete(self, ctxt, host, snapshot_id):
        LOG.debug("delete_backupinstance  rpcapi snapshot_id %s", 
                        snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('snapshot_delete',snapshot_id=snapshot_id),
                  topic=topic)
