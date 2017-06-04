# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.
#

from oslo.config import cfg
import workloadmgr.vault.vault

CONF = cfg.CONF

def set_defaults(conf):
    conf.set_default('fake_rabbit', True)
    conf.set_default('rpc_backend', 'workloadmgr.openstack.common.rpc.impl_fake')
    conf.set_default('verbose', True)
    conf.set_default('connection', 'sqlite://', group='database')
    conf.set_default('sqlite_synchronous', False)
    conf.set_default('policy_file', 'workloadmgr/tests/unit/policy.json')
    conf.set_default('vault_storage_type', 'nfs')
    conf.set_default('vault_data_directory', '/tmp/triliovault-mounts')
