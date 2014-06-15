# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 OpenStack, LLC.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Scheduler Service
"""

from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr import manager
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.notifier import api as notifier

LOG = logging.getLogger(__name__)

scheduler_driver_opt = cfg.StrOpt('scheduler_driver',
                                  default='workloadmgr.scheduler.filter_scheduler.'
                                          'FilterScheduler',
                                  help='Default scheduler driver to use')

FLAGS = flags.FLAGS
FLAGS.register_opt(scheduler_driver_opt)


class SchedulerManager(manager.Manager):
    """Chooses a host to create snapshot."""

    RPC_API_VERSION = '1.2'

    def __init__(self, scheduler_driver=None, service_name=None,
                 *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def init_host(self):
        ctxt = context.get_admin_context()

    def get_host_list(self, context):
        """Get a list of hosts from the HostManager."""
        return self.driver.get_host_list()

    def get_service_capabilities(self, context):
        """Get the normalized set of capabilities for this zone."""
        return self.driver.get_service_capabilities()

    def update_service_capabilities(self, context, service_name=None,
                                    host=None, capabilities=None, **kwargs):
        """Process a capability update from a service node."""
        if capabilities is None:
            capabilities = {}
        self.driver.update_service_capabilities(service_name,
                                                host,
                                                capabilities)

    def workload_snapshot(self, context, topic, snapshot_id,
                          request_spec=None, filter_properties=None):
        try:
            if request_spec is None:
                request_spec = {}
                snapshot_ref = db.snapshot_get(context, snapshot_id)

                request_spec.update( {'snapshot_id': snapshot_id, 'snapshot_properties':{}})

            self.driver.schedule_workload_snapshot(context, request_spec,
                                                   filter_properties)
        except exception.NoValidHost as ex:
            snapshot_state = {'status': {'status': 'error'}}
            self._set_snapshot_state_and_notify('workload_snapshot',
                                              snapshot_state,
                                              context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                snapshot_state = {'status': {'status': 'error'}}
                self._set_snapshot_state_and_notify('workload_snapshot',
                                                  snapshot_state,
                                                  context, ex, request_spec)

    def _set_snapshot_state_and_notify(self, method, updates, context, ex,
                                     request_spec):
        LOG.error(_("Failed to schedule_%(method)s: %(ex)s") % locals())
  
        snapshot_status = updates['status']
        properties = request_spec.get('snapshot_properties', {})

        snapshot_id = request_spec.get('snapshot_id', None)

        if snapshot_id:
            db.snapshot_update(context, snapshot_id, snapshot_status)

        payload = dict(request_spec=request_spec,
                       snapshot_properties=properties,
                       snapshot_id=snapshot_id,
                       state=snapshot_status,
                       method=method,
                       reason=ex)

        notifier.notify(context, notifier.publisher_id("scheduler"),
                        'scheduler.' + method, notifier.ERROR, payload)

