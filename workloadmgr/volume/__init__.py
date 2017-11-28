# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

try:
   from oslo_config import cfg
except ImportError:
   from oslo.config import cfg

# Importing full names to not pollute the namespace and cause possible
# collisions with use of 'from workloadmgr.volume import <foo>' elsewhere.
import workloadmgr.openstack.common.importutils

_volume_opts = [
    cfg.StrOpt('volume_api_class',
                           default='workloadmgr.volume.cinder.API',
                           help='The full class name of the '
                           'volume API class to use'),
]

cfg.CONF.register_opts(_volume_opts)


def API():
    importutils = workloadmgr.openstack.common.importutils
    volume_api_class = cfg.CONF.volume_api_class
    cls = importutils.import_class(volume_api_class)
    return cls()
