# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


"""Keystone Client functionality for use by resources."""

import collections

from keystoneclient.auth.identity import v3 as kc_auth_v3
import keystoneclient.exceptions as kc_exception
from keystoneclient import session
from keystoneclient.v3 import client as kc_v3
from oslo_config import cfg
from oslo_log import log as logging
from keystoneauth1.identity.generic import password as passMod
from keystoneclient import client
from novaclient import client as novaclient

from workloadmgr.common import context
from workloadmgr import exception
from workloadmgr.common.i18n import _LE
from workloadmgr.common.i18n import _LW
#from workloadmgr.vault import vault
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB

LOG = logging.getLogger('workloadmgr.common.keystoneclient')

#AccessKey = collections.namedtuple('AccessKey', ['id', 'access', 'secret'])

_default_keystone_backend = "workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV3"

keystone_opts = [
    cfg.StrOpt('keystone_backend',
               default=_default_keystone_backend,
               help="Fully qualified class name to use as a keystone backend.")
]

cfg.CONF.register_opts(keystone_opts)
CONF = cfg.CONF

class KeystoneClientBase(object):
    """Wrap keystone client so we can encapsulate logic used in resources.
    Note this is intended to be initialized from a resource on a per-session
    basis, so the session context is passed in on initialization
    Also note that an instance of this is created in each request context as
    part of a lazy-loaded cloud backend and it can be easily referenced in
    each resource as ``self.keystone()``, so there should not be any need to
    directly instantiate instances of this class inside resources themselves.
    """

    def __init__(self, context):
        # If a trust_id is specified in the context, we immediately
        # authenticate so we can populate the context with a trust token
        # otherwise, we delay client authentication until needed to avoid
        # unnecessary calls to keystone.
        #
        # Note that when you obtain a token using a trust, it cannot be
        # used to reauthenticate and get another token, so we have to
        # get a new trust-token even if context.auth_token is set.
        #
        # - context.auth_url is expected to contain a versioned keystone
        #   path, we will work with either a v2.0 or v3 path
        self.context = context
        self._client = None
        self._client_instance = None
        self._nova_client = None
        self._admin_auth = None
        self._domain_admin_auth = None
        self._domain_admin_client = None

        self.session = session.Session.construct(self._ssl_options())
        try:
            self.v3_endpoint = self.context.keystone_v3_endpoint
        except:
                self.v3_endpoint = None

        try:
            if self.context.trust_id:
               # Create a client with the specified trust_id, this
               # populates self.context.auth_token with a trust-scoped token
               self._client = self._v3_client_init()
        except:
               self._client = self._v3_client_init()

    @property
    def client(self):
        if not self._client:
            # Create connection to v3 API
            self._client = self._v3_client_init()
        return self._client

    @property
    def client_instance(self):
        if not self._client_instance:
            # Create connection to API
            self._client_instance = self._common_client_init()
        return self._client_instance

    @property
    def nova_client(self):
        if not self._nova_client:
           self._nova_client = self._common_client_init(nova_client=True)
        return self._nova_client

    def _common_client_init(self, nova_client=False):
        try:
            username=CONF.get('keystone_authtoken').username 
        except:
               username=CONF.get('keystone_authtoken').admin_user
        try:
            password=CONF.get('keystone_authtoken').password 
        except:
               password=CONF.get('keystone_authtoken').admin_password
        try:
            tenant_name=CONF.get('keystone_authtoken').admin_tenant_name
        except:
               project_id = context.project_id
               context.project_id = 'Configurator'
               tenant_name=WorkloadMgrDB().db.setting_get(context, 'service_tenant_name', get_hidden=True).value
               context.project_id = project_id
        auth_url=CONF.keystone_endpoint_url
        if CONF.keystone_auth_version == '3':
           username=CONF.get('nova_admin_username')
           password=CONF.get('nova_admin_password')
           if username == 'triliovault':
              domain_id=CONF.get('triliovault_user_domain_id')
           else:
                domain_id=CONF.get('domain_name')

           cloud_admin_project = CONF.get('neutron_admin_tenant_name',None)
           if nova_client is True:
              auth = passMod.Password(auth_url=auth_url,
                                    username=username,
                                    password=password,
                                    user_domain_id=domain_id,
                                    project_name=cloud_admin_project,
                                    project_domain_id=domain_id,
                                    )
           else: 
                 auth = passMod.Password(auth_url=auth_url,
                                    username=username,
                                    password=password,
                                    user_domain_id=domain_id,
                                    domain_id=domain_id,
                                    )
        else:
             auth = passMod.Password(auth_url=auth_url,
                                    username=username,
                                    password=password,
                                    project_name=tenant_name,
                                    )
        sess = session.Session(auth=auth, verify=False)
        if nova_client is True:
           return novaclient.Client("2", session=sess)
        return client.Client(session=sess, auth_url=auth_url, insecure=True)

    def _v3_client_init(self):
        client = kc_v3.Client(session=self.session,
                              auth=self.context.auth_plugin)

        if hasattr(self.context.auth_plugin, 'get_access'):
            # NOTE(jamielennox): get_access returns the current token without
            # reauthenticating if it's present and valid.
            try:
                auth_ref = self.context.auth_plugin.get_access(self.session)
            except kc_exception.Unauthorized:
                LOG.error(_LE("Keystone client authentication failed"))
                raise exception.AuthorizationFailure()

            if self.context.trust_id:
                # Sanity check
                if not auth_ref.trust_scoped:
                    LOG.error(_LE("trust token re-scoping failed!"))
                    raise exception.AuthorizationFailure()
                # Sanity check that impersonation is effective
                if self.context.trustor_user_id != auth_ref.user_id:
                    LOG.error(_LE("Trust impersonation failed"))
                    raise exception.AuthorizationFailure()

        return client

    def _ssl_options(self):
        opts = {'cacert': cfg.CONF.keystone_authtoken.cafile,
                'insecure': cfg.CONF.keystone_authtoken.insecure,
                'cert': cfg.CONF.keystone_authtoken.certfile,
                'key': cfg.CONF.keystone_authtoken.keyfile}
        return opts

    def create_trust_context(self):
        """Create a trust using the trustor identity in the current context.
        The trust is created with the trustee as the heat service user.
        If the current context already contains a trust_id, we do nothing
        and return the current context.
        Returns a context containing the new trust_id.
        """
        if self.context.trust_id:
            return self.context

        # We need the service admin user ID (not name), as the trustor user
        # can't lookup the ID in keystoneclient unless they're admin
        # workaround this by getting the user_id from admin_client

        try:
            trustee_user_id = self.context.trusts_auth_plugin.get_user_id(
                self.session)
        except kc_exception.Unauthorized:
            LOG.error(_LE("Domain admin client authentication failed"))
            raise exception.AuthorizationFailure()

        trustor_user_id = self.context.trustor_user_id
        trustor_proj_id = self.context.tenant_id

        # inherit the roles of the trustor
        roles = self.context.roles

        try:
            trust = self.client.trusts.create(trustor_user=trustor_user_id,
                                              trustee_user=trustee_user_id,
                                              project=trustor_proj_id,
                                              impersonation=True,
                                              role_names=roles)
        except kc_exception.NotFound as ex:
            LOG.exception(ex)
            LOG.debug("Failed to find roles %s for user %s"
                      % (roles, trustor_user_id))
            raise exception.MissingCredentialError(
                message="Invalid roles %s" % roles)

        trust_context = context.RequestContext.from_dict(
            self.context.to_dict())
        trust_context.trust_id = trust.id
        trust_context.trustor_user_id = trustor_user_id
        return trust_context

    def delete_trust(self, trust_id):
        """Delete the specified trust."""
        try:
            self.client.trusts.delete(trust_id)
        except kc_exception.NotFound:
            pass

    def _get_username(self, username):
        if(len(username) > 64):
            LOG.warning(_LW("Truncating the username %s to the last 64 "
                            "characters."), username)
        # get the last 64 characters of the username
        return username[-64:]

    def url_for(self, **kwargs):
        default_region_name = (self.context.region_name or
                               cfg.CONF.region_name_for_services)
        kwargs.setdefault('region_name', default_region_name)
        return self.context.auth_plugin.get_endpoint(self.session, **kwargs)

    @property
    def auth_token(self):
        return self.context.auth_plugin.get_token(self.session)

    @property
    def auth_ref(self):
        return self.context.auth_plugin.get_access(self.session)

class KeystoneClientV3(KeystoneClientBase):

    def __init__(self, context):
       super(KeystoneClientV3, self).__init__(context)

    def user_exist_in_tenant(self, project_id, user_id):
        try:
            user = self.client_instance.users.get(user_id)
            project = self.client_instance.projects.get(project_id)
            output = self.client_instance.role_assignments.list(user=user, project=project)
            if len(output) > 0:
               return True
            else:
                 return False
            #projects = self.client_instance.projects.list(user=user)
            #project_list = [project.id for project in projects]
        except Exception:
            return False

    def check_user_role(self, project_id, user_id):
        try:
            roles = self.client_instance.roles.list(user=user_id, project=project_id)
            trustee_role = CONF.trustee_role
            for role in roles:
                if (trustee_role == role.name) or (role.name == 'admin'):
                    return True
            return False
        except Exception as ex:
            LOG.exception(ex)

    def get_project_list_for_import(self, context):
        try:
            projects = []
            if (context.user == CONF.get('nova_admin_username')):
                projects = self.client_instance.projects.list()
            else:
                #user = self.client_instance.users.get(context.user_id)
                #projects = self.client_instance.projects.list(user=user)
                user = self.client_instance.users.get(context.user_id)
                project_list = self.client_instance.role_assignments.list(user=user)
                for proj in project_list:
                    if 'project' in proj.__dict__['scope'].keys():
                        project_id = proj.__dict__['scope']['project']['id']
                        project = self.client_instance.projects.get(project_id)
                        projects.append(project)
            return projects
        except Exception as ex:
            LOG.exception(ex)


class KeystoneClientV2(KeystoneClientBase):

    def __init__(self, context):
       super(KeystoneClientV2, self).__init__(context)

    def user_exist_in_tenant(self, project_id, user_id):
        try:
            users = self.client_instance.users.list(project_id)
            user_ids = [user.id for user in users]
            if user_id in user_ids:
                return True
            else:
                return False
        except Exception as ex:
            LOG.exception(ex)

    def check_user_role(self, project_id, user_id):
        try:
            roles = self.client_instance.tenants.role_manager.roles_for_user(user_id, project_id)
            trustee_role = CONF.trustee_role
            for role in roles:
                if (trustee_role == role.name) or (role.name == 'admin'):
                    return True
            return False
        except Exception as ex:
            LOG.exception(ex)

    def get_project_list_for_import(self, context):
        try:
            projects = self.client_instance.tenants.list()
            return projects
        except Exception as ex:
            LOG.exception(ex)

class KeystoneClient(object):
    """Keystone Auth Client.
    """

    _instance = None

    def __new__(class_, *args, **kwargs):
        if not isinstance(class_._instance, class_):
            class_._instance = object.__new__(class_, *args, **kwargs)
        return class_._instance

    def __init__(self, context):
        auth_url = CONF.keystone_endpoint_url
        if auth_url.find('v3') != -1:
            self.client = KeystoneClientV3(context)
        else:
            self.client = KeystoneClientV2(context)

    def get_user_to_get_email_address(self, context):
        user = self.client.client_instance.users.get(context.user_id)
        if not hasattr(user, 'email'):
            user.email = None
        return user

    def get_user_list(self):
        users = self.client.client_instance.users.list()
        return users

    def create_flavor(self, name, ram, vcpus, disk, ephemeral=0, swap=0):
        nova = self.client.nova_client
        return nova.flavors.create(name, ram, vcpus, disk, ephemeral=ephemeral, swap=swap)

def list_opts():
    yield None, keystone_opts
