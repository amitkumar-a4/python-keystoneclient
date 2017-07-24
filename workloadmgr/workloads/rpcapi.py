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
from workloadmgr import autolog


LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)
FLAGS = flags.FLAGS


class WorkloadMgrAPI(workloadmgr.openstack.common.rpc.proxy.RpcProxy):
    """
    Client side of the workloadmgr rpc API.
    API version history:
    1.0 - Initial version.
    """

    BASE_RPC_API_VERSION = '1.0'

    @autolog.log_method(logger=Logger)
    def __init__(self):
        super(WorkloadMgrAPI, self).__init__(
            topic=FLAGS.workloads_topic,
            default_version=self.BASE_RPC_API_VERSION)
    
    @autolog.log_method(logger=Logger, password_arg=5)    
    def workload_type_discover_instances(self, ctxt, host, workload_type_id, metadata):
        LOG.debug("workload_type_discover_instances in rpcapi workload_type_id %s", workload_type_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        instances = self.call(ctxt,
                              self.make_msg('workload_type_discover_instances', workload_type_id=workload_type_id, metadata=metadata),
                              topic=topic,
                              timeout=300)
        return instances
    
    @autolog.log_method(logger=Logger, password_arg=5)
    def workload_type_topology(self, ctxt, host, workload_type_id, metadata):
        LOG.debug("workload_type_topology in rpcapi workload_type_id %s", workload_type_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        topology = self.call(ctxt,
                              self.make_msg('workload_type_topology', workload_type_id=workload_type_id, metadata=metadata),
                              topic=topic,
                              timeout=300)
        return topology
    
    @autolog.log_method(logger=Logger)
    def workload_discover_instances(self, ctxt, host, workload_id):
        LOG.debug("workload_discover_instances in rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        instances = self.call(ctxt,
                              self.make_msg('workload_discover_instances', workload_id=workload_id),
                              topic=topic,
                              timeout=300)
        return instances

    @autolog.log_method(logger=Logger)
    def workload_get_topology(self, ctxt, host, workload_id):
        LOG.debug("workload_get_topology in rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        topology = self.call(ctxt,
                              self.make_msg('workload_get_topology', workload_id=workload_id),
                              topic=topic,
                              timeout=300)
        return topology
    
    @autolog.log_method(logger=Logger)    
    def workload_get_workflow_details(self, ctxt, host, workload_id):
        LOG.debug("workload_get_workflow_details in rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        workflow = self.call(ctxt,
                              self.make_msg('workload_get_workflow_details', workload_id=workload_id),
                              topic=topic,
                              timeout=300)
        return workflow      
    
    @autolog.log_method(logger=Logger)              
    def workload_create(self, ctxt, host, workload_id):
        LOG.debug("create_workload in rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_create', workload_id=workload_id),
                  topic=topic)

    @autolog.log_method(logger=Logger)
    def workload_snapshot(self, ctxt, host, snapshot_id):
        LOG.debug("snapshot workload in rpcapi snapshot_id:%s", snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_snapshot',snapshot_id=snapshot_id),
                  topic=topic)

    @autolog.log_method(logger=Logger)
    def workload_reset(self, ctxt, host, workload_id):
        LOG.debug("workload_reset workload_id:%s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('workload_reset',workload_id=workload_id),
                  topic=topic)

    @autolog.log_method(logger=Logger)
    def workload_delete(self, ctxt, host, workload_id):
        LOG.debug("delete_workload  rpcapi workload_id %s", workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('workload_delete', workload_id=workload_id),
                  topic=topic)
    
    @autolog.log_method(logger=Logger)
    def snapshot_restore(self, ctxt, host, restore_id):
        LOG.debug("restore_snapshot in rpcapi restore_id %s", restore_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("restore queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('snapshot_restore', restore_id=restore_id),
                  topic=topic)
    
    @autolog.log_method(logger=Logger)    
    def snapshot_delete(self, ctxt, host, snapshot_id, task_id):
        LOG.debug("delete_snapshot  rpcapi snapshot_id %s", snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('snapshot_delete', snapshot_id=snapshot_id, task_id=task_id),
                  topic=topic)
        
    @autolog.log_method(logger=Logger)     
    def snapshot_mount(self, ctxt, host, snapshot_id, mount_vm_id):
        LOG.debug("snapshot_mount in rpcapi snapshot_id %s, mount_vm_id %s",
                    snapshot_id, mount_vm_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt, self.make_msg('snapshot_mount',
                                      snapshot_id=snapshot_id,
                                      mount_vm_id=mount_vm_id),
                   topic=topic)
    
    @autolog.log_method(logger=Logger)     
    def snapshot_dismount(self, ctxt, host, snapshot_id):
        LOG.debug("snapshot_dismount in rpcapi snapshot_id %s",
                   snapshot_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.call(ctxt,
                  self.make_msg('snapshot_dismount',
                                snapshot_id=snapshot_id),
                  topic=topic,
                  timeout=300)
    
    @autolog.log_method(logger=Logger)    
    def restore_delete(self, ctxt, host, restore_id):
        LOG.debug("delete_restore  rpcapi restore_id %s", restore_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.call(ctxt,
                  self.make_msg('restore_delete',restore_id=restore_id),
                  topic=topic,
                  timeout=300)        

    @autolog.log_method(logger=Logger)
    def config_workload(self, ctxt, host, config_workload_id):
        LOG.debug("config_workload in rpcapi workload_id %s", config_workload_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('config_workload', config_workload_id=config_workload_id),
                  topic=topic)

    @autolog.log_method(logger=Logger)
    def config_backup(self, ctxt, host, backup_id):
        LOG.debug("config_backup in rpcapi backup_id:%s", backup_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('config_backup', backup_id=backup_id), topic=topic)

    @autolog.log_method(logger=Logger)
    def config_backup_delete(self, ctxt, host, backup_id, task_id):
        LOG.debug("config_backup rpcapi backup_id:%s", backup_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('config_backup_delete', backup_id=backup_id,
                                task_id=task_id), topic=topic)
