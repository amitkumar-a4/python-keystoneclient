# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Base class for classes that need modular database access."""

try:
   from oslo_config import cfg
except ImportError:
   from oslo.config import cfg

from workloadmgr import flags
from workloadmgr.openstack.common import importutils

db_driver_opt = cfg.StrOpt('db_driver',
                           default='workloadmgr.db',
                           help='driver to use for database access')

FLAGS = flags.FLAGS
FLAGS.register_opt(db_driver_opt)


class Base(object):
    """DB driver is injected in the init method."""

    def __init__(self, db_driver=None):
        if not db_driver:
            db_driver = FLAGS.db_driver
        self.db = importutils.import_module(db_driver)  # pylint: disable=C0103
