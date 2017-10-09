# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


"""
Client side of the scheduler manager RPC API.
"""

from workloadmgr import flags
from workloadmgr.openstack.common import jsonutils
import workloadmgr.openstack.common.rpc.proxy


FLAGS = flags.FLAGS


class SchedulerAPI(workloadmgr.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the scheduler rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Add workload_snapshot() method
        1.2 - Add request_spec, filter_properties arguments
              to workload_snapshot()
    '''

    RPC_API_VERSION = '1.0'

    def __init__(self):
        super(SchedulerAPI, self).__init__(
            topic=FLAGS.scheduler_topic,
            default_version=self.RPC_API_VERSION)

    def file_search(self, ctxt, topic, search_id,
                    request_spec=None, filter_properties=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        return self.cast(ctxt, self.make_msg(
            'file_search', topic=topic,
            search_id=search_id,
            request_spec=request_spec_p,
            filter_properties=filter_properties),
            version='1.2')

    def workload_snapshot(self, ctxt, topic, snapshot_id,
                          request_spec=None, filter_properties=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        return self.cast(ctxt, self.make_msg(
            'workload_snapshot', topic=topic,
            snapshot_id=snapshot_id,
            request_spec=request_spec_p,
            filter_properties=filter_properties),
            version='1.2')

    def snapshot_restore(self, ctxt, topic, restore_id,
                         request_spec=None, filter_properties=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        return self.cast(ctxt, self.make_msg(
            'snapshot_restore', topic=topic,
            restore_id=restore_id,
            request_spec=request_spec_p,
            filter_properties=filter_properties),
            version='1.2')

    def config_backup(self, ctxt, topic, backup_id,
                      request_spec=None, filter_properties=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        return self.cast(ctxt, self.make_msg(
            'config_backup', topic=topic,
            backup_id=backup_id,
            request_spec=request_spec_p,
            filter_properties=filter_properties),
            version='1.2')

    def update_service_capabilities(self, ctxt,
                                    service_name, host,
                                    capabilities):
        self.fanout_cast(ctxt, self.make_msg('update_service_capabilities',
                                             service_name=service_name, host=host,
                                             capabilities=capabilities))
