# vim: tabstop=4 shiftwidth=4 softtabstop=4 
# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


"""Keystone Client functionality for use by resources."""

import collections
import uuid
import json
import os

from keystoneclient.auth.identity import v3 as kc_auth_v3
import keystoneclient.exceptions as kc_exception
from keystoneclient import session
from keystoneclient.v3 import client as kc_v3
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils

from workloadmgr.common import context
from workloadmgr import exception
from workloadmgr.common.i18n import _
from workloadmgr.common.i18n import _LE
from workloadmgr.common.i18n import _LW
from workloadmgr.vault import vault

LOG = logging.getLogger('workloadmgr.common.keystoneclient')

AccessKey = collections.namedtuple('AccessKey', ['id', 'access', 'secret'])

_default_keystone_backend = "workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV3"

keystone_opts = [
    cfg.StrOpt('keystone_backend',
               default=_default_keystone_backend,
               help="Fully qualified class name to use as a keystone backend.")
]
cfg.CONF.register_opts(keystone_opts)


class KeystoneClientV3(object):
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
        self._admin_auth = None
        self._domain_admin_auth = None
        self._domain_admin_client = None

        self.session = session.Session.construct(self._ssl_options())
        self.v3_endpoint = self.context.keystone_v3_endpoint

        if self.context.trust_id:
            # Create a client with the specified trust_id, this
            # populates self.context.auth_token with a trust-scoped token
            self._client = self._v3_client_init()

    @property
    def client(self):
        if not self._client:
            # Create connection to v3 API
            self._client = self._v3_client_init()
        return self._client

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


class KeystoneClient(object):
    """Keystone Auth Client.

    Delay choosing the backend client module until the client's class
    needs to be initialized.
    """

    def __new__(cls, context):
        if cfg.CONF.keystone_backend == _default_keystone_backend:
            return KeystoneClientV3(context)
        else:
            return importutils.import_object(
                cfg.CONF.keystone_backend,
                context
            )


def list_opts():
    yield None, keystone_opts

def user_exist_in_tenant(context, project_id, user_id):
    keystone_client = vault.get_client(context)
    if keystone_client.version == 'v3':
        try:
            user = keystone_client.users.get(user_id)
            projects = keystone_client.projects.list(user=user)
            project_list = [project.id for project in projects]
            if project_id in project_list:
                return True
            else:
                return False
        except Exception :
            return False
    else:
        users = keystone_client.users.list(project_id)
        user_ids = [user.id for user in users]
        if user_id in user_ids:
            return True
        else:
            return False

def check_user_role(context, project_id, user_id ):
    try:
        keystone_client = vault.get_client(context)
        if keystone_client.version == 'v3':
            roles = keystone_client.roles.list(user=user_id, project=project_id)
        else:
            roles = keystone_client.tenants.role_manager.roles_for_user(user_id, project_id)
        trustee_role = vault.CONF.trustee_role
        for role in roles:
            if (trustee_role == role.name) or (role.name == 'admin'):
                return True
        return False
    except Exception as ex:
        LOG.exception(ex)

def get_workloads_for_tenant(context, tenant_ids):
    workload_ids = []
    for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
        vault.get_backup_target(backup_endpoint)
    for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
        backup_target = None
        try:
            backup_target = vault.get_backup_target(backup_endpoint)
            for workload_url in backup_target.get_workloads(context):
                workload_values = json.loads(backup_target.get_object(\
                        os.path.join(workload_url, 'workload_db')))
                project_id = workload_values.get('project_id')
                workload_id = workload_values.get('id')
                if project_id in tenant_ids:
                    workload_ids.append(workload_id)
        except Exception as ex:
            LOG.exception(ex)
    return  workload_ids

def update_workload_db(context, workloads_to_update, new_tenant_id, user_id):

    workload_urls = []

    try:
        #Ensure all mounts
        for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
            vault.get_backup_target(backup_endpoint)

        #Get list of workload directory path for workloads need to update
        for workload_id in workloads_to_update:
            for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
                backup_target = None
                backup_target = vault.get_backup_target(backup_endpoint)
                workload_url = os.path.join(backup_target.mount_path, "workload_" + workload_id)
                if os.path.isdir(workload_url):
                    workload_urls.append(workload_url)
                    break;

        #Iterate through each workload directory and update workload_db and snapsot_db with new values
        for workload_path in workload_urls:
            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())

                        if db_values.get('project_id', None) is not None:
                            db_values['project_id'] = new_tenant_id
                        else:
                            db_values['tenant_id'] = new_tenant_id
                        db_values['user_id'] = user_id

                        with open(os.path.join(path, name), 'w') as file:
                            json.dump(db_values, file)
    except Exception as ex:
        LOG.exception(ex)

