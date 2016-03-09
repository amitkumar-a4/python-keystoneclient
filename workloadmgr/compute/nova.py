# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to compute + nova.
"""

import time
import glob
import itertools
import pkgutil
import os
import imp
import pkg_resources
import six
from six.moves.urllib import parse
from threading import Lock
from collections import namedtuple

from workloadmgr.openstack.common.gettextutils import _
from novaclient import exceptions as nova_exception
from novaclient import service_catalog
from novaclient import client
from novaclient import extension as nova_extension
from novaclient.v1_1 import client as nova_client
from oslo.config import cfg

from workloadmgr.db import base
from workloadmgr import context
from workloadmgr import exception
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common import log as logging

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
                default=False,
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

def _get_tenant_context(user_id, tenant_id):
    try:
        httpclient = client.HTTPClient(
                user=CONF.nova_admin_username,
                password=CONF.nova_admin_password,
                tenant_id=tenant_id,
                service_name='nova',
                service_type='compute',
                endpoint_type='adminURL',
                region_name=CONF.nova_production_region_name,
                auth_url=CONF.nova_admin_auth_url,
                timeout=CONF.nova_url_timeout,
                auth_system=CONF.nova_auth_system,
                insecure=CONF.nova_api_insecure)
        httpclient.authenticate()
        tenantcontext = context.RequestContext(user_id=user_id, project_id=tenant_id,
                                               is_admin=True, auth_token=httpclient.auth_token)
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_("_get_auth_token() failed"))
    return tenantcontext

def _get_httpclient(production):
    try:
        if production:
            httpclient = client.HTTPClient(
                user=CONF.nova_admin_username,
                password=CONF.nova_admin_password,
                projectid=CONF.nova_admin_tenant_name,
                service_name='nova',
                service_type='compute',
                endpoint_type='adminURL',
                region_name=CONF.nova_production_region_name,
                auth_url=CONF.nova_admin_auth_url,
                timeout=CONF.nova_url_timeout,
                auth_system=CONF.nova_auth_system,
                insecure=CONF.nova_api_insecure)
        else:
            httpclient = client.HTTPClient(
                user=CONF.nova_admin_username,
                password=CONF.nova_admin_password,
                projectid=CONF.nova_admin_tenant_name,
                service_name='nova',
                service_type='compute',
                endpoint_type='adminURL',
                region_name=CONF.nova_tvault_region_name,
                auth_url=CONF.nova_admin_auth_url,
                timeout=CONF.nova_url_timeout,
                auth_system=CONF.nova_auth_system,
                insecure=CONF.nova_api_insecure)
        httpclient.authenticate()
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_("_get_auth_token() failed"))
    return httpclient

def novaclient(context, production, admin=False, extensions = None):
    if admin:
        httpclient = _get_httpclient(production)
        if production == True:
            url = CONF.nova_production_endpoint_template.replace('%(project_id)s', httpclient.tenant_id)
            c = nova_client.Client(CONF.nova_admin_username,
                                   CONF.nova_admin_password,
                                   project_id=httpclient.tenant_id,
                                   auth_url=url,
                                   insecure=CONF.nova_api_insecure,
                                   extensions = extensions,
                                   timeout=CONF.nova_url_timeout)
        else:
            url = CONF.nova_tvault_endpoint_template.replace('%(project_id)s', httpclient.tenant_id)
            c = nova_client.Client(CONF.nova_admin_username,
                                   CONF.nova_admin_password,
                                   project_id=httpclient.tenant_id,
                                   auth_url=url,
                                   insecure=CONF.nova_api_insecure,
                                   extensions = extensions,
                                   timeout=CONF.nova_url_timeout)
        LOG.debug(_('Novaclient connection created using URL: %s') % url)
        c.client.auth_token = httpclient.auth_token
        c.client.management_url = url
    else:
        if production == True:
            url = CONF.nova_production_endpoint_template % context.to_dict()
        else:
            url = CONF.nova_tvault_endpoint_template % context.to_dict()
        LOG.debug(_('Novaclient connection created using URL: %s') % url)
        c = nova_client.Client(context.user_id,
                               context.auth_token,
                               project_id=context.project_id,
                               auth_url=url,
                               insecure=CONF.nova_api_insecure,
                               extensions = extensions,
                               timeout=CONF.nova_url_timeout)
        # noauth extracts user_id:tenant_id from auth_token
        c.client.auth_token = context.auth_token or '%s:%s' % (context.user_id, context.project_id)
        c.client.management_url = url
    return c

def novaclient2(auth_url, username, password, tenant_name, nova_endpoint_template):
    httpclient = client.HTTPClient(
        user=username,
        password=password,
        projectid=tenant_name,
        service_name='nova',
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


class API(base.Base):
    """API for interacting with the volume manager."""

    def __init__(self, production = True):
        self._production = production

    @synchronized(novalock)
    def get_hypervisors(self,context):
        hypervisors = novaclient(context, self._production, True).hypervisors.list()
        return hypervisors

    @synchronized(novalock)
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

        try:
            client = novaclient(context, self._production)
            item = client.servers.create(  name, image, flavor,
                                           meta=meta, files=files,
                                           reservation_id=reservation_id, min_count=min_count,
                                           max_count=max_count, security_groups=security_groups,
                                           userdata=userdata, key_name=key_name,
                                           availability_zone=availability_zone,block_device_mapping=block_device_mapping,
                                           nics=nics, scheduler_hints=scheduler_hints,
                                           config_drive=config_drive, **kwargs)
            time.sleep(15)#TODO(gbasava): Creation is asynchronous. Wait and check for the status
            #Perform translation required if any
            return item
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            item = client.servers.create(  name, image, flavor,
                                           meta=meta, files=files,
                                           reservation_id=reservation_id, min_count=min_count,
                                           max_count=max_count, security_groups=security_groups,
                                           userdata=userdata, key_name=key_name,
                                           availability_zone=availability_zone,block_device_mapping=block_device_mapping,
                                           nics=nics, scheduler_hints=scheduler_hints,
                                           config_drive=config_drive, **kwargs)
            time.sleep(15)#TODO(gbasava): Creation is asynchronous. Wait and check for the status
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    def _get_servers(self, context, search_opts=None, admin=False):
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
        try:
            client = novaclient(context, self._production, admin=admin)
            servers = client.servers.list(True, search_opts)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            servers = client.servers.list(True, search_opts)
        return servers

    @synchronized(novalock)
    def get_servers(self, context, search_opts=None, admin=False):
        return self._get_servers(context, search_opts, admin)

    @synchronized(novalock)
    def get_server(self, context, name, admin=False):
        """
        Get the server given the name
        :rtype: :class:`Server`
        """
        server = None
        try:
            client = novaclient(context, self._production, admin)
            return client.servers.find(name=name)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.find(name=name)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_security_group_by_id(self, context, secid, admin=False):
        """
        Get the security group given the name
        :rtype: :int:`secuirty id`
        """
        try:
            client = novaclient(context, self._production, admin)
            return client.security_groups.get(secid)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.security_groups.get(secid)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_security_groups(self, context, admin=False):
        """
        Get the security group given the name
        :rtype: :int:`secuirty id`
        """
        try:
            client = novaclient(context, self._production, admin)
            return client.security_groups.list()
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.security_groups.list()
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_server_by_id(self, context, id, admin=False, search_opts=None):
        """
        :param id to query.
        :rtype: :class:`Server`
        """
        retries = 3
        while retries:
            try:
                if search_opts == None:
                    servers = self._get_servers(context, search_opts, admin=admin)
                    for server in servers:
                        if server.id == id:
                            return server
                    return None
                else:
                    qparams = {}

                    for opt, val in six.iteritems(search_opts):
                        if val:
                            qparams[opt] = val
                    if qparams:
                        new_qparams = sorted(qparams.items(), key=lambda x: x[0])
                        query_string = "?%s" % parse.urlencode(new_qparams)
                    else:
                        query_string = ""
                    client = novaclient(context, self._production, admin=admin)
                    server = client.servers._get("/servers/%s%s" % (id, query_string), "server")
                    return server
            except nova_exception.Unauthorized as unauth_ex:
                retries -= 1
                admin = True
                if not retries:
                    raise
            except Exception as ex:
                LOG.exception(ex)
                #TODO(gbasava): Handle the exception
                raise

    @synchronized(novalock)
    def stop(self, context, server):
        """
        Stop the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.stop(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.stop(server=server)
        except Exception  as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def start(self, context, server):
        """
        Start the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.start(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.start(server=server)
        except Exception  as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def suspend(self, context, server):
        """
        Suspend the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.suspend(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.suspend(server=server)
        except Exception  as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def reboot(self, context, server, reboot_type='SOFT'):
        """
        Suspend the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """   
    
        try:
            client = novaclient(context, self._production)
            return client.servers.reboot(server=server, reboot_type=reboot_type)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.reboot(server=server, reboot_type=reboot_type)
        except Exception  as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def resume(self, context, server):
        """
        Resume the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.resume(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.resume(server=server)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def pause(self, context, server):
        """
        Pause the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.pause(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.pause(server=server)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def unpause(self, context, server):
        """
        UnPause the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.unpause(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.unpause(server=server)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def delete(self, context, server):
        """
        Delete the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.delete(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.delete(server=server)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def force_delete(self, context, server):
        """
        Force Delete the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            client = novaclient(context, self._production)
            return client.servers.force_delete(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.force_delete(server=server)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def set_meta_item(self, context, server_id, key, value):
        """
        Adds a metadata item to the server given key value
        :param server: The :class:`Server` (or its ID) to query.
        """

        try:
            server = namedtuple('server', 'id')
            s = server(id=server_id)

            client = novaclient(context, self._production)
            return client.servers.set_meta_item(server=s, key=key, value=value)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.set_meta_item(server=s, key=key, value=value)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def delete_meta(self, context, server_id, keys):
        """
        Delete metadata of the server given the server id and keys
        :param server: The :class:`Server` (or its ID) to query.
        :param keys: meta data keys
        """

        try:
            server = namedtuple('server', 'id')
            s = server(id=server_id)

            client = novaclient(context, self._production)
            return client.servers.delete_meta(server=s, keys=keys)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.delete_meta(server=s, keys=keys)
        except Exception as ex:
            LOG.exception(ex)
            return

    @synchronized(novalock)
    def attach_volume(self, context, server_id, volume_id, device):
        """
        Attach a volume identified by the volume ID to the given server ID

        :param server_id: The ID of the server
        :param volume_id: The ID of the volume to attach.
        :param device: The device name
        :rtype: :class:`Volume`
        """

        try:
            client = novaclient(context, self._production)
            return client.volumes.create_server_volume(server_id, volume_id, device)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.volumes.create_server_volume(server_id, volume_id, device)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_image(self, context, id):
        """
        Get the image given the name

        :param name: name of the image
        :rtype: :class:`Image`
        """

        try:
            client = novaclient(context, self._production)
            return client.images.find(id=id)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.images.find(id=id)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_flavors(self, context, is_public=True):
        """
        Get the list of flavors

        :param is_public: public flavors
        :rtype: :class:`Flavor`
        """
        try:
            client = novaclient(context, self._production)
            return client.flavors.list(is_public=is_public)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.flavors.list(is_public=is_public)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_flavor_by_name(self, context, name):
        """
        Get the flavors given the name

        :param name: name of the flavors
        :rtype: :class:`Flavor`
        """

        try:
            client = novaclient(context, self._production)
            return client.flavors.find(name=name)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.flavors.find(name=name)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_flavor_by_id(self, context, id):
        """
        Get the flavor given the id

        :param name: id of the flavors
        :rtype: :class:`Flavor`
        """

        try:
            client = novaclient(context, self._production)
            return client.flavors.get(id)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.flavors.get(id)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def create_flavor(self, context, name, memory, vcpus,
                      root_gb, ephemeral_gb):

        """
        Create a new flavor

        :rtype: :class:`Flavor`
        """

        try:
            client = novaclient(context, self._production, admin=True)
            return client.flavors.create(name,
                                         memory, vcpus, root_gb, flavorid="auto",
                                         ephemeral = ephemeral_gb)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.flavors.create(name,
                                         memory, vcpus, root_gb, flavorid="auto",
                                         ephemeral = ephemeral_gb)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def delete_flavor(self, context, id):
        """
        Delete the falvor given the flavor name
        """

        try:
            client = novaclient(context, self._production, admin=True)
            return client.flavors.delete(id)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.flavors.delete(id)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_keypairs(self, context):
        """
        Get the list of keypairs

        :rtype: :class:`keypair`
        """
        try:
            client = novaclient(context, self._production)
            return client.keypairs.list()
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.keypairs.list()
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def create_keypair(self, context, name, public_key):
        """
        Create new keypairs

        """
        try:
            client = novaclient(context, self._production)
            return client.keypairs.create(name, public_key=public_key)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.keypairs.create(name, public_key=public_key)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_keypair_by_name(self, context, name):
        """
        Get the keypair given the name

        :param name: name of the keypair
        :rtype: :class:`keypair`
        """

        try:
            client = novaclient(context, self._production)
            return client.keypairs.get(name)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.keypairs.get(name)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_interfaces(self, context, server):
        """
        List attached network interfaces

        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            client = novaclient(context, self._production)
            return client.servers.interface_list(server=server)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.servers.interface_list(server=server)
        except nova_exception.HTTPNotImplemented:
            # This is configured to use nova network
            server = client.servers.get(server)
            return server._info['addresses']
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return
    @synchronized(novalock)
    def get_networks(self, context):
        """
        Get the list of nova networks

        :param is_public: public networks
        :rtype: :class:`Network`
        """
        try:
            client = novaclient(context, self._production)
            return client.networks.list()
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.networks.list()
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def get_fixed_ip(self, context, ip):
        """
        Get the IP address information

        :param IP4 address: 
        """
        try:
            client = novaclient(context, self._production)
            return client.fixed_ips.get(ip)
        except nova_exception.Unauthorized as unauth_ex:
            client = novaclient(context, self._production, admin=True)
            return client.fixed_ips.get(ip)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception
            return

    @synchronized(novalock)
    def map_snapshot_files(self, context, server, params):
        """
        Map snapshot volume images to file manager instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.map_snapshot_files(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.map_snapshot_files(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to map snapshot; Please check contego logs for more details' 
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    def vast_prepare(self, context, server, params):
        """
        PREPARE to VAST an instance
        :param server: The :class:`Server` (or its ID) to prepare.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_prepare(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_prepare(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to prepare instance for snapshot operation; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    def vast_freeze(self, context, server, params):
        """
        FREEZE an instance
        :param server: The :class:`Server` (or its ID) to freeze.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_freeze(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_freeze(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception


    @synchronized(novalock)
    def vast_thaw(self, context, server, params):
        """
        Thaw an instance
        :param server: The :class:`Server` (or its ID) to thaw.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_thaw(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_thaw(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            #TODO(gbasava): Handle the exception


    @synchronized(novalock)
    def vast_instance(self, context, server, params):
        """
        VAST an instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_instance(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_instance(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to snapshot; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    @retry(Exception, tries=3, delay=1, logger=LOG)
    def vast_get_info(self, context, server, params):
        """
        Get components of a VASTed instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_get_info(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_get_info(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to get instace info; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    def vast_data_transfer(self, context, server, params):
        """
        Transfer a component of a VASTed instance to backup store
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_data_transfer(server=server, params=params, do_checksum=True)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_data_transfer(server=server, params=params, do_checksum=True)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to upload snapshot; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    def copy_backup_image_to_volume(self, context, server, params):
        """
        Transfer the backup image to volume
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.copy_backup_image_to_volume(server=server,
                                            params=params, do_checksum=True)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.copy_backup_image_to_volume(server=server,
                                            params=params, do_checksum=True)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to copy backup image to volume; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    def vast_async_task_status(self, context, server, params):
        """
        Get data transfer status of VASTed instance component
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_async_task_status(server=server, params=params, do_checksum=True)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_async_task_status(server=server, params=params, do_checksum=True)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to get snapshot upload task status; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    @autolog.log_method(logger=Logger)
    def vast_finalize(self, context, server, params):
        """
        Finalize the VAST
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_finalize(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_finalize(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to complete snapshot operation; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    @autolog.log_method(logger=Logger)
    def vast_reset(self, context, server, params):
        """
        Reset the VAST snapshot
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.vast_reset(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.vast_reset(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to reset workload; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    def testbubble_attach_volume(self, context, server, params):
        """
        Attach a volume to testbubble instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.testbubble_attach_volume(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production, extensions=extensions, admin=True)
            return client.contego.testbubble_attach_volume(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to attach volume to test restore; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception

    @synchronized(novalock)
    def testbubble_reboot_instance(self, context, server, params):
        """
        Simple reboot of a testbubble instance
        :param server: The :class:`Server` (or its ID) to query.
        """
        try:
            extensions = _discover_extensions('1.1')
            client =  novaclient(context, self._production, extensions=extensions)
            return client.contego.testbubble_reboot_instance(server=server, params=params)
        except nova_exception.Unauthorized as unauth_ex:
            client =  novaclient(context, self._production,
                                  extensions=extensions, admin=True)
            return client.contego.testbubble_reboot_instance(server=server, params=params)
        except Exception as ex:
            LOG.exception(ex)
            msg = 'Unable to reboot test restore instance; Please check contego logs for more details'
            raise exception.ErrorOccurred(msg)
            #TODO(gbasava): Handle the exception
