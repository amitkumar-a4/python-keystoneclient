# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


from ceilometerclient import client as cc
from ceilometerclient import exc
from ceilometerclient.openstack.common.apiclient import exceptions as api_exc

from workloadmgr.common.clients import client_plugin

CLIENT_NAME = 'ceilometer'


class CeilometerClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = [exc, api_exc]

    service_types = [METERING, ALARMING] = ['metering', 'alarming']

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        endpoint = self.url_for(service_type=self.METERING,
                                endpoint_type=endpoint_type)
        aodh_endpoint = self.url_for(service_type=self.ALARMING,
                                     endpoint_type=endpoint_type)
        args = {
            'auth_url': con.auth_url,
            'service_type': self.METERING,
            'project_name': con.tenant,
            'token': lambda: self.auth_token,
            'user_domain_id': con.user_domain,
            'project_domain_id': con.project_domain,
            'endpoint_type': endpoint_type,
            'os_endpoint': endpoint,
            'cacert': self._get_client_option(CLIENT_NAME, 'ca_file'),
            'cert_file': self._get_client_option(CLIENT_NAME, 'cert_file'),
            'key_file': self._get_client_option(CLIENT_NAME, 'key_file'),
            'insecure': self._get_client_option(CLIENT_NAME, 'insecure'),
            'aodh_endpoint': aodh_endpoint
        }

        return cc.get_client('2', **args)

    def is_not_found(self, ex):
        return isinstance(ex, (exc.HTTPNotFound, api_exc.NotFound))

    def is_over_limit(self, ex):
        return isinstance(ex, exc.HTTPOverLimit)

    def is_conflict(self, ex):
        return isinstance(ex, exc.HTTPConflict)
