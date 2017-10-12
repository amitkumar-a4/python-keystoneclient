# Copyright 2014 TrilioData Inc.
# All Rights Reserved.

"""
Chance (Random) Scheduler implementation
"""

import random

from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.scheduler import driver


FLAGS = flags.FLAGS


class ChanceScheduler(driver.Scheduler):
    """Implements Scheduler as a random node selector."""

    def _filter_hosts(self, request_spec, hosts, **kwargs):
        """Filter a list of hosts based on request_spec."""

        filter_properties = kwargs.get('filter_properties', {})
        ignore_hosts = filter_properties.get('ignore_hosts', [])
        hosts = [host for host in hosts if host not in ignore_hosts]
        return hosts

    def _schedule(self, context, topic, request_spec, **kwargs):
        """Picks a host that is up at random."""

        elevated = context.elevated()
        hosts = self.hosts_up(elevated, topic)
        if not hosts:
            msg = _("Is the appropriate service running?")
            raise exception.NoValidHost(reason=msg)

        hosts = self._filter_hosts(request_spec, hosts, **kwargs)
        if not hosts:
            msg = _("Could not find another host")
            raise exception.NoValidHost(reason=msg)

        return hosts[int(random.random() * len(hosts))]

    def schedule_snapshot(self, context, request_spec, filter_properties):
        """Picks a host that is up at random."""
        topic = FLAGS.workloads_topic
        host = self._schedule(context, topic, request_spec,
                              filter_properties=filter_properties)
        snapshot_id = request_spec['snapshot_id']

        # call rpc api

    def schedule_restore(self, context, request_spec, filter_properties):
        """Picks a host that is up at random."""
        topic = FLAGS.workloads_topic
        host = self._schedule(context, topic, request_spec,
                              filter_properties=filter_properties)
        restore_id = request_spec['restore_id']

        # call rpc api
