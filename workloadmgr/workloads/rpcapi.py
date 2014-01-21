# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Client side of the workload scheduler RPC API.
"""

from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import rpc
import workloadmgr.openstack.common.rpc.proxy


LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class WorkloadMgrAPI(workloadmgr.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the workloadmgr rpc API.

    API version history:

        1.0 - Initial version.
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(WorkloadMgrAPI, self).__init__(
            topic=FLAGS.workloads_topic,
            default_version=self.BASE_RPC_API_VERSION)

    def workload_create(self, ctxt, host, workload_id):
        LOG.debug("create_workload in rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_create', workload_id=workload_id),
                  topic=topic)

    def workload_snapshot(self, ctxt, host, snapshot_id, full):
        LOG.debug("snapshot workload in rpcapi snapshot_id:%s full:%s", snapshot_id, full)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_snapshot',snapshot_id=snapshot_id, full=full),
                  topic=topic)

    def workload_delete(self, ctxt, host, workload_id):
        LOG.debug("delete_workload  rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('workload_delete', workload_id=workload_id),
                  topic=topic)

    def snapshot_restore(self, ctxt, host, snapshot_id, test):
        LOG.debug("restore_snapshot in rpcapi snapshot_id %s", 
                              snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("restore queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('snapshot_restore', snapshot_id=snapshot_id, test=test),
                  topic=topic)
        
    def snapshot_delete(self, ctxt, host, snapshot_id):
        LOG.debug("delete_snapshot  rpcapi snapshot_id %s", snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('snapshot_delete',snapshot_id=snapshot_id),
                  topic=topic)
