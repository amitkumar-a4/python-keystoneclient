# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

import os

from oslo.config import cfg
from workloadmgr import exception
from workloadmgr.openstack.common import log as logging
from workloadmgr.virt.libvirt import qemuimages

libvirt_opts = [

]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts)
LOG = logging.getLogger(__name__)


def get_instance_path(instance_id, relative=False):
    """Determine the correct path for instance storage.
    This method determines the directory name for instance storage
    :param instance: the instance we want a path for
    :param relative: if True, just the relative path is returned
    :returns: a path to store information about that instance
    """
    if relative:
        return instance_id
    return os.path.join(CONF.instances_path, instance_id)
