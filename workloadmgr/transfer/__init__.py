# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


from oslo_config import cfg
from oslo_utils import importutils

CONF = cfg.CONF

transfer_opts = [
    cfg.StrOpt('transfer_api_class',
               default='workloadmgr.transfer.api.API',
               help='The full class name of the volume transfer API class'),
]

CONF.register_opts(transfer_opts)

API = importutils.import_class(CONF.transfer_api_class)
