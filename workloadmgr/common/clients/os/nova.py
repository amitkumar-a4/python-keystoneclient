# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


import collections
import email
from email.mime import multipart
from email.mime import text
import os
import pkgutil
import string

from novaclient import shell as novashell
from novaclient import client as nc
from novaclient import exceptions
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
from retrying import retry
import six
from six.moves.urllib import parse as urlparse

from workloadmgr import exception
from workloadmgr.common.i18n import _
from workloadmgr.common.i18n import _LI
from workloadmgr.common.i18n import _LW
from workloadmgr.common.clients import client_plugin
from workloadmgr.common.clients import os as os_client

LOG = logging.getLogger(__name__)

client_retry_limit = 2
max_interface_check_attempts = 2

NOVACLIENT_VERSION = "2"
CLIENT_NAME = 'nova'


class NovaClientPlugin(client_plugin.ClientPlugin):

    deferred_server_statuses = ['BUILD',
                                'HARD_REBOOT',
                                'PASSWORD',
                                'REBOOT',
                                'RESCUE',
                                'RESIZE',
                                'REVERT_RESIZE',
                                'SHUTOFF',
                                'SUSPENDED',
                                'VERIFY_RESIZE']

    exceptions_module = exceptions

    service_types = [COMPUTE] = ['compute']

    def _create(self):
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        management_url = self.url_for(service_type=self.COMPUTE,
                                      endpoint_type=endpoint_type)

        management_url = management_url.replace("v2.1", "v2")
        computeshell = novashell.OpenStackComputeShell()
        extensions = computeshell._discover_extensions(NOVACLIENT_VERSION)

        args = {
            'project_id': self.context.tenant_id,
            'auth_url': self.context.auth_url,
            'auth_token': self.auth_token,
            'service_type': self.COMPUTE,
            'username': None,
            'api_key': None,
            'extensions': extensions,
            'endpoint_type': endpoint_type,
            'http_log_debug': self._get_client_option(CLIENT_NAME,
                                                      'http_log_debug'),
            'cacert': self._get_client_option(CLIENT_NAME, 'ca_file'),
            'insecure': self._get_client_option(CLIENT_NAME, 'insecure')
        }

        client = nc.Client(NOVACLIENT_VERSION, **args)

        client.client.set_management_url(management_url)

        return client

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.OverLimit)

    def is_bad_request(self, ex):
        return isinstance(ex, exceptions.BadRequest)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)

    def is_unprocessable_entity(self, ex):
        http_status = (getattr(ex, 'http_status', None) or
                       getattr(ex, 'code', None))
        return (isinstance(ex, exceptions.ClientException) and
                http_status == 422)

    def _list_extensions(self):
        extensions = self.client().list_extensions.show_all()
        return set(extension.alias for extension in extensions)

    def has_extension(self, alias):
        """Check if specific extension is present."""
        return alias in self._list_extensions()
