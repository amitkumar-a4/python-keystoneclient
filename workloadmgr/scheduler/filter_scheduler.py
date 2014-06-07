# Copyright (c) 2011 Intel Corporation
# Copyright (c) 2011 OpenStack, LLC.
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
The FilterScheduler is for scheduling next snapshot operation
"""

import operator

from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.scheduler import driver
from workloadmgr.workloads import rpcapi as workloads_rpcapi
from workloadmgr.scheduler import scheduler_options


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class FilterScheduler(driver.Scheduler):
    """Scheduler that can be used for filtering and weighing."""
    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)
        self.cost_function_cache = None
        self.options = scheduler_options.SchedulerOptions()
        self.max_attempts = self._max_attempts()
        self.workloads_rpcapi = workloads_rpcapi.WorkloadMgrAPI()

    def schedule(self, context, topic, method, *args, **kwargs):
        """The schedule() contract requires we return the one
        best-suited host for this request.
        """
        self._schedule(context, topic, *args, **kwargs)

    def _get_configuration_options(self):
        """Fetch options dictionary. Broken out for testing."""
        return self.options.get_configuration()

    def populate_filter_properties(self, request_spec, filter_properties):
        """Stuff things into filter_properties.  Can be overridden in a
        subclass to add more data.
        """
        pass

    def schedule_workload_snapshot(self, context, request_spec, filter_properties):
        weighed_host = self._schedule(context, request_spec, filter_properties)

        if not weighed_host:
            raise exception.NoValidHost(reason="")

        host = weighed_host.obj.host
        snapshot_id = request_spec['snapshot_id']

        updated_snapshot = driver.snapshot_update_db(context, snapshot_id, host)
        self._post_select_populate_filter_properties(filter_properties,
                                                     weighed_host.obj)

        # context is not serializable
        if filter_properties:
           filter_properties.pop('context', None)

        self.workloads_rpcapi.workload_snapshot(context, host, snapshot_id)

    def _post_select_populate_filter_properties(self, filter_properties,
                                                host_state):
        """Add additional information to the filter properties after a host has
        been selected by the scheduling process.
        """
        # Add a retry entry for the selected workloadmgr backend:
        self._add_retry_host(filter_properties, host_state.host)

    def _add_retry_host(self, filter_properties, host):
        """Add a retry entry for the selected workloadmgr backend. In the event that
        the request gets re-scheduled, this entry will signal that the given
        backend has already been tried.
        """
        if not filter_properties:
            return

        retry = filter_properties.get('retry', None)
        if not retry:
            return

        hosts = retry['hosts']
        hosts.append(host)

    def _max_attempts(self):
        max_attempts = FLAGS.scheduler_max_attempts
        if max_attempts < 1:
            msg = _("Invalid value for 'scheduler_max_attempts', "
                    "must be >=1")
            raise exception.InvalidParameterValue(err=msg)
        return max_attempts

    def _log_snapshot_error(self, snapshot_id, retry):
        """If the request contained an exception from a previous workload_snapshot operation, 
           log it to aid debugging
        """
        exc = retry.pop('exc', None)  # string-ified exception from snapshot
        if not exc:
            return  # no exception info from a previous attempt, skip

        hosts = retry.get('hosts', None)
        if not hosts:
            return  # no previously attempted hosts, skip

        last_host = hosts[-1]
        msg = _("Error scheduling %(snapshot_id)s from last workloadmgr-service: "
                "%(last_host)s : %(exc)s") % locals()
        LOG.error(msg)

    def _populate_retry(self, filter_properties, properties):
        """Populate filter properties with history of retries for this
        request. If maximum retries is exceeded, raise NoValidHost.
        """
        max_attempts = self.max_attempts
        retry = filter_properties.pop('retry', {})

        if max_attempts == 1:
            # re-scheduling is disabled.
            return

        # retry is enabled, update attempt count:
        if retry:
            retry['num_attempts'] += 1
        else:
            retry = {
                'num_attempts': 1,
                'hosts': []  # list of workloadmgr service hosts tried
            }
        filter_properties['retry'] = retry

        snapshot_id = properties.get('snapshot_id')
        self._log_snapshot_error(snapshot_id, retry)

        if retry['num_attempts'] > max_attempts:
            msg = _("Exceeded max scheduling attempts %(max_attempts)d for "
                    "snapshot %(snapshot_id)s") % locals()
            raise exception.NoValidHost(reason=msg)

    def _schedule(self, context, request_spec, filter_properties=None):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()

        snapshot_properties = request_spec['snapshot_properties']
        resource_properties = snapshot_properties.copy()
        request_spec.update({'resource_properties': resource_properties})

        config_options = self._get_configuration_options()

        if filter_properties is None:
            filter_properties = {}
        self._populate_retry(filter_properties, resource_properties)

        filter_properties.update({'context': context,
                                  'request_spec': request_spec,
                                  'config_options': config_options})

        self.populate_filter_properties(request_spec,
                                        filter_properties)

        hosts = self.host_manager.get_all_host_states(elevated)

        hosts = self.host_manager.get_filtered_hosts(hosts,
                                                     filter_properties)
        if not hosts:
            return None

        LOG.debug(_("Filtered %(hosts)s") % locals())
        # weighted_host = WeightedHost() ... the best
        # host for the job.
        weighed_hosts = self.host_manager.get_weighed_hosts(hosts,
                                                            filter_properties)
        best_host = weighed_hosts[0]
        LOG.debug(_("Choosing %(best_host)s") % locals())
        best_host.obj.consume_from_snapshot(snapshot_properties)
        return best_host
