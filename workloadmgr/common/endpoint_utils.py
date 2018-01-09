# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


from keystoneclient import discover as ks_discover
from oslo_config import cfg
from oslo_utils import importutils
from clients import client_plugin


def get_auth_uri(v3=True):
    # Look for the keystone auth_uri in the configuration. First we
    # check the [clients_keystone] section, and if it is not set we
    # look in [keystone_authtoken]
    if cfg.CONF.clients_keystone.auth_uri:
        discover = ks_discover.Discover(
            auth_url=cfg.CONF.clients_keystone.auth_uri,
            cacert=client_plugin._get_client_option('keystone', 'ca_file'),
            insecure=client_plugin._get_client_option('keystone', 'insecure'),
            cert=client_plugin._get_client_option('keystone', 'cert_file'),
            key=client_plugin._get_client_option('keystone', 'key_file'))
        return discover.url_for('3.0')
    else:
        # Import auth_token to have keystone_authtoken settings setup.
        try:
            importutils.import_module('keystonemiddleware.auth_token')
        except BaseException:
            pass
        auth_uri = cfg.CONF.keystone_authtoken.auth_uri
        return auth_uri.replace('v2.0', 'v3') if auth_uri and v3 else auth_uri
