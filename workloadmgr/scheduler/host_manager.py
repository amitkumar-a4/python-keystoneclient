# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


"""
Manage hosts in the current zone.
"""

import UserDict

from oslo_config import cfg

from workloadmgr import db
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.scheduler import filters
from workloadmgr.openstack.common.scheduler import weights
from workloadmgr.scheduler.weights.capacity import CapacityWeigher
from workloadmgr.openstack.common import timeutils
from workloadmgr import utils

host_manager_opts = [
    cfg.ListOpt('scheduler_default_filters',
                default=[
                    'AvailabilityZoneFilter',
                    'CapacityFilter',
                    #'CapabilitiesFilter'
                ],
                help='Which filter class names to use for filtering hosts '
                     'when not specified in the request.'),
    cfg.ListOpt('scheduler_default_weighers',
                default=[
                    'CapacityWeigher'
                ],
                help='Which weigher class names to use for weighing hosts.')
]

FLAGS = flags.FLAGS
FLAGS.register_opts(host_manager_opts)

LOG = logging.getLogger(__name__)


class ReadOnlyDict(UserDict.IterableUserDict):
    """A read-only dict."""

    def __init__(self, source=None):
        self.data = {}
        self.update(source)

    def __setitem__(self, key, item):
        raise TypeError

    def __delitem__(self, key):
        raise TypeError

    def clear(self):
        raise TypeError

    def pop(self, key, *args):
        raise TypeError

    def popitem(self):
        raise TypeError

    def update(self, source=None):
        if source is None:
            return
        elif isinstance(source, UserDict.UserDict):
            self.data = source.data
        elif isinstance(source, type({})):
            self.data = source
        else:
            raise TypeError


class HostState(object):
    """Mutable and immutable information tracked for a host."""

    def __init__(self, host, capabilities=None, service=None):
        self.host = host
        self.update_capabilities(capabilities, service)

        self.workloadmgr_backend_name = None  # Swift/LocalFS/tvaultfs
        self.vendor_name = None
        self.driver_version = 0

        # Mutable available resources.
        # These will change as new snapshot jobs are scheduled
        self.running_snapshots = 0
        self.running_file_search = 0

        self.updated = None

    def update_capabilities(self, capabilities=None, service=None):
        # Read-only capability dicts

        if capabilities is None:
            capabilities = {}
        self.capabilities = ReadOnlyDict(capabilities)
        if service is None:
            service = {}
        self.service = ReadOnlyDict(service)

    def update_from_workloadmgr_capability(self, capability):
        """Update information about a host from its workloadmgr node info."""
        if capability:
            if self.updated and self.updated > capability['timestamp']:
                return

            self.workloadmgr_backend = capability.get(
                'workloadmgr_backend_name', None)
            self.vendor_name = capability.get('vendor_name', None)
            self.driver_version = capability.get('driver_version', None)

            self.running_snapshots = capability['running_snapshots']

            self.updated = capability['timestamp']

    def consume_from_snapshot(self, snapshot):
        """Incrementally update host state snapshot request"""
        self.updated = timeutils.utcnow()
        self.running_snapshots += 1
        pass

    def consume_from_file_search(self, search):
        """Incrementally update host state search request"""
        self.updated = timeutils.utcnow()
        self.running_file_search += 1
        pass

    def __repr__(self):
        return ("host '%s': running snapshots: %s" %
                (self.host, self.running_snapshots))


class HostManager(object):
    """Base HostManager class."""

    host_state_cls = HostState

    def __init__(self):
        self.service_states = {}  # { <host>: {<service>: {cap k : v}}}
        self.host_state_map = {}
        self.host_state_running = {}
        self.filter_handler = filters.HostFilterHandler(
            'workloadmgr.scheduler.' 'filters')
        self.filter_classes = self.filter_handler.get_all_classes()
        self.weight_handler = weights.HostWeightHandler(
            'workloadmgr.scheduler.weights')
        self.weight_classes = self.weight_handler.get_all_classes()
        # Hardcode this for now. For some reason get_all_classes() is not getting
        # all weight classes. The routine was working in the python interpreter
        # though.
        self.weight_classes = [CapacityWeigher]

    def _choose_host_filters(self, filter_cls_names):
        """Since the caller may specify which filters to use we need
        to have an authoritative list of what is permissible. This
        function checks the filter names against a predefined set
        of acceptable filters.
        """
        if filter_cls_names is None:
            filter_cls_names = FLAGS.scheduler_default_filters

        if filter_cls_names and not isinstance(
                filter_cls_names, (list, tuple)):
            filter_cls_names = [filter_cls_names]
        good_filters = []
        bad_filters = []
        if filter_cls_names:
            for filter_name in filter_cls_names:
                found_class = False
                for cls in self.filter_classes:
                    if cls.__name__ == filter_name:
                        found_class = True
                        good_filters.append(cls)
                        break
                if not found_class:
                    bad_filters.append(filter_name)
        if bad_filters:
            msg = ", ".join(bad_filters)
            raise exception.SchedulerHostFilterNotFound(filter_name=msg)
        return good_filters

    def _choose_host_weighers(self, weight_cls_names):
        """Since the caller may specify which weighers to use, we need
        to have an authoritative list of what is permissible. This
        function checks the weigher names against a predefined set
        of acceptable weighers.
        """
        if weight_cls_names is None:
            weight_cls_names = FLAGS.scheduler_default_weighers
        if weight_cls_names and not isinstance(
                weight_cls_names, (list, tuple)):
            weight_cls_names = [weight_cls_names]

        good_weighers = []
        bad_weighers = []
        if weight_cls_names:
            for weigher_name in weight_cls_names:
                found_class = False
                for cls in self.weight_classes:
                    if cls.__name__ == weigher_name:
                        good_weighers.append(cls)
                        found_class = True
                        break
                if not found_class:
                    bad_weighers.append(weigher_name)
            if bad_weighers:
                msg = ", ".join(bad_weighers)
                raise exception.SchedulerHostWeigherNotFound(weigher_name=msg)
        return good_weighers

    def get_filtered_hosts(self, hosts, filter_properties,
                           filter_class_names=None):
        """Filter hosts and return only ones passing all filters"""
        return hosts
        #filter_classes = self._choose_host_filters(filter_class_names)
        # return self.filter_handler.get_filtered_objects(filter_classes,
        # hosts,
        # filter_properties)

    def get_weighed_hosts(self, hosts, weight_properties,
                          weigher_class_names=None):
        """Weigh the hosts"""
        weigher_classes = self._choose_host_weighers(weigher_class_names)
        return self.weight_handler.get_weighed_objects(weigher_classes,
                                                       hosts,
                                                       weight_properties)

    def update_service_capabilities(self, service_name, host, capabilities):
        """Update the per-service capabilities based on this notification."""
        if service_name != 'volume':
            LOG.debug(_('Ignoring %(service_name)s service update '
                        'from %(host)s'), locals())
            return

        LOG.debug(_("Received %(service_name)s service update from "
                    "%(host)s.") % locals())

        # Copy the capabilities, so we don't modify the original dict
        capab_copy = dict(capabilities)
        capab_copy["timestamp"] = timeutils.utcnow()  # Reported time
        self.service_states[host] = capab_copy

    def get_all_host_states(self, context):
        """Returns a dict of all the hosts the HostManager
          knows about. Also, each of the consumable resources in HostState
          are pre-populated and adjusted based on data in the db.

          For example:
          {'192.168.1.100': HostState(), ...}
        """

        # Get resource usage across the available workloadmanager nodes:
        topic = FLAGS.workloads_topic
        hosts_snapshots = db.snapshot_get_running_snapshots_by_host(context)
        self.host_state_running = {}
        for obj in hosts_snapshots:
            self.host_state_running[obj[0]] = int(obj[1])

        wlm_services = db.service_get_all_by_topic(context, topic)
        for service in wlm_services:
            if not utils.service_is_up(service) or service['disabled']:
                LOG.warn(_("service is down or disabled."))
                continue
            host = service['host']
            capabilities = self.service_states.get(host, None)
            host_state = self.host_state_map.get(host)
            if host_state:
                # copy capabilities to host_state.capabilities
                host_state.update_capabilities(capabilities,
                                               dict(service.iteritems()))
            else:
                host_state = self.host_state_cls(
                    host, capabilities=capabilities, service=dict(
                        service.iteritems()))
            # update host_state
            if host in self.host_state_running.keys():
                host_state.running_snapshots = self.host_state_running[host]
            else:
                host_state.running_snapshots = 0

            self.host_state_map[host] = host_state
            host_state.update_from_workloadmgr_capability(capabilities)

        return self.host_state_map.itervalues()
