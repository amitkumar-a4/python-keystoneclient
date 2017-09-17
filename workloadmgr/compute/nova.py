# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to compute + nova.
"""

import time
import glob
import itertools
import inspect
import pkgutil
import os
import imp
import pkg_resources
import six
from six.moves.urllib import parse
from threading import Lock
from collections import namedtuple
from functools import wraps

from oslo.config import cfg

from novaclient import exceptions as nova_exception
from novaclient import service_catalog
from novaclient import client
from novaclient import extension as nova_extension
from novaclient.v1_1 import client as nova_client

from neutronclient.common import exceptions as nc_exc

from workloadmgr.db import base
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.common import context as wlm_context
from workloadmgr import exception
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.common import clients

from workloadmgr import autolog
from workloadmgr.decorators import retry

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)


nova_opts = [
    cfg.StrOpt('nova_admin_auth_url',
               default='http://localhost:5000/v2.0',
               help='auth url for connecting to nova in admin context'),
    cfg.StrOpt('nova_admin_username',
               default='admin',
               help='tenant name for connecting to nova in admin context'),
    cfg.StrOpt('nova_admin_password',
               default='password',
               help='password for connecting to nova in admin context',
               secret=True),
    cfg.StrOpt('nova_admin_tenant_name',
               default='admin',
               help='tenant name for connecting to nova in admin context'),
    cfg.StrOpt('nova_production_endpoint_template',
               default= 'http://localhost:8774/v2/%(project_id)s',
               help='nova production endpoint e.g. http://localhost:8774/v2/%(project_id)s'),
    cfg.StrOpt('nova_tvault_endpoint_template',
               default= 'http://localhost:8774/v2/%(project_id)s',
               help='nova tvault endpoint e.g. http://localhost:8774/v2/%(project_id)s'),
    cfg.StrOpt('nova_production_region_name',
               default=None,
               help='region name for connecting to nova in admin context'),
    cfg.StrOpt('nova_tvault_region_name',
               default=None,
               help='region name for connecting to nova in admin context'),
    cfg.BoolOpt('nova_api_insecure',
                default=True,
                help='if set, ignore any SSL validation issues'),
    cfg.StrOpt('nova_auth_system',
               default='keystone',
               help='auth system for connecting to '
                    'nova in admin context'),
    cfg.IntOpt('nova_url_timeout',
               default=600,
               help='timeout value for connecting to nova in seconds'),
]

CONF = cfg.CONF
CONF.register_opts(nova_opts)

LOG = logging.getLogger(__name__)

novalock = Lock()
def synchronized(lock):
    '''Synchronization decorator.'''
    def wrap(f):
        def new_function(*args, **kw):
            lock.acquire()
            try:
                return f(*args, **kw)
            finally:
                lock.release()
        return new_function
    return wrap

def _discover_extensions(version):
    extensions = []
    for name, module in itertools.chain(
            _discover_via_python_path(),
            _discover_via_contrib_path(version),
            _discover_via_entry_points()):

        extension = nova_extension.Extension(name, module)
        extensions.append(extension)

    return extensions

def _discover_via_python_path():
    for (module_loader, name, _ispkg) in pkgutil.iter_modules():
        if name.endswith('_python_novaclient_ext'):
            if not hasattr(module_loader, 'load_module'):
                # Python 2.6 compat: actually get an ImpImporter obj
                module_loader = module_loader.find_module(name)

            module = module_loader.load_module(name)
            if hasattr(module, 'extension_name'):
                name = module.extension_name

            yield name, module

def _discover_via_contrib_path(version):
    module_path = os.path.dirname(os.path.abspath(__file__))
    version_str = "v%s" % version.replace('.', '_')
    ext_path = os.path.join(module_path, version_str, 'contrib')
    ext_glob = os.path.join(ext_path, "*.py")

    for ext_path in glob.iglob(ext_glob):
        name = os.path.basename(ext_path)[:-3]

        if name == "__init__":
            continue

        module = imp.load_source(name, ext_path)
        yield name, module

def _discover_via_entry_points():
    for ep in pkg_resources.iter_entry_points('novaclient.extension'):
        name = ep.name
        module = ep.load()

        yield name, module

try:
    # load keystone_authtoken by importing keystonemiddleware
    # if it is already loaded, just ignore the exception
    cfg.CONF.import_group('keystone_authtoken',
                          'keystonemiddleware.auth_token')
except:
    pass

def _get_trusts(user_id, tenant_id):

    db = WorkloadMgrDB().db
    context = wlm_context.RequestContext(
                user_id=user_id,
                project_id=tenant_id)

    settings = db.setting_get_all_by_project(
                        context, context.project_id)

    trust = [t for t in settings if t.type == "trust_id" and \
             t.project_id == context.project_id and \
             t.user_id == context.user_id]
    return trust


def _get_tenant_context(context):
    from workloadmgr import workloads as workloadAPI
    if type(context) is dict:
       user_id = context['user_id']
       tenant_id = context['project_id']
       user = context.get('user',None)
       tenant = context.get('tenant',None)
       if 'user_domain_id' in context:
          user_domain_id = context['user_domain_id']
       else:
            user_domain_id = 'default'
    else:   
         if hasattr(context, 'user_id'):
            user_id = context.user_id
         elif hasattr(context, 'user'):
              user_id = context.user

         if hasattr(context, 'tenant_id'):
            tenant_id = context.tenant_id
         elif hasattr(context, 'project_id'):
              tenant_id = context.project_id
         elif hasattr(context, 'tenant'):
              tenant_id = context.tenant

         if hasattr(context, 'user_domain_id'):
            if context.user_domain_id is None:
               user_domain_id = 'default'
            else:
                 user_domain_id = context.user_domain_id
         elif hasattr(context, 'user_domain'):
              if context.user_domain is None:
                 user_domain_id = 'default'
              else:
                   user_domain_id = context.user_domain
         else:
              user_domain_id = 'default'

         user = getattr(context, 'user', 'NA')
         tenant = getattr(context, 'tenant', 'NA')

    trust = _get_trusts(user_id, tenant_id)
    if len(trust):
        try:
            trust_id = trust[0].value
            context = wlm_context.RequestContext(
                username=CONF.keystone_authtoken.admin_user,
                password=CONF.keystone_authtoken.admin_password,
                trust_id=trust_id,
                tenant_id=tenant_id,
                trustor_user_id=user_id,
                user_domain_id=CONF.triliovault_user_domain_id,
                is_admin=False)

            clients.initialise()
            client_plugin = clients.Clients(context)
            kclient = client_plugin.client("keystone")
            context.auth_token = kclient.auth_token
            context.user_id = user_id
            if user != 'NA' and getattr(context, 'user', None) == None:
               context.user = user
            if tenant != 'NA' and getattr(context, 'tenant', None) == None:
               context.tenant = tenant
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = _("Assign valid trustee role to tenant %s") % tenant_id
                workloadAPI.api.AUDITLOG(context, msg, None)
                LOG.info(msg)
                LOG.exception(_("token cannot be created using saved "
                                "trust id for user %s, tenant %s") %
                                (user_id, tenant_id))
    else:
         LOG.info(_("Could not find any saved trust ids. Trying "
                    "admin credentials to generate token"))
         try:
            httpclient = client.HTTPClient(
                user=CONF.nova_admin_username,
                password=CONF.nova_admin_password,
                tenant_id=tenant_id,
                service_type='compute',
                endpoint_type='adminURL',
                region_name=CONF.nova_production_region_name,
                auth_url=CONF.nova_admin_auth_url,
                domain_name=user_domain_id,
                timeout=CONF.nova_url_timeout,
                auth_system=CONF.nova_auth_system,
                insecure=CONF.nova_api_insecure)
            httpclient.authenticate()
            context = wlm_context.RequestContext(
                user_id=user_id, project_id=tenant_id,
                is_admin=True, auth_token=httpclient.auth_token)
            if user != 'NA' and getattr(context, 'user', None) == None:
               context.user = user
            if tenant != 'NA' and getattr(context, 'tenant', None) == None:
               context.tenant = tenant
         except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("_get_auth_token() with admin credentials failed. "
                                "Perhaps admin is not member of tenant %s") % tenant_id)
                msg = _("Assign valid trustee role to tenant %s") % tenant_id
                workloadAPI.api.AUDITLOG(context, msg, None)

    return context


def novaclient(context, production=True, refresh_token=False, extensions=None):
    trust = _get_trusts(context.user_id, context.tenant_id)
    if hasattr(context, 'user_domain_id'):
       if context.user_domain_id is None:
          user_domain_id = 'default'
       else:
            user_domain_id = context.user_domain_id
    elif hasattr(context, 'user_domain'):
       if context.user_domain is None:
          user_domain_id = 'default'
       else:
            user_domain_id = context.user_domain
    else:
         user_domain_id = 'default'
    # pick the first trust. Usually it should not be more than one trust
    if len(trust):
        trust_id = trust[0].value

        if refresh_token:
            context = wlm_context.RequestContext(
                username=CONF.keystone_authtoken.admin_user,
                password=CONF.keystone_authtoken.admin_password,
                trust_id=trust_id,
                tenant_id=context.project_id,
                trustor_user_id=context.user_id,
                user_domain_id=CONF.triliovault_user_domain_id,
                is_admin=False)
        else:
            context = wlm_context.RequestContext(
                trustor_user_id=context.user_id,
                project_id=context.project_id,
                auth_token=context.auth_token,
                trust_id=trust_id,
                user_domain_id=user_domain_id,
                is_admin=False)

        clients.initialise()
        nova_plugin = clients.Clients(context)
        novaclient = nova_plugin.client("nova")
        novaclient.client_plugin = novaclient
    else:
        # trusts are not enabled
        if refresh_token:
            if production == True:
                url = CONF.nova_production_endpoint_template.replace('%(project_id)s', context.tenant_id)
                url = url.replace("/v2.1/", "/v2/")
                novaclient = nova_client.Client(CONF.nova_admin_username,
                                       CONF.nova_admin_password,
                                       project_id=context.tenant_id,
                                       auth_url=url,
                                       domain_name=user_domain_id,
                                       insecure=CONF.nova_api_insecure,
                                       extensions = extensions,
                                       timeout=CONF.nova_url_timeout)
            else:
                url = CONF.nova_tvault_endpoint_template.replace('%(project_id)s', context.tenant_id)
                novaclient = nova_client.Client(CONF.nova_admin_username,
                                       CONF.nova_admin_password,
                                       project_id=context.tenant_id,
                                       auth_url=url,
                                       domain_name=user_domain_id,
                                       insecure=CONF.nova_api_insecure,
                                       extensions = extensions,
                                       timeout=CONF.nova_url_timeout)
            LOG.debug(_('Novaclient connection created using URL: %s') % url)
        else:
            if production == True:
                url = CONF.nova_production_endpoint_template % context.to_dict()
                url = url.replace("/v2.1/", "/v2/")
            else:
                url = CONF.nova_tvault_endpoint_template % context.to_dict()
            LOG.debug(_('Novaclient connection created using URL: %s') % url)
            novaclient = nova_client.Client(context.user_id,
                                   context.auth_token,
                                   project_id=context.project_id,
                                   auth_url=url,
                                   domain_name=user_domain_id,
                                   insecure=CONF.nova_api_insecure,
                                   extensions = extensions,
                                   timeout=CONF.nova_url_timeout)

            # noauth extracts user_id:tenant_id from auth_token
            novaclient.client.auth_token = context.auth_token or '%s:%s' % (context.user_id, context.project_id)
            novaclient.client.management_url = url

    return novaclient

def novaclient2(auth_url, username, password, tenant_name, nova_endpoint_template):
    httpclient = client.HTTPClient(
        user=username,
        password=password,
        projectid=tenant_name,
        service_type='compute',
        endpoint_type='adminURL',
        region_name=CONF.nova_production_region_name,
        auth_url=auth_url,
        timeout=CONF.nova_url_timeout,
        auth_system=CONF.nova_auth_system,
        insecure=CONF.nova_api_insecure)
    httpclient.authenticate()
    url = nova_endpoint_template.replace('%(project_id)s', httpclient.tenant_id)
    c = nova_client.Client(username,
                           password,
                           project_id=httpclient.tenant_id,
                           auth_url=url,
                           insecure=CONF.nova_api_insecure,
                           extensions = None,
                           timeout=CONF.nova_url_timeout)
    LOG.debug(_('Novaclient connection created using URL: %s') % url)
    c.client.auth_token = httpclient.auth_token
    c.client.management_url = url
    return c


def exception_handler(ignore_exception=False, refresh_token=True, contego=False):
    def exception_handler_decorator(func):
        @wraps(func)
        def func_wrapper(*args, **argv):
            try:
                try:
                    extensions = None
                    if contego is True:
                        extensions = _discover_extensions('1.1')
                    client = novaclient(args[1], args[0]._production,
                                        refresh_token=False,
                                        extensions=extensions)
                    argv.update({'client': client})
                    return func(*args, **argv)
                except (nc_exc.NeutronClientException, nova_exception.Unauthorized) as unauth_ex:
                    if refresh_token is True:
                        argv.pop('client')
                        client = novaclient(args[1], args[0]._production,
                                            refresh_token=True,
                                            extensions=extensions)
                        argv.update({'client': client})
                        return func(*args, **argv)
            except Exception as ex:
                if ignore_exception is True:
                    LOG.exception(ex)
                    if nova_exception.BadRequest in \
                        inspect.getmro(ex.__class__) or \
                        nova_exception.NotFound in \
                        inspect.getmro(ex.__class__):
                        return

                if contego is True:
                    msg = "Unable to call %s; Please check contego " \
                          "logs for more details" % func.func_name
                    if hasattr(ex, 'code') and ex.code == 413:
                       msg = ex.message
                    raise exception.ErrorOccurred(reason=msg)
                else:
                    raise

        return func_wrapper
    return exception_handler_decorator


class API(base.Base):
    """API for interacting with the volume manager."""

    def __init__(self, production = True):
        self._production = production

    @synchronized(novalock)
    @exception_handler(ignore_exception=True)
    def get_hypervisors(self, context, **kwargs):
        client = kwargs['client']
        hypervisors = novaclient(context, self._production, True).hypervisors.list()
        return hypervisors

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def create_server(self, context, name, image, flavor,
                      meta=None, files=None,
                      reservation_id=None, min_count=None,
                      max_count=None, security_groups=None, userdata=None,
                      key_name=None, availability_zone=None,
                      block_device_mapping=None, nics=None, scheduler_hints=None,
                      config_drive=None, **kwargs):

        """
        Create (boot) a new server.

        :param name: Something to name the server.
        :param image: The :class:`Image` to boot with.
        :param flavor: The :class:`Flavor` to boot onto.
        :param production: If True, production Nova will be used.
        :param meta: A dict of arbitrary key/value metadata to store for this
                     server. A maximum of five entries is allowed, and both
                     keys and values must be 255 characters or less.
        :param files: A dict of files to overrwrite on the server upon boot.
                      Keys are file names (i.e. ``/etc/passwd``) and values
                      are the file contents (either as a string or as a
                      file-like object). A maximum of five entries is allowed,
                      and each file must be 10k or less.
        :param userdata: user data to pass to be exposed by the metadata
                      server this can be a file type object as well or a
                      string.
        :param reservation_id: a UUID for the set of servers being requested.
        :param key_name: (optional extension) name of previously created
                      keypair to inject into the instance.
        :param availability_zone: Name of the availability zone for instance
                                  placement.
        :param block_device_mapping: (optional extension) A dict of block
                      device mappings for this server.
        :param nics:  (optional extension) an ordered list of nics to be
                      added to this server, with information about
                      connected networks, fixed ips, port etc.
        :param scheduler_hints: (optional extension) arbitrary key-value pairs
                            specified by the client to help boot an instance
        :param config_drive: (optional extension) value for config drive
                            either boolean, or volume-id
        """

        client = kwargs['client']
        item = client.servers.create(name, image, flavor,
                                     meta=meta, files=files,
                                     reservation_id=reservation_id, min_count=min_count,
                                     max_count=max_count, security_groups=security_groups,
                                     userdata=userdata, key_name=key_name,
                                     availability_zone=availability_zone,block_device_mapping=block_device_mapping,
                                     nics=nics, scheduler_hints=scheduler_hints,
                                     config_drive=config_drive, **kwargs)
        time.sleep(15)
        return item

    def _get_servers(self, context, search_opts=None, admin=False, **kwargs):
        """
        Get all the servers for a particular tenant or all tenants
        :rtype: :class:`Server`
        """
        if search_opts is None:
            search_opts = {}
        if admin:
            search_opts['all_tenants'] = True
        else:
            search_opts['project_id'] = context.project_id

        servers = None
        client = kwargs['client']
        servers = client.servers.list(True, search_opts)

        return servers

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_servers(self, context, search_opts=None, admin=False, **kwargs):
        return self._get_servers(context, search_opts, admin, **kwargs)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_server(self, context, name, admin=False, **kwargs):
        """
        Get the server given the name
        :rtype: :class:`Server`
        """
        server = None
        client = kwargs['client']
        client = novaclient(context, self._production, admin)
        return client.servers.find(name=name)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_security_group_by_id(self, context, secid, admin=False, **kwargs):
        """
        Get the security group given the name
        :rtype: :int:`secuirty id`
        """
        client = kwargs['client']
        return client.security_groups.get(secid)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_security_groups(self, context, admin=False, **kwargs):
        """
        Get the security group given the name
        :rtype: :int:`secuirty id`
        """
        client = kwargs['client']
        return client.security_groups.list()

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_server_by_id(self, context, id, admin=False, search_opts=None, **kwargs):
        """
        :param id to query.
        :rtype: :class:`Server`
        """
        if search_opts == None:
            servers = self._get_servers(context, search_opts, admin=admin, **kwargs)
            for server in servers:
                if server.id == id:
                    return server
            return None
        else:
            qparams = {}

            client = kwargs['client']
            for opt, val in six.iteritems(search_opts):
                if val:
                    qparams[opt] = val
                if qparams:
                    new_qparams = sorted(qparams.items(), key=lambda x: x[0])
                    query_string = "?%s" % parse.urlencode(new_qparams)
                else:
                    query_string = ""
                server = client.servers._get("/servers/%s%s" % (id, query_string), "server")
                return server

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def stop(self, context, server, **kwargs):
        """
        Stop the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        return client.servers.stop(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def start(self, context, server, **kwargs):
        """
        Start the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        return client.servers.start(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def suspend(self, context, server, **kwargs):
        """
        Suspend the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        client = novaclient(context, self._production)
        return client.servers.suspend(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def reboot(self, context, server, reboot_type='SOFT', **kwargs):
        """
        Suspend the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """   
    
        client = kwargs['client']
        return client.servers.reboot(server=server, reboot_type=reboot_type)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def resume(self, context, server, **kwargs):
        """
        Resume the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        return client.servers.resume(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def pause(self, context, server, **kwargs):
        """
        Pause the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        return client.servers.pause(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def unpause(self, context, server, **kwargs):
        """
        UnPause the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        return client.servers.unpause(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def delete(self, context, server, **kwargs):
        """
        Delete the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        return client.servers.delete(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def force_delete(self, context, server, **kwargs):
        """
        Force Delete the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        client = kwargs['client']
        return client.servers.force_delete(server=server)

    @synchronized(novalock)
    @exception_handler(ignore_exception=True)
    def set_meta_item(self, context, server_id, key, value, **kwargs):
        """
        Adds a metadata item to the server given key value
        :param server: The :class:`Server` (or its ID) to query.
        """

        server = namedtuple('server', 'id')
        s = server(id=server_id)
        client = kwargs['client']

        return client.servers.set_meta_item(server=s, key=key, value=value)

    @synchronized(novalock)
    @exception_handler(ignore_exception=True)
    def delete_meta(self, context, server_id, keys, **kwargs):
        """
        Delete metadata of the server given the server id and keys
        :param server: The :class:`Server` (or its ID) to query.
        :param keys: meta data keys
        """

        server = namedtuple('server', 'id')
        s = server(id=server_id)
        client = kwargs['client']

        return client.servers.delete_meta(server=s, keys=keys)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def list_security_group(self, context, server_id, **kwargs):
        """
        List security groups on the server
        :param server: The :class:`Server` (or its ID) to query.
        """

        server = namedtuple('server', 'id')
        s = server(id=server_id)
        client = kwargs['client']

        return client.servers.list_security_group(server=s)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def add_security_group(self, context, server_id, security_group_id, **kwargs):
        """
        Add security group identified by security group id
        :param server: The :class:`Server` (or its ID) to query.
        :param security_group_id: Security group id
        """

        server = namedtuple('server', 'id')
        s = server(id=server_id)
        client = kwargs['client']

        return client.servers.add_security_group(server=s, security_group=security_group_id)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def remove_security_group(self, context, server_id, security_group_id, **kwargs):
        """
        Removes a security group identified by the security group_id
        :param server: The :class:`Server` (or its ID) to query.
        :param security_group_id: Security group id
        """

        server = namedtuple('server', 'id')
        s = server(id=server_id)
        client = kwargs['client']

        return client.servers.remove_security_group(server=s, security_group=security_group_id)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def add_floating_ip(self, context, server_id, floating_ip, fixed_ip, **kwargs):
        """
        Add floating ip to the server
        :param server: The :class:`Server` (or its ID) to query.
        :param floating_ip: Floating IP
        """

        server = namedtuple('server', 'id')
        s = server(id=server_id)
        client = kwargs['client']

        return client.servers.add_floating_ip(server=s, address=floating_ip,
                                              fixed_address=fixed_ip)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def floating_ip_list(self, context, **kwargs):
        """
        Add floating ip to the server
        :param server: The :class:`Server` (or its ID) to query.
        :param floating_ip: Floating IP
        """

        client = kwargs['client']

        return client.floating_ips.list()

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def attach_volume(self, context, server_id, volume_id, device, **kwargs):
        """
        Attach a volume identified by the volume ID to the given server ID

        :param server_id: The ID of the server
        :param volume_id: The ID of the volume to attach.
        :param device: The device name
        :rtype: :class:`Volume`
        """

        client = kwargs['client']
        return client.volumes.create_server_volume(server_id, volume_id, device)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_image(self, context, id, **kwargs):
        """
        Get the image given the name

        :param name: name of the image
        :rtype: :class:`Image`
        """

        client = kwargs['client']
        return client.images.find(id=id)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_flavors(self, context, is_public=True, **kwargs):
        """
        Get the list of flavors

        :param is_public: public flavors
        :rtype: :class:`Flavor`
        """
        client = kwargs['client']
        return client.flavors.list(is_public=is_public)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_flavor_by_name(self, context, name, **kwargs):
        """
        Get the flavors given the name

        :param name: name of the flavors
        :rtype: :class:`Flavor`
        """

        client = kwargs['client']
        return client.flavors.find(name=name)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_flavor_by_id(self, context, id, **kwargs):
        """
        Get the flavor given the id

        :param name: id of the flavors
        :rtype: :class:`Flavor`
        """

        client = kwargs['client']
        return client.flavors.get(id)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def create_flavor(self, context, name, memory, vcpus,
                      root_gb, ephemeral_gb, **kwargs):

        """
        Create a new flavor

        :rtype: :class:`Flavor`
        """

        client = kwargs['client']
        return client.flavors.create(name, memory, vcpus, root_gb,
                                     flavorid="auto", ephemeral=ephemeral_gb)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def delete_flavor(self, context, id, **kwargs):
        """
        Delete the falvor given the flavor name
        """

        client = kwargs['client']
        return client.flavors.delete(id)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_keypairs(self, context, **kwargs):
        """
        Get the list of keypairs

        :rtype: :class:`keypair`
        """
        client = kwargs['client']
        return client.keypairs.list()

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def create_keypair(self, context, name, public_key, **kwargs):
        """
        Create new keypairs

        """
        client = kwargs['client']
        return client.keypairs.create(name, public_key=public_key)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_keypair_by_name(self, context, name, **kwargs):
        """
        Get the keypair given the name

        :param name: name of the keypair
        :rtype: :class:`keypair`
        """

        client = kwargs['client']
        return client.keypairs.get(name)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_interfaces(self, context, server, **kwargs):
        """
        List attached network interfaces

        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        try:
            return client.servers.interface_list(server=server)
        except nova_exception.HTTPNotImplemented:
            # This is configured to use nova network
            server = client.servers.get(server)
            return server._info['addresses']
    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_networks(self, context, **kwargs):
        """
        Get the list of nova networks

        :param is_public: public networks
        :rtype: :class:`Network`
        """
        client = kwargs['client']
        return client.networks.list()

    @synchronized(novalock)
    @exception_handler(ignore_exception=False)
    def get_fixed_ip(self, context, ip, **kwargs):
        """
        Get the IP address information

        :param IP4 address: 
        """
        client = kwargs['client']
        return client.fixed_ips.get(ip)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def map_snapshot_files(self, context, server, params, **kwargs):
        """
        Map snapshot volume images to file manager instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.map_snapshot_files(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def vast_prepare(self, context, server, params, **kwargs):
        """
        PREPARE to VAST an instance
        :param server: The :class:`Server` (or its ID) to prepare.
        """
        client = kwargs['client']
        return client.contego.vast_prepare(server=server, params=params)

    def contego_service_status(self, context, host=None, ip=None):
        """
        Get contego service status running on a compute node
        """
        contego_service_info = {}
        all_services = []
        try:                
            try:
                client = novaclient(context, self._production)
                
                if host == 'all' and ip == 'all':
                    all_services = client.services.list()               
                elif host != 'all':
                    all_services = client.services.list(host=host)
                elif ip != 'all':
                    for hypervisor in client.hypervisors.list():                    
                        if hypervisor.host_ip == ip:
                            all_services = client.services.list(host=hypervisor.hypervisor_hostname)
                            
                for service in all_services:                    
                    if service.binary in 'contego':
                        contego_service_info[service.host] = ({"id":service.id,
                                                                "name":service.binary,
                                                                "status":service.status,
                                                                "running_state":service.state
                                                                })                                                    
                return contego_service_info
            except nova_exception.Unauthorized as unauth_ex:
                client = novaclient(context, self._production, admin=True)
                all_services = client.services.list()
                
                for service in all_services:                    
                    if service.binary in 'contego':
                        contego_service_info[service.host] = ({"id":service.id,
                                                                "name":service.binary,
                                                                "status":service.status,
                                                                "running_state":service.state
                                                                })
                return contego_service_info
            except Exception as ex:
                LOG.exception(ex)                
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to get the status of contego service'
            raise exception.ErrorOccurred(msg)            
            
    @synchronized(novalock)
    @exception_handler(ignore_exception=True, contego=True)
    def vast_freeze(self, context, server, params, **kwargs):
        """
        FREEZE an instance
        :param server: The :class:`Server` (or its ID) to freeze.
        """
        client = kwargs['client']
        return client.contego.vast_freeze(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=True, contego=True)
    def vast_thaw(self, context, server, params, **kwargs):
        """
        Thaw an instance
        :param server: The :class:`Server` (or its ID) to thaw.
        """
        client = kwargs['client']
        return client.contego.vast_thaw(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def vast_instance(self, context, server, params, **kwargs):
        """
        VAST an instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_instance(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    @retry(Exception, tries=3, delay=1, logger=LOG)
    def vast_get_info(self, context, server, params, **kwargs):
        """
        Get components of a VASTed instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_get_info(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def vast_data_transfer(self, context, server, params, **kwargs):
        """
        Transfer a component of a VASTed instance to backup store
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_data_transfer(server=server, params=params, do_checksum=True)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def vast_check_prev_snapshot(self, context, server, params, **kwargs):
        """
        Check if the previous snapshot is valid
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_check_prev_snapshot(server=server,
                                         params=params, do_checksum=True)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def copy_backup_image_to_volume(self, context, server, params, **kwargs):
        """
        Transfer the backup image to volume
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.copy_backup_image_to_volume(server=server,
                                            params=params, do_checksum=True)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def vast_async_task_status(self, context, server, params, **kwargs):
        """
        Get data transfer status of VASTed instance component
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_async_task_status(server=server, params=params, do_checksum=True)

    @synchronized(novalock)
    @exception_handler(ignore_exception=True, contego=True)
    @autolog.log_method(logger=Logger)
    def vast_finalize(self, context, server, params, **kwargs):
        """
        Finalize the VAST
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_finalize(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=True, contego=True)
    @autolog.log_method(logger=Logger)
    def vast_reset(self, context, server, params, **kwargs):
        """
        Reset the VAST snapshot
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_reset(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def testbubble_attach_volume(self, context, server, params, **kwargs):
        """
        Attach a volume to testbubble instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.testbubble_attach_volume(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def testbubble_reboot_instance(self, context, server, params, **kwargs):
        """
        Simple reboot of a testbubble instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.testbubble_reboot_instance(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def vast_commit_image(self, context, server, params, **kwargs):
        """
        Commit snapshot image for instance.
        :param server: The :class:`Server` (or its ID) to query.
        """
        client = kwargs['client']
        return client.contego.vast_commit_image(server=server, params=params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def vast_config_backup(self, context, backup_id, params, **kwargs):
        """
        Backup OpenStack config files.
        :param services: services for which configuration and database need to backup.
        """
        client = kwargs['client']
        return client.contego.vast_config_backup(backup_id, params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def validate_database_creds(self, context, params, **kwargs):
        """
        Validate database credentials.
        :param : database credentials which need to be validate.
        """
        client = kwargs['client']
        return client.contego.validate_database_creds(CONF.cloud_unique_id, params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def validate_trusted_nodes(self, context, params, **kwargs):
        """
        validate a trusted node whether it has access to controller node or not.
        :param : trusted_node hostname.
        """
        client = kwargs['client']
        return client.contego.validate_trusted_nodes(CONF.cloud_unique_id, params)

    @synchronized(novalock)
    @exception_handler(ignore_exception=False, contego=True)
    def get_controller_nodes(self, context, **kwargs):
        """
        Get list of controller nodes.
        """
        client = kwargs['client']
        return client.contego.get_controller_nodes(CONF.cloud_unique_id)
