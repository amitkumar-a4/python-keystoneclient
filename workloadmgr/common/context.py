# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from keystoneclient import access
from keystoneclient import auth
from keystoneclient.auth.identity import access as access_plugin
from keystoneclient.auth.identity import v3
from keystoneclient.auth import token_endpoint
from oslo_config import cfg
from oslo_context import context
from oslo_log import log as logging
import oslo_messaging
from oslo_middleware import request_id as oslo_request_id
from oslo_utils import importutils
import six

from workloadmgr.common import endpoint_utils
from workloadmgr import exception
from workloadmgr.common.i18n import _LE, _LW
from workloadmgr.common import policy
from workloadmgr.db import api as db_api
from workloadmgr.common import clients

LOG = logging.getLogger(__name__)


# Note, we yield the options via list_opts to enable generation of the
# sample workloadmgr.conf, but we don't register these options directly via
# cfg.CONF.register*, it's done via auth.register_conf_options
# Note, only auth_plugin = v3password is expected to work, example config:
# [trustee]
# auth_plugin = password
# auth_url = http://192.168.1.2:35357
# username = triliovault
# password = password
# user_domain_id = default
V3_PASSWORD_PLUGIN = 'v3password'
TRUSTEE_CONF_GROUP = 'trustee'
auth.register_conf_options(cfg.CONF, TRUSTEE_CONF_GROUP)


def list_opts():
    trustee_opts = auth.conf.get_common_conf_options()
    trustee_opts.extend(auth.conf.get_plugin_options(V3_PASSWORD_PLUGIN))
    yield TRUSTEE_CONF_GROUP, trustee_opts


class RequestContext(context.RequestContext):
    """Stores information about the security context.

    Under the security context the user accesses the system, as well as
    additional request information.
    """

    def __init__(self, auth_token=None, username=None, password=None,
                 tenant=None, user_id=None, project_id=None,
                 tenant_id=None, auth_url=None, roles=None, is_admin=None,
                 read_only=False, show_deleted=False,
                 overwrite=True, trust_id=None, trustor_user_id=None,
                 request_id=None, auth_token_info=None, region_name=None,
                 auth_plugin=None, trusts_auth_plugin=None,
                 user_domain_id=None, project_domain_id=None,
                 remote_address=None, **kwargs):
        """Initialisation of the request context.

        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.

         :param kwargs: Extra arguments that might be present, but we ignore
            because they possibly came in from older rpc messages.
        """
        super(RequestContext, self).__init__(auth_token=auth_token,
                                             user=username, tenant=tenant,
                                             is_admin=is_admin,
                                             read_only=read_only,
                                             show_deleted=show_deleted,
                                             request_id=request_id,
                                             user_domain=user_domain_id,
                                             project_domain=project_domain_id)

        self.username = username
        self.user_id = user_id
        self.password = password
        self.region_name = region_name
        self.tenant_id = tenant_id or project_id
        self.project_id = tenant_id or project_id
        self.auth_token_info = auth_token_info
        self.auth_url = auth_url
        self.roles = roles or []
        self._session = None
        self._clients = None
        self.trust_id = trust_id
        self.trustor_user_id = trustor_user_id
        self.policy = policy.Enforcer()
        self._auth_plugin = auth_plugin
        self._trusts_auth_plugin = trusts_auth_plugin
        self.read_deleted = 'no'
        self.remote_address = remote_address

        if is_admin is None:
            self.is_admin = self.policy.check_is_admin(self)
        else:
            self.is_admin = is_admin

    @property
    def session(self):
        if self._session is None:
            self._session = db_api.get_session()
        return self._session

    @property
    def clients(self):
        if self._clients is None:
            self._clients = clients.Clients(self)
        return self._clients

    def to_dict(self):
        user_idt = '{user} {tenant}'.format(user=self.user_id or '-',
                                            tenant=self.tenant_id or '-')

        return {'auth_token': self.auth_token,
                'username': self.username,
                'user_id': self.user_id,
                'password': self.password,
                'tenant': self.tenant,
                'tenant_id': self.tenant_id,
                'project_id': self.tenant_id,
                'trust_id': self.trust_id,
                'trustor_user_id': self.trustor_user_id,
                'auth_token_info': self.auth_token_info,
                'auth_url': self.auth_url,
                'roles': self.roles,
                'is_admin': self.is_admin,
                'user': self.user,
                'request_id': self.request_id,
                'show_deleted': self.show_deleted,
                'region_name': self.region_name,
                'user_identity': user_idt,
                'user_domain_id': self.user_domain,
                'read_deleted': self.read_deleted,
                'project_domain_id': self.project_domain}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    @property
    def keystone_v3_endpoint(self):
        if self.auth_url:
            return self.auth_url.replace('v2.0', 'v3')
        else:
            auth_uri = endpoint_utils.get_auth_uri()
            if auth_uri:
                return auth_uri
            else:
                LOG.error('Keystone API endpoint not provided. Set '
                          'auth_uri in section [clients_keystone] '
                          'of the configuration file.')
                raise exception.AuthorizationFailure()

    @property
    def trusts_auth_plugin(self):
        if self._trusts_auth_plugin:
            return self._trusts_auth_plugin

        self._trusts_auth_plugin = auth.load_from_conf_options(
            cfg.CONF, TRUSTEE_CONF_GROUP, trust_id=self.trust_id)

        if self._trusts_auth_plugin:
            return self._trusts_auth_plugin

        try:
            cfg.CONF.import_group('keystone_authtoken',
                                  'keystonemiddleware.auth_token')
        except BaseException:
            pass

        trustee_user_domain = 'default'
        if 'triliovault_user_domain_id' in cfg.CONF:
            trustee_user_domain = cfg.CONF.triliovault_user_domain_id

        if 'user_domain_id' in cfg.CONF.keystone_authtoken:
            trustee_user_domain = cfg.CONF.keystone_authtoken.user_domain_id

        self._trusts_auth_plugin = v3.Password(
            username=cfg.CONF.keystone_authtoken.admin_user,
            password=cfg.CONF.keystone_authtoken.admin_password,
            user_domain_id=trustee_user_domain,
            auth_url=self.keystone_v3_endpoint,
            trust_id=self.trust_id)
        return self._trusts_auth_plugin

    def _create_auth_plugin(self):
        if self.auth_token_info:
            auth_ref = access.AccessInfo.factory(body=self.auth_token_info,
                                                 auth_token=self.auth_token)
            return access_plugin.AccessInfoPlugin(
                auth_url=self.keystone_v3_endpoint,
                auth_ref=auth_ref)

        if self.auth_token:
            # FIXME(jamielennox): This is broken but consistent. If you
            # only have a token but don't load a service catalog then
            # url_for wont work. Stub with the keystone endpoint so at
            # least it might be right.
            return token_endpoint.Token(endpoint=self.keystone_v3_endpoint,
                                        token=self.auth_token)

        if self.password:
            return v3.Password(username=self.username,
                               password=self.password,
                               project_id=self.tenant_id,
                               user_domain_id=self.user_domain,
                               auth_url=self.keystone_v3_endpoint)

        LOG.error(_LE("Keystone v3 API connection failed, no password "
                      "trust or auth_token!"))
        raise exception.AuthorizationFailure()

    def reload_auth_plugin(self):
        self._auth_plugin = None

    @property
    def auth_plugin(self):
        if not self._auth_plugin:
            if self.trust_id:
                self._auth_plugin = self.trusts_auth_plugin
            else:
                self._auth_plugin = self._create_auth_plugin()

        return self._auth_plugin


def get_admin_context(show_deleted=False):
    return RequestContext(is_admin=True, show_deleted=show_deleted)
