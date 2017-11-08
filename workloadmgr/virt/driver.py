# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Driver base-classes:
    (Beginning of) the contract that compute drivers must follow, and shared
    types that support that contract
"""

import sys

from oslo_config import cfg

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import log as logging
from workloadmgr import utils
from workloadmgr.virt import event as virtevent

driver_opts = [
    cfg.StrOpt(
        'compute_driver',
        help='Driver to use for controlling workload snapshots. Options '
        'include: libvirt.LibvirtDriver for the initial version '),
]

CONF = cfg.CONF
CONF.register_opts(driver_opts)
LOG = logging.getLogger(__name__)


def driver_dict_from_config(named_driver_config, *args, **kwargs):
    driver_registry = dict()

    for driver_str in named_driver_config:
        driver_type, _sep, driver = driver_str.partition('=')
        driver_class = importutils.import_class(driver)
        driver_registry[driver_type] = driver_class(*args, **kwargs)

    return driver_registry


def block_device_info_get_root(block_device_info):
    block_device_info = block_device_info or {}
    return block_device_info.get('root_device_name')


def block_device_info_get_mapping(block_device_info):
    block_device_info = block_device_info or {}
    block_device_mapping = block_device_info.get('block_device_mapping') or []
    return block_device_mappingget_info


class ComputeDriver(object):
    """
    Base class for compute drivers.
    """

    capabilities = {
        "live_snapshot": False,
    }

    def __init__(self, virtapi):
        self.virtapi = virtapi
        self._compute_event_callback = None

    def init_host(self, host):
        """
        Initialize anything that is necessary for the driver to function,
        """
        raise NotImplementedError()

    def get_info(self, instance):
        """
        Get the current status of an instance, by name (not ID!)
        """
        raise NotImplementedError()

    def get_num_instances(self):
        """
        Return the total number of virtual machines.
        """
        return NotImplementedError()

    def instance_exists(self, instance_id):
        """
        Checks existence of an instance on the host.
        """
        return NotImplementedError()

    def list_instances(self):
        """
        Return the names of all the instances known to the virtualization
        layer, as a list.
        """
        raise NotImplementedError()

    def list_instance_uuids(self):
        """
        Return the UUIDS of all the instances known to the virtualization
        layer, as a list.
        """
        raise NotImplementedError()

    def get_host_ip_addr(self):
        """
        Retrieves the IP address of the dom0
        """
        raise NotImplementedError()

    def emit_event(self, event):
        """
        Dispatches an event to the compute manager.

        Invokes the event callback registered by the
        workloadmgr manager to dispatch the event. This
        must only be invoked from a green thread.
        """
        # TODO(gbasava):Implementation
        return

    def get_vcenter_info(self):
        """
        Discovers the datacenters, hosts, virtual machines, datastores and networks of a vCenter
        """
        raise NotImplementedError()


def load_compute_driver(virtapi, compute_driver=None):
    """Load a compute driver module.

    Load the compute driver module specified by the compute_driver
    configuration option or, if supplied, the driver name supplied as an
    argument.

    Compute drivers constructors take a VirtAPI object as their first object
    and this must be supplied.

    :param virtapi: a VirtAPI instance
    :param compute_driver: a compute driver name to override the config opt
    :returns: a ComputeDriver instance
    """
    if not compute_driver:
        compute_driver = CONF.compute_driver

    if not compute_driver:
        LOG.error(_("Compute driver option required, but not specified"))
        sys.exit(1)

    LOG.info(_("Loading compute driver '%s'") % compute_driver)
    try:
        driver = importutils.import_object_ns('workloadmgr.virt',
                                              compute_driver,
                                              virtapi)
        return utils.check_isinstance(driver, ComputeDriver)
    except ImportError as e:
        LOG.error(_("Unable to load the virtualization driver: %s") % (e))
        sys.exit(1)


def compute_driver_matches(match):
    return CONF.compute_driver.endswith(match)


def pre_snapshot_vm(self, cntx, db, instance, snapshot):
    raise NotImplementedError()


def freeze_vm(self, cntx, db, instance, snapshot):
    raise NotImplementedError()


def thaw_vm(self, cntx, db, instance, snapshot):
    raise NotImplementedError()


def enable_cbt(self, cntx, db, instance):
    raise NotImplementedError()


def snapshot_vm(self, cntx, db, instance, snapshot):
    raise NotImplementedError()


def get_snapshot_data_size(self, cntx, db, instance, snapshot, snapshot_data):
    raise NotImplementedError()


def upload_snapshot(self, cntx, db, instance, snapshot, snapshot_data_ex):
    raise NotImplementedError()


def post_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_data):
    raise NotImplementedError()


def restore_vm(self, cntx, db, instance, restore, restored_net_resources,
               restored_compute_flavor, restored_nics, instance_options):
    raise NotImplementedError()


def mount_instance_root_device(self, cntx, db, instance, restore):
    raise NotImplementedError()


def umount_instance_root_device(self, process):
    raise NotImplementedError()


def snapshot_mount(self, cntx, snapshot):
    raise NotImplementedError()


def snapshot_dismount(self, cntx, snapshot):
    raise NotImplementedError()
