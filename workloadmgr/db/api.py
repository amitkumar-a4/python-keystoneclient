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


def service_delete(context, service_id):
    """Destroy the service or raise if it does not exist."""
    return IMPL.service_delete(context, service_id)

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
def workload_type_create(context, values):
    return IMPL.workload_type_create(context, values)

def workload_type_update(context, id, values, purge_metadata=False):
    return IMPL.workload_type_update(context, id, values, purge_metadata)

def workload_types_get(context):
    return IMPL.workload_types_get(context)

def workload_type_get(context, id):
    return IMPL.workload_type_get(context, id)

def workload_type_delete(context, id):
    return IMPL.workload_type_delete(context, id)

def workload_get(context, workload_id):
    """Get a workload or raise if it does not exist."""
    return IMPL.workload_get(context, workload_id)

def workload_show(context, workload_id):
    """Get more details of the  workload or raise if it does not exist."""
    return IMPL.workload_show(context, workload_id)

def workload_get_all(context, **kwargs):
    """Get all workloads."""
    return IMPL.workload_get_all(context, **kwargs)

def workload_get_all_by_host(context, host):
    """Get all workloads belonging to a host."""
    return IMPL.workload_get_all_by_host(context, host)

def workload_create(context, values):
    """Create a workload from the values dictionary."""
    return IMPL.workload_create(context, values)

def workload_get_all_by_project(context, project_id):
    """Get all workloads belonging to a project."""
    return IMPL.workload_get_all_by_project(context, project_id)

def workload_update(context, workload_id, values, purge_metadata=False):
    """
    Set the given properties on a workload  and update it.
    Raises NotFound if workload  does not exist.
    """
    return IMPL.workload_update(context, workload_id, values, purge_metadata)

def workload_delete(context, workload_id):
    """Destroy the workload or raise if it does not exist."""
    return IMPL.workload_delete(context, workload_id)

def workload_vms_create(context, values):
    return IMPL.workload_vms_create(context, values)

def workload_vms_get(context, workload_id, **kwargs):
    return IMPL.workload_vms_get(context, workload_id, **kwargs)

def workload_vms_delete(context, vm_id, workload_id):
    return IMPL.workload_vms_delete(context, vm_id, workload_id)

def snapshot_mark_incomplete_as_error(context, host):
    return IMPL.snapshot_mark_incomplete_as_error(context, host)
    
def snapshot_create(context, values):
    return IMPL.snapshot_create(context, values)

def snapshot_type_time_size_update(context, snapshot_id):
    return IMPL.snapshot_type_time_size_update(context, snapshot_id)

def snapshot_delete(context, snapshot_id):
    """Destroy the snapshot or raise if it does not exist."""
    return IMPL.snapshot_delete(context, snapshot_id)

def snapshot_get(context, snapshot_id, **kwargs):
    return IMPL.snapshot_get(context, snapshot_id, **kwargs)
    
def snapshot_get_all(context, workload_id=None, **kwargs):
    return IMPL.snapshot_get_all(context, workload_id, **kwargs)    

def snapshot_get_all_by_project(context, project_id, **kwargs):
    """Get all snapshots belonging to a project."""
    return IMPL.snapshot_get_all_by_project(context, project_id, **kwargs)
    
def snapshot_get_all_by_project_workload(context, project_id, workload_id, **kwargs):
    """Get all snapshots belonging to a project and workload"""
    return IMPL.snapshot_get_all_by_project_workload(context, project_id, workload_id, **kwargs)
    
def snapshot_show(context, snapshot_id):
    """Get more details of the  snapshot or raise if it does not exist."""
    return IMPL.snapshot_show(context, snapshot_id)

def snapshot_update(context, snapshot_id, values):
    return IMPL.snapshot_update(context, snapshot_id, values)

def snapshot_vm_create(context, values):
    return IMPL.snapshot_vm_create(context, values)

def snapshot_vms_get(context, snapshot_id, **kwargs):
    return IMPL.snapshot_vms_get(context, snapshot_id, **kwargs)

def snapshot_vm_get(context, vm_id, snapshot_id):
    return IMPL.snapshot_vm_get(context, vm_id, snapshot_id)

def snapshot_vm_update(context, vm_id, snapshot_id, values):
    return IMPL.snapshot_vm_update(context, vm_id, snapshot_id, values)

def snapshot_vm_delete(context, vm_id, snapshot_id):
    return IMPL.snapshot_vm_delete(context, vm_id, snapshot_id)

def vm_recent_snapshot_create(context, values):
    return IMPL.vm_recent_snapshot_create(context, values)

def vm_recent_snapshot_get(context, vm_id, **kwargs):
    return IMPL.vm_recent_snapshot_get(context, vm_id, **kwargs)

def vm_recent_snapshot_update(context, vm_id, values):
    return IMPL.vm_recent_snapshot_update(context, vm_id, values)

def vm_recent_snapshot_delete(context, vm_id):
    return IMPL.vm_recent_snapshot_delete(context, vm_id)

def snapshot_vm_resource_create(context, values):
    return IMPL.snapshot_vm_resource_create(context, values)

def snapshot_vm_resource_update(context, id, vaules, purge_metadata=False):
    return IMPL.snapshot_vm_resource_update(context, id, vaules, purge_metadata)

def snapshot_vm_resources_get(context, vm_id, snapshot_id):
    return IMPL.snapshot_vm_resources_get(context, vm_id, snapshot_id)

def snapshot_resources_get(context, snapshot_id, **kwargs):
    return IMPL.snapshot_resources_get(context, snapshot_id, **kwargs)

def snapshot_vm_resource_get_by_resource_pit_id(context, vm_id, snapshot_id, resource_pit_id):
    return IMPL.snapshot_vm_resource_get_by_resource_pit_id(context, vm_id, snapshot_id, resource_pit_id)

def snapshot_vm_resource_get_by_resource_name(context, vm_id, snapshot_id, resource_name):
    return IMPL.snapshot_vm_resource_get_by_resource_name(context, vm_id, snapshot_id, resource_name)

def snapshot_vm_resource_get(context, id):
    return IMPL.snapshot_vm_resource_get(context, id)

def snapshot_vm_resource_delete(context, id):
    return IMPL.snapshot_vm_resource_delete(context, id)
    
def vm_disk_resource_snap_create(context, values):
    return IMPL.vm_disk_resource_snap_create(context, values)

def vm_disk_resource_snap_update(context, id, vaules, purge_metadata=False):
    return IMPL.vm_disk_resource_snap_update(context, id, vaules, purge_metadata)

def vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, **kwargs):
    return IMPL.vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, **kwargs)

def vm_disk_resource_snap_get_top(context, snapshot_vm_resource_id):
    return IMPL.vm_disk_resource_snap_get_top(context, snapshot_vm_resource_id)

def vm_disk_resource_snap_get(context, vm_disk_resource_snap_id):
    return IMPL.vm_disk_resource_snap_get(context, vm_disk_resource_snap_id)

def vm_disk_resource_snap_delete(context, vm_disk_resource_snap_id):
    return IMPL.vm_disk_resource_snap_delete(context, vm_disk_resource_snap_id)

def vm_network_resource_snap_create(context, values):
    return IMPL.vm_network_resource_snap_create(context, values)

def vm_network_resource_snap_update(context, id, vaules, purge_metadata=False):
    return IMPL.vm_network_resource_snap_update(context, id, vaules, purge_metadata)

def vm_network_resource_snaps_get(context, snapshot_vm_resource_id, **kwargs):
    return IMPL.vm_network_resource_snaps_get(context, snapshot_vm_resource_id, **kwargs)

def vm_network_resource_snap_get(context, snapshot_vm_resource_id):
    return IMPL.vm_network_resource_snap_get(context, snapshot_vm_resource_id)

def vm_network_resource_snap_delete(context, vm_network_resource_snap_id):
    return IMPL.vm_network_resource_snap_delete(context, vm_network_resource_snap_id)

def vm_security_group_rule_snap_create(context, values):
    return IMPL.vm_security_group_rule_snap_create(context, values)

def vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, vaules, purge_metadata=False):
    return IMPL.vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, vaules, purge_metadata)

def vm_security_group_rule_snaps_get(context, vm_security_group_snap_id, **kwargs):
    return IMPL.vm_security_group_rule_snaps_get(context, vm_security_group_snap_id, **kwargs)

def vm_security_group_rule_snap_get(context, id, vm_security_group_snap_id):
    return IMPL.vm_security_group_rule_snap_get(context, id, vm_security_group_snap_id)

def vm_security_group_rule_snap_delete(context, id, vm_security_group_rule_snap_id):
    return IMPL.vm_security_group_rule_snap_delete(context, id, vm_security_group_rule_snap_id)
    
def get_metadata_value(metadata, key, default=None):
    return IMPL.get_metadata_value(metadata, key, default=None)

def restore_mark_incomplete_as_error(context, host):
    return IMPL.restore_mark_incomplete_as_error(context, host)

def restore_get(context, restore_id):
    return IMPL.restore_get(context, restore_id)

def restore_get_all(context, **kwargs):
    return IMPL.restore_get_all(context, **kwargs)

def restore_get_all_by_project(context, project_id):
    return IMPL.restore_get_all_by_project(context, project_id)
        
def restore_get_all_by_project_snapshot(context, project_id, snapshot_id):
    return IMPL.restore_get_all_by_project_snapshot(context, project_id, snapshot_id)

def restore_show(context, restore_id):
    return IMPL.restore_show(context, restore_id)

def restore_create(context, values):
    return IMPL.restore_create(context, values)

def restore_update(context, restore_id, values):
    return IMPL.restore_update(context, restore_id, values)

def restore_delete(context, restore_id):
    return IMPL.restore_delete(context, restore_id)

def restored_vm_create(context, values):
    return IMPL.restored_vm_create(context, values)

def restored_vm_update(context, vm_id, restore_id, values):
    return IMPL.restored_vm_update(context, vm_id, restore_id, values)

def restored_vm_get(context, restore_id):
    return IMPL.restored_vm_get(context, restore_id)

def restored_vm_delete(context, vm_id, restore_id):
    return IMPL.restored_vm_delete(context, vm_id, restore_id)

def restored_vm_resource_metadata_create(context, values):
    return IMPL.restored_vm_resource_metadata_create(context, values)

def restored_vm_resource_metadata_delete(context, metadata_ref):
    return IMPL.restored_vm_resource_metadata_delete(context, metadata_ref)

def restored_vm_resource_create(context, values):
    return IMPL.restored_vm_resource_create(context, values)

def restored_vm_resource_update(context, restored_vm_resource_id, values, purge_metadata=False):
    return IMPL.restored_vm_resource_update(context, restored_vm_resource_id, values, purge_metadata)

def restored_vm_resources_get(context, vm_id, restore_id):
    return IMPL.restored_vm_resources_get(context, vm_id, restore_id)

def restored_vm_resource_get_by_resource_name(context, vm_id, restore_id, resource_name):
    return IMPL.restored_vm_resource_get_by_resource_name(context, vm_id, restore_id, resource_name)

def restored_vm_resource_get(context, id):
    return IMPL.restored_vm_resource_get(context, id)

def restored_vm_resource_delete(context, id, vm_id, restore_id):
    return IMPL.restored_vm_resource_delete(context, id, vm_id, restore_id)

def purge_snapshot(context, id):
    return IMPL.purge_snapshot(context, id)

def purge_workload(context, id):
    return IMPL.purge_workload(context, id)
