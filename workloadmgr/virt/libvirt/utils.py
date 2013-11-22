# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

import os

from oslo.config import cfg
from workloadmgr import exception
from workloadmgr.openstack.common import log as logging
from workloadmgr import utils
from workloadmgr.virt.libvirt import images

libvirt_opts = [

    ]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts)
LOG = logging.getLogger(__name__)


def get_disk_backing_file(path, basename=True):
    """Get the backing file of a disk image

    :param path: Path to the disk image
    :returns: a path to the image's backing store
    """
    backing_file = images.qemu_img_info(path).backing_file
    if backing_file and basename:
        backing_file = os.path.basename(backing_file)

    return backing_file

