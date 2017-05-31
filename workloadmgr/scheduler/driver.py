# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


"""
Scheduler base class that all Schedulers should inherit from
"""

from oslo.config import cfg

from workloadmgr import db
from workloadmgr import flags
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import timeutils
from workloadmgr import utils

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='workloadmgr.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    cfg.IntOpt('scheduler_max_attempts',
               default=3,
               help='Maximum number of attempts to schedule a workload'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(scheduler_driver_opts)


def snapshot_update_db(context, snapshot_id, host):
    '''Set the host and set the scheduled_at field of the snapshot.

    :returns: A Snapshot with the updated fields set properly.
    '''
    now = timeutils.utcnow()
    values = {'host': host, 'scheduled_at': now}
    return db.snapshot_update(context, snapshot_id, values)

def restore_update_db(context, restore_id, host):
    '''Set the host and set the scheduled_at field of the restore.

    :returns: A Snapshot with the updated fields set properly.
    '''
    now = timeutils.utcnow()
    values = {'host': host, 'scheduled_at': now}
    return db.restore_update(context, restore_id, values)

def openstack_snapshot_update_db(context, openstack_snapshot_id, host):
    '''Set the host and set the scheduled_at field of the snapshot.
    :returns: A OpenstackSnapshot with the updated fields set properly.
    '''
    now = timeutils.utcnow()
    values = {'host': host, 'scheduled_at': now}
    return db.openstack_config_snapshot_update(context, values, openstack_snapshot_id)

class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
            FLAGS.scheduler_host_manager)

    def get_host_list(self):
        """Get a list of hosts from the HostManager."""
        return self.host_manager.get_host_list()

    def get_service_capabilities(self):
        """Get the normalized set of capabilities for the services.
        """
        return self.host_manager.get_service_capabilities()

    def update_service_capabilities(self, service_name, host, capabilities):
        """Process a capability update from a service node."""
        self.host_manager.update_service_capabilities(service_name,
                                                      host,
                                                      capabilities)

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""
        services = db.service_get_all_by_topic(context, topic)
        return [service['host']
                for service in services
                if utils.service_is_up(service)]

    def schedule(self, context, topic, method, *_args, **_kwargs):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement a fallback schedule"))

    def schedule_snapshot(self, context, request_spec, filter_properties):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement schedule_snapshot"))
    
    def schedule_restore(self, context, request_spec, filter_properties):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement schedule_restore"))    
