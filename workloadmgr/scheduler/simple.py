# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


"""
Simple Scheduler
"""

from oslo.config import cfg

from workloadmgr import db
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.scheduler import chance
from workloadmgr.scheduler import driver
from workloadmgr import utils

simple_scheduler_opts = [
    cfg.IntOpt("max_snapshots",
               default=1,
               help="maximum number of snapshots to schedule per host"),
    cfg.IntOpt("max_restores",
               default=1,
               help="maximum number of restores to schedule per host"),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(simple_scheduler_opts)


class SimpleScheduler(chance.ChanceScheduler):
    """Implements Naive Scheduler that tries to find least loaded host."""

    def schedule_snapshot(self, context, request_spec, filter_properties):
        """Picks a host that is up and has the fewest snapshots in progress."""
        elevated = context.elevated()

        snapshot_id = request_spec.get('snapshot_id')

        # call rpc api

        msg = _("Is the appropriate service running?")
        raise exception.NoValidHost(reason=msg)

    def schedule_restore(self, context, request_spec, filter_properties):
        """Picks a host that is up and has the fewest restores in progress."""
        elevated = context.elevated()

        snapshot_id = request_spec.get('snapshot_id')

        # call rpc api

        msg = _("Is the appropriate service running?")
        raise exception.NoValidHost(reason=msg)
