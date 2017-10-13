# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement VMWare Cloud
specific flows
"""

import cPickle as pickle

import eventlet
from eventlet import pools
from eventlet import debug

from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog
from workloadmgr.virt import driver
from workloadmgr.vault import vault
from workloadmgr import utils

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)


def create_virtdriver():
    return driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')


vmwaresessionpool = pools.Pool(max_size=32)
vmwaresessionpool.create = create_virtdriver

print debug.hub_listener_stacks(state=True)


@autolog.log_method(Logger, 'vmtasks_openstack.apply_retention_policy')
def apply_retention_policy(cntx, db, instances, snapshot):
    with vmwaresessionpool.item() as vmsession:
        return vmsession.apply_retention_policy(cntx, db, instances, snapshot)


@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_networks')
def snapshot_vm_networks(cntx, db, instances, snapshot):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_flavors')
def snapshot_vm_flavors(cntx, db, instances, snapshot):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm_security_groups')
def snapshot_vm_security_groups(cntx, db, instances, snapshot):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.pause_vm')
def pause_vm(cntx, db, instance):
    return suspend_vm(cntx, db, instance)


@autolog.log_method(Logger, 'vmtasks_vcloud.unpause_vm')
def unpause_vm(cntx, db, instance):
    return resume_vm(cntx, db, instance)


@autolog.log_method(Logger, 'vmtasks_vcloud.suspend_vm')
def suspend_vm(cntx, db, instance):
    with vmwaresessionpool.item() as vmsession:
        retval = vmsession.suspend(cntx, db, instance)
        print debug.format_hub_listeners()
        return retval


@autolog.log_method(Logger, 'vmtasks_vcloud.resume_vm')
def resume_vm(cntx, db, instance):
    with vmwaresessionpool.item() as vmsession:
        return vmsession.resume(cntx, db, instance)


@autolog.log_method(Logger, 'vmtasks_vcloud.pre_snapshot_vm')
def pre_snapshot_vm(cntx, db, instance, snapshot):
    print debug.format_hub_listeners()
    with vmwaresessionpool.item() as vmsession:
        retval = vmsession.pre_snapshot_vm(cntx, db, instance, snapshot)
        print debug.format_hub_listeners()
        return retval


@autolog.log_method(Logger, 'vmtasks_vcloud.freeze_vm')
def freeze_vm(cntx, db, instance, snapshot):
    pass


@autolog.log_method(Logger, 'vmtasks_vcloud.thaw_vm')
def thaw_vm(cntx, db, instance, snapshot):
    pass


@autolog.log_method(Logger, 'vmtasks_vcloud.snapshot_vm')
def snapshot_vm(cntx, db, instance, snapshot):
    print debug.format_hub_listeners()
    with vmwaresessionpool.item() as vmsession:
        retval = vmsession.snapshot_vm(cntx, db, instance, snapshot)
        print debug.format_hub_listeners()
        return retval


@autolog.log_method(Logger, 'vmtasks_vcloud.get_snapshot_data_size')
def get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data):
    LOG.debug(_("instance: %(instance_id)s") %
              {'instance_id': instance['vm_id'], })
    vm_data_size = 0

    with vmwaresessionpool.item() as vmsession:
        vm_data_size = vmsession.get_snapshot_data_size(
            cntx, db, instance, snapshot, snapshot_data)
        LOG.debug(_("vm_data_size: %(vm_data_size)s") %
                  {'vm_data_size': vm_data_size, })
        return vm_data_size


@autolog.log_method(Logger, 'vmtasks_vcloud.upload_snapshot')
def upload_snapshot(cntx, db, instance, snapshot, snapshot_data_ex):
    with vmwaresessionpool.item() as vmsession:
        vmsession.upload_snapshot(
            cntx, db, instance, snapshot, snapshot_data_ex)


@autolog.log_method(Logger, 'vmtasks_vcloud.post_snapshot')
def post_snapshot(cntx, db, instance, snapshot, snapshot_data):
    with vmwaresessionpool.item() as vmsession:
        vmsession.post_snapshot_vm(cntx, db, instance, snapshot, snapshot_data)
        print debug.format_hub_listeners()


@autolog.log_method(Logger, 'vmtasks_vcloud.delete_restored_vm')
def delete_restored_vm(cntx, db, instance, restore):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm_flavor')
def restore_vm_flavor(cntx, db, instance, restore):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm_security_groups')
def restore_vm_security_groups(cntx, db, restore):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm_security_groups')
def delete_vm_security_groups(cntx, security_groups):
    pass


@autolog.log_method(Logger, 'vmtasks_vcloud.get_vm_nics')
def get_vm_nics(cntx, db, instance, restore, restored_net_resources):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.get_vm_restore_data_size')
def get_vm_restore_data_size(cntx, db, instance, restore):
    instance_size = 0
    snapshot_vm_resources = db.snapshot_vm_resources_get(
        cntx, instance['vm_id'], restore['snapshot_id'])
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(
            cntx, snapshot_vm_resource.id)
        instance_size = instance_size + vm_disk_resource_snap.size
        while vm_disk_resource_snap.vm_disk_resource_snap_backing_id is not None:
            vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(
                cntx, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            instance_size = instance_size + vm_disk_resource_snap_backing.size
            vm_disk_resource_snap = vm_disk_resource_snap_backing

    return instance_size


@autolog.log_method(Logger, 'vmtasks_vcloud.get_restore_data_size')
def get_restore_data_size(cntx, db, restore):
    restore_size = 0
    restore_options = pickle.loads(restore['pickle'].encode('ascii', 'ignore'))
    for vm in db.snapshot_vms_get(cntx, restore['snapshot_id']):
        instance_options = utils.get_instance_restore_options(
            restore_options, vm.vm_id, restore_options['type'])
        if instance_options and instance_options.get('include', True) == False:
            continue
        #restore_size = restore_size + get_vm_restore_data_size(cntx, db, {'vm_id' : vm.vm_id}, restore)
        restore_size = restore_size + vm.restore_size

    return restore_size


@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm_networks')
def restore_vm_networks(cntx, db, restore):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.delete_vm_networks')
def delete_vm_networks(cntx, net_resources):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.pre_restore_vm')
def pre_restore_vm(cntx, db, instance, restore):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.restore_vm')
def restore_vm(cntx, db, instance, restore,
               restored_net_resources, restored_security_groups):

    # restore_vm_flavor(cntx, db, instance,restore)
    restored_compute_flavor = None
    # get_vm_nics( cntx, db, instance, restore, restored_net_resources)
    restored_nics = None

    restore_obj = db.restore_get(cntx, restore['id'])
    restore_options = pickle.loads(str(restore_obj.pickle))
    instance_options = utils.get_instance_restore_options(
        restore_options, instance['vm_id'], 'vmware')

    #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
    with vmwaresessionpool.item() as vmsession:
        return vmsession.restore_vm(cntx, db, instance, restore,
                                    restored_net_resources,
                                    restored_security_groups,
                                    restored_compute_flavor,
                                    restored_nics,
                                    instance_options)
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.poweron_vm')
def poweron_vm(cntx, instance, restore, restored_instance):
    with vmwaresessionpool.item() as vmsession:
        return vmsession.poweron_vm(cntx, instance, restore, restored_instance)


@autolog.log_method(Logger, 'vmtasks_vcloud.set_vm_metadata')
def set_vm_metadata(cntx, instance, restore, restored_instance):
    pass


@autolog.log_method(Logger, 'vmtasks_vcloud.post_restore_vm')
def post_restore_vm(cntx, db, instance, restore):
    return None


@autolog.log_method(Logger, 'vmtasks_vcloud.mount_instance_root_device')
def mount_instance_root_device(cntx, instance, restore):
    with vmwaresessionpool.item() as vmsession:
        return vmsession.mount_instance_root_device(cntx, instance, restore)


@autolog.log_method(Logger, 'vmtasks_vcloud.umount_instance_root_device')
def umount_instance_root_device(process):
    with vmwaresessionpool.item() as vmsession:
        return vmsession.umount_instance_root_device(process)
