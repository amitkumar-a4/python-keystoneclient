# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Defines interface for DB access.

The underlying driver is loaded as a :class:`LazyPluggable`.

Functions in this module are imported into the workloadmgr.db namespace. Call these
functions from workloadmgr.db namespace, not the workloadmgr.db.api namespace.

All functions in this module return objects that implement a dictionary-like
interface. Currently, many of these objects are sqlalchemy objects that
implement a dictionary interface. However, a future goal is to have all of
these objects be simple dictionaries.


**Related Flags**

:db_backend:  string to lookup in the list of LazyPluggable backends.
              `sqlalchemy` is the only supported backend right now.

:sql_connection:  string specifying the sqlalchemy connection to use, like:
                  `sqlite:///var/lib/workloadmgr/workloadmgr.sqlite`.

:enable_new_services:  when adding a new service to the database, is it in the
                       pool of available hardware (Default: True)

"""

from oslo.config import cfg

from workloadmgr import exception
from workloadmgr import flags
from workloadmgr import utils

db_opts = [
    cfg.StrOpt('db_backend',
               default='sqlalchemy',
               help='The backend to use for db'),
    cfg.BoolOpt('enable_new_services',
                default=True,
                help='Services to be added to the available pool on create'),
    cfg.StrOpt('workload_name_template',
               default='workload-%s',
               help='Template string to be used to generate workload names'), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(db_opts)

IMPL = utils.LazyPluggable('db_backend',
                           sqlalchemy='workloadmgr.db.sqlalchemy.api')


class NoMoreTargets(exception.WorkloadMgrException):
    """No more available targets"""
    pass

###################


def service_destroy(context, service_id):
    """Destroy the service or raise if it does not exist."""
    return IMPL.service_destroy(context, service_id)

def service_get(context, service_id):
    """Get a service or raise if it does not exist."""
    return IMPL.service_get(context, service_id)

def service_get_by_host_and_topic(context, host, topic):
    """Get a service by host it's on and topic it listens to."""
    return IMPL.service_get_by_host_and_topic(context, host, topic)

def service_get_all(context, disabled=None):
    """Get all services."""
    return IMPL.service_get_all(context, disabled)

def service_get_all_by_topic(context, topic):
    """Get all services for a given topic."""
    return IMPL.service_get_all_by_topic(context, topic)

def service_get_all_by_host(context, host):
    """Get all services for a given host."""
    return IMPL.service_get_all_by_host(context, host)

def service_get_by_args(context, host, binary):
    """Get the state of an service by node name and binary."""
    return IMPL.service_get_by_args(context, host, binary)

def service_create(context, values):
    """Create a service from the values dictionary."""
    return IMPL.service_create(context, values)

def service_update(context, service_id, values):
    """Set the given properties on an service and update it.

    Raises NotFound if service does not exist.

    """
    return IMPL.service_update(context, service_id, values)

###################


def workload_get(context, workload_id):
    """Get a workload or raise if it does not exist."""
    return IMPL.workload_get(context, workload_id)

def workload_show(context, workload_id):
    """Get more details of the  workload or raise if it does not exist."""
    return IMPL.workload_show(context, workload_id)

def workload_get_all(context):
    """Get all workloads."""
    return IMPL.workload_get_all(context)

def workload_get_all_by_host(context, host):
    """Get all workloads belonging to a host."""
    return IMPL.workload_get_all_by_host(context, host)

def workload_create(context, values):
    """Create a workload from the values dictionary."""
    return IMPL.workload_create(context, values)

def workload_get_all_by_project(context, project_id):
    """Get all workloads belonging to a project."""
    return IMPL.workload_get_all_by_project(context, project_id)

def workload_update(context, workload_id, values):
    """
    Set the given properties on a workload  and update it.
    Raises NotFound if workload  does not exist.
    """
    return IMPL.workload_update(context, workload_id, values)

def workload_destroy(context, workload_id):
    """Destroy the workload or raise if it does not exist."""
    return IMPL.workload_destroy(context, workload_id)

def workload_vms_create(context, values):
    return IMPL.workload_vms_create(context, values)

def workload_vms_get(context, workload_id, session=None):
    return IMPL.workload_vms_get(context, workload_id, session)

def workload_vms_destroy(context, vm_id, workload_id):
    return IMPL.workload_vms_destroy(context, vm_id, workload_id)
    
def scheduledjob_create(context, scheduledjob):
    return IMPL.scheduledjob_create(context, scheduledjob)

def scheduledjob_delete(context, scheduledjob):
    return IMPL.scheduledjob_delete(context, scheduledjob)

def scheduledjob_get(context):
    return IMPL.scheduledjob_get(context)

def scheduledjob_update(context, scheduledjob):
    return IMPL.scheduledjob_update(context, scheduledjob)

def snapshot_create(context, values):
    return IMPL.snapshot_create(context, values)

def snapshot_get(context, snapshot_id, session=None):
    return IMPL.snapshot_get(context, snapshot_id, session)
    
def snapshot_get_all(context, workload_id=None):
    return IMPL.snapshot_get_all(context, workload_id)    

def snapshot_get_all_by_project(context, project_id):
    """Get all snapshots belonging to a project."""
    return IMPL.snapshot_get_all_by_project(context, project_id)
    
def snapshot_get_all_by_project_workload(context, project_id, workload_id):
    """Get all snapshots belonging to a project and workload"""
    return IMPL.snapshot_get_all_by_project_workload(context, project_id, workload_id)
    
def snapshot_show(context, snapshot_id):
    """Get more details of the  snapshot or raise if it does not exist."""
    return IMPL.snapshot_show(context, snapshot_id)

def snapshot_update(context, snapshot_id, values):
    return IMPL.snapshot_update(context, snapshot_id, values)

def snapshot_vm_create(context, values):
    return IMPL.snapshot_vm_create(context, values)

def snapshot_vm_get(context, snapshot_id, session=None):
    return IMPL.snapshot_vm_get(context, snapshot_id, session)

def snapshot_vm_destroy(context, vm_id, snapshot_id):
    return IMPL.snapshot_vm_destroy(context, vm_id, snapshot_id)

def vm_recent_snapshot_create(context, values):
    return IMPL.vm_recent_snapshot_create(context, values)

def vm_recent_snapshot_get(context, vm_id, session=None):
    return IMPL.vm_recent_snapshot_get(context, vm_id, session)

def vm_recent_snapshot_update(context, vm_id, values):
    return IMPL.vm_recent_snapshot_update(context, vm_id, values)

def vm_recent_snapshot_destroy(context, vm_id):
    return IMPL.vm_recent_snapshot_destroy(context, vm_id)

def snapshot_vm_resource_create(context, values):
    return IMPL.snapshot_vm_resource_create(context, values)

def snapshot_vm_resources_get(context, vm_id, snapshot_id, session=None):
    return IMPL.snapshot_vm_resources_get(context, vm_id, snapshot_id, session)

def snapshot_vm_resource_get_by_resource_name(context, vm_id, snapshot_id, resource_name, session=None):
    return IMPL.snapshot_vm_resource_get_by_resource_name(context, vm_id, snapshot_id, resource_name, session)

def snapshot_vm_resource_get(context, id, session=None):
    return IMPL.snapshot_vm_resource_get(context, id, session)

def snapshot_vm_resource_destroy(context, id, vm_id, snapshot_id):
    return IMPL.snapshot_vm_resource_destroy(context, id, vm_id, snapshot_id)
    
def vm_disk_resource_snap_create(context, values):
    return IMPL.vm_disk_resource_snap_create(context, values)

def vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, session=None):
    return IMPL.vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, session)

def vm_disk_resource_snap_get_top(context, snapshot_vm_resource_id, session=None):
    return IMPL.vm_disk_resource_snap_get_top(context, snapshot_vm_resource_id, session)

def vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session=None):
    return IMPL.vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session)

def vm_disk_resource_snaps_destroy(context, snapshot_vm_resource_id):
    return IMPL.vm_disk_resource_snaps_destroy(context, snapshot_vm_resource_id)

def vm_network_resource_snap_create(context, values):
    return IMPL.vm_network_resource_snap_create(context, values)

def vm_network_resource_snaps_get(context, snapshot_vm_resource_id, session=None):
    return IMPL.vm_network_resource_snaps_get(context, snapshot_vm_resource_id, session)

def vm_network_resource_snap_get(context, snapshot_vm_resource_id, session=None):
    return IMPL.vm_network_resource_snap_get(context, snapshot_vm_resource_id, session)

def vm_network_resource_snaps_destroy(context, snapshot_vm_resource_id):
    return IMPL.vm_network_resource_snaps_destroy(context, snapshot_vm_resource_id)
    