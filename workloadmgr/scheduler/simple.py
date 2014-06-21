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
    cfg.IntOpt("max_gigabytes",
               default=10000,
               help="maximum number of volume gigabytes to allow per host"), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(simple_scheduler_opts)


class SimpleScheduler(chance.ChanceScheduler):
    """Implements Naive Scheduler that tries to find least loaded host."""

    def schedule_create_volume(self, context, request_spec, filter_properties):
        """Picks a host that is up and has the fewest volumes."""
        elevated = context.elevated()

        volume_id = request_spec.get('volume_id')
        snapshot_id = request_spec.get('snapshot_id')
        image_id = request_spec.get('image_id')
        volume_properties = request_spec.get('volume_properties')
        volume_size = volume_properties.get('size')
        availability_zone = volume_properties.get('availability_zone')

        zone, host = None, None
        if availability_zone:
            zone, _x, host = availability_zone.partition(':')
        if host and context.is_admin:
            topic = FLAGS.volume_topic
            service = db.service_get_by_args(elevated, host, topic)
            if not utils.service_is_up(service):
                raise exception.WillNotSchedule(host=host)
            updated_volume = driver.volume_update_db(context, volume_id, host)
            self.volume_rpcapi.create_volume(context,
                                             updated_volume,
                                             host,
                                             snapshot_id,
                                             image_id)
            return None

        results = db.service_get_all_volume_sorted(elevated)
        if zone:
            results = [(service, gigs) for (service, gigs) in results
                       if service['availability_zone'] == zone]
        for result in results:
            (service, volume_gigabytes) = result
            if volume_gigabytes + volume_size > FLAGS.max_gigabytes:
                msg = _("Not enough allocatable volume gigabytes remaining")
                raise exception.NoValidHost(reason=msg)
            if utils.service_is_up(service) and not service['disabled']:
                updated_volume = driver.volume_update_db(context, volume_id,
                                                         service['host'])
                self.volume_rpcapi.create_volume(context,
                                                 updated_volume,
                                                 service['host'],
                                                 snapshot_id,
                                                 image_id)
                return None
        msg = _("Is the appropriate service running?")
        raise exception.NoValidHost(reason=msg)
