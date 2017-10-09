# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


"""
Handles all requests relating to network + neutron.
"""

from threading import Lock
from functools import wraps

from oslo.config import cfg
from neutronclient import client
from neutronclient.v2_0 import client as clientv20
from neutronclient.common import exceptions as qexceptions

from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common import log as logging

neutron_opts = [
    cfg.StrOpt('neutron_production_url',
               default='http://localhost:9696',
               help='URL for connecting to production neutron'),
    cfg.StrOpt('neutron_tvault_url',
               default='http://localhost:9696',
               help='URL for connecting to tvault neutron'),
    cfg.StrOpt('neutron_admin_auth_url',
               default='http://localhost:5000/v2.0',
               help='auth url for connecting to quantum in admin context'),
    cfg.IntOpt('neutron_url_timeout',
               default=30,
               help='timeout value for connecting to neutron in seconds'),
    cfg.StrOpt('neutron_admin_username',
               default='admin',
               help='username for connecting to neutron in admin context'),
    cfg.StrOpt('neutron_admin_password',
               default='password',
               help='password for connecting to neutron in admin context',
               secret=True),
    cfg.StrOpt('neutron_admin_tenant_name',
               default='admin',
               help='tenant name for connecting to neutron in admin context'),
    cfg.StrOpt('neutron_region_name',
               default=None,
               help='region name for connecting to neutron in admin context'),
    cfg.BoolOpt('neutron_api_insecure',
                default=True,
                help='if set, ignore any SSL validation issues'),
    cfg.StrOpt('neutron_auth_strategy',
               default='keystone',
               help='auth strategy for connecting to '
                    'neutron in admin context'),
]

CONF = cfg.CONF
CONF.register_opts(neutron_opts)

LOG = logging.getLogger(__name__)

neutronlock = Lock()


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


def _get_auth_token():
    try:
        httpclient = client.HTTPClient(
            username=CONF.neutron_admin_username,
            tenant_name=CONF.neutron_admin_tenant_name,
            region_name=CONF.neutron_region_name,
            password=CONF.neutron_admin_password,
            domain_name=CONF.domain_name,
            auth_url=CONF.neutron_admin_auth_url,
            timeout=CONF.neutron_url_timeout,
            auth_strategy=CONF.neutron_auth_strategy,
            insecure=CONF.neutron_api_insecure)
        httpclient.authenticate()
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_("_get_auth_token() failed"))
    return httpclient.auth_token


def _get_client(token=None, production=True, cntx=None):
    if not token and CONF.neutron_auth_strategy:
        token = _get_auth_token()
    if production == True:
        neutron_url = CONF.neutron_production_url
    else:
        neutron_url = CONF.neutron_tvault_url

    if hasattr(cntx, 'user_domain_id'):
        if cntx.user_domain_id is None:
            user_domain_id = 'default'
        else:
            user_domain_id = cntx.user_domain_id
    elif hasattr(cntx, 'user_domain'):
        if cntx.user_domain is None:
            user_domain_id = 'default'
        else:
            user_domain_id = cntx.user_domain
    else:
        user_domain_id = 'default'

    params = {
        'endpoint_url': neutron_url,
        'timeout': CONF.neutron_url_timeout,
        'insecure': CONF.neutron_api_insecure,
        'auth_url': CONF.neutron_admin_auth_url,
        'domain_name': user_domain_id,
    }
    if token:
        params['token'] = token
    else:
        params['auth_strategy'] = None
    return clientv20.Client(**params)


def get_client(context, refresh_token=False, production=True):
    if refresh_token:
        token = None
    else:
        token = context.auth_token
    return _get_client(token=token, production=production, cntx=context)


def exception_handler(ignore_exception=False, refresh_token=True):
    def exception_handler_decorator(func):
        @wraps(func)
        def func_wrapper(*args, **argv):
            try:
                try:
                    client = get_client(
                        args[1], production=args[0]._production)
                    argv.update({'client': client})
                    return func(*args, **argv)
                except qexceptions.NeutronClientException as unauth_ex:
                    if refresh_token is True:
                        argv.pop('client')
                        client = get_client(args[1], refresh_token=True,
                                            production=args[0]._production)
                        argv.update({'client': client})
                        return func(*args, **argv)
            except Exception as ex:
                if ignore_exception is False:
                    LOG.exception(ex)
                    raise

        return func_wrapper
    return exception_handler_decorator


class API(base.Base):
    """API for interacting with the network manager."""

    def __init__(self, production=True):
        self._production = production

    def _get_ports(self, context, **search_opts):
        client = search_opts['client']
        return client.list_ports(**search_opts).get('ports')

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_ports(self, context, **search_opts):
        return self._get_ports(context, **search_opts)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_port(self, context, port_id, **kwargs):
        client = kwargs['client']
        return client.show_port(port_id)

    def _modify_port(self, context, port_id, **kwargs):
        LOG.debug("port_modify(): portid=%s, kwargs=%s" % (port_id, kwargs))
        body = {'port': kwargs}
        client = kwargs['client']
        return client.update_port(port_id, body=body).get('port')

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def modify_port(self, context, port_id, **kwargs):
        return self._modify_port(context, port_id, **kwargs)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def create_port(self, context, **kwargs):
        """
        Create a port on a specified network.
        :param request: request context
        :param network_id: network id a subnet is created on
        :param device_id: (optional) device id attached to the port
        :param tenant_id: (optional) tenant id of the port created
        :param name: (optional) name of the port created
        :returns: Port object
        """
        client = kwargs['client']
        kwargs.pop('client')
        body = {'port': kwargs}
        port = client.create_port(body=body).get('port')
        return port

    def _delete_port(self, context, port_id, **kwargs):
        client = kwargs['client']
        return client.delete_port(port_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def delete_port(self, context, port_id, **kwargs):
        return self._delete_port(context, port_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def create_subnet(self, context, **kwargs):
        client = kwargs['client']
        kwargs.pop('client')
        body = {'subnet': kwargs}
        subnet = client.create_subnet(body=body).get('subnet')
        subnet['label'] = subnet['name']
        return subnet

    def _get_subnet(self, context, subnet_id, **kwargs):
        client = kwargs['client']
        return client.show_subnet(subnet_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_subnet(self, context, subnet_id, **kwargs):
        return self._get_subnet(context, subnet_id, **kwargs)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def delete_subnet(self, context, subnet_id, **kwargs):
        client = kwargs['client']
        rv_subnets = self._get_subnet(context, subnet_id, **kwargs)
        search_opts = {'network_id': rv_subnets['subnet']['network_id']}
        rv_ports = self._get_ports(context, **search_opts)
        for port in rv_ports:
            self._delete_port(context, port['id'])
        client.delete_subnet(subnet_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_subnets_from_port(self, context, port, **kwargs):
        """Return the subnets for a given port."""

        client = kwargs['client']
        fixed_ips = port['fixed_ips']
        # No fixed_ips for the port means there is no subnet associated
        # with the network the port is created on.
        # Since list_subnets(id=[]) returns all subnets visible for the
        # current tenant, returned subnets may contain subnets which is not
        # related to the port. To avoid this, the method returns here.subnets
        if not fixed_ips:
            return []
        search_opts = {'id': [ip['subnet_id'] for ip in fixed_ips]}
        data = client.list_subnets(**search_opts)
        return data
        """
        ipam_subnets = data.get('subnets', [])
        subnets = []

        for subnet in ipam_subnets:
            subnet_dict = {'cidr': subnet['cidr'],
                           'gateway': network_model.IP(
                                address=subnet['gateway_ip'],
                                type='gateway'),
            }

            # attempt to populate DHCP server field
            search_opts = {'network_id': subnet['network_id'],
                           'device_owner': 'network:dhcp'}
            data = get_client(context, admin=True).list_ports(**search_opts)
            dhcp_ports = data.get('ports', [])
            for p in dhcp_ports:
                for ip_pair in p['fixed_ips']:
                    if ip_pair['subnet_id'] == subnet['id']:
                        subnet_dict['dhcp_server'] = ip_pair['ip_address']
                        break

            subnet_object = network_model.Subnet(**subnet_dict)
            for dns in subnet.get('dns_nameservers', []):
                subnet_object.add_dns(
                    network_model.IP(address=dns, type='dns'))

            # TODO(gongysh) get the routes for this subnet
            subnets.append(subnet_object)
        return subnets
        """

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def create_network(self, context, **kwargs):
        client = kwargs['client']
        kwargs.pop('client')
        body = {'network': kwargs}
        network = client.create_network(body=body).get('network')
        network['label'] = network['name']
        return network

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def delete_network(self, context, network_id, **kwargs):
        client = kwargs['client']
        client.delete_network(network_id, **kwargs)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_network(self, context, network_uuid, **kwargs):
        client = kwargs['client']
        network = client.show_network(network_uuid).get('network') or {}
        network['label'] = network['name']
        return network

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_networks(self, context, **kwargs):
        client = kwargs['client']
        networks = client.list_networks().get('networks')
        for network in networks:
            network['label'] = network['name']
        return networks

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_available_networks(
            self, context, project_id, net_ids=None, **kwargs):
        """
        Return a network list available for the tenant.
        The list contains networks owned by the tenant and public networks.
        If net_ids specified, it searches networks with requested IDs only.
        """
        client = kwargs['client']

        # If user has specified networks,
        # add them to **search_opts
        # (1) Retrieve non-public network list owned by the tenant.
        search_opts = {"tenant_id": project_id, 'shared': False}
        if net_ids:
            search_opts['id'] = net_ids
        nets = client.list_networks(**search_opts).get('networks', [])
        # (2) Retrieve public network list.
        search_opts = {'shared': True}
        if net_ids:
            search_opts['id'] = net_ids
        nets += client.list_networks(**search_opts).get('networks', [])

        _ensure_requested_network_ordering(
            lambda x: x['id'],
            nets,
            net_ids)

        return nets

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def create_router(self, context, **kwargs):
        client = get_client(context, admin=True, production=self._production)
        client = kwargs['client']
        kwargs.pop('client')
        body = {'router': kwargs}
        router = client.create_router(body=body).get('router')
        router['label'] = router['name']
        return router

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def delete_router(self, context, router_id, **kwargs):
        client = kwargs['client']
        search_opts = {
            'device_owner': 'network:router_interface',
            'device_id': router_id}
        ports = client.list_ports(**search_opts).get('ports')
        for port in ports:
            self._router_remove_interface(
                context, router_id, port_id=port['id'])
        client.delete_router(router_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def get_routers(self, context, **kwargs):
        """Fetches a list of all routers for a tenant."""
        client = kwargs['client']
        search_opts = {}
        routers = client.list_routers(**search_opts).get('routers', [])
        return routers

    @synchronized(neutronlock)
    def router_add_interface(self, context, router_id,
                             subnet_id=None, port_id=None, **kwargs):
        body = {}
        client = kwargs['client']
        if subnet_id:
            body['subnet_id'] = subnet_id
        if port_id:
            body['port_id'] = port_id
        client.add_interface_router(router_id, body)

    def _router_remove_interface(
            self, context, router_id, subnet_id=None, port_id=None, **kwargs):
        body = {}
        client = kwargs['client']
        if subnet_id:
            body['subnet_id'] = subnet_id
        if port_id:
            body['port_id'] = port_id
        client.remove_interface_router(router_id, body)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def router_remove_interface(
            self, context, router_id, subnet_id=None, port_id=None, **kwargs):
        return self._router_remove_interface(
            context, router_id, subnet_id, port_id, **kwargs)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def router_add_gateway(self, context, router_id, network_id, **kwargs):
        body = {'network_id': network_id}
        client = kwargs['client']
        client.add_gateway_router(router_id, body)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def security_group_list(self, context, **kwargs):
        client = kwargs['client']
        return client.list_security_groups(tenant_id=context.project_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def security_group_get(self, context, sg_id, **kwargs):
        client = kwargs['client']
        return client.show_security_group(sg_id).get('security_group')

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def security_group_create(self, context, name, desc, **kwargs):
        body = {'security_group': {'name': name,
                                   'description': desc}}
        client = kwargs['client']
        return client.create_security_group(body)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def security_group_delete(self, context, sg_id, **kwargs):
        client = kwargs['client']
        return client.delete_security_group(sg_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def security_group_update(self, context, sg_id, name, desc, **kwargs):
        body = {'security_group': {'name': name,
                                   'description': desc}}
        client = kwargs['client']
        return client.update_security_group(sg_id, body)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def security_group_rule_create(self, context, parent_group_id,
                                   direction, ethertype,
                                   ip_protocol, from_port, to_port,
                                   cidr, group_id, **kwargs):
        if not cidr:
            cidr = None
        if from_port < 0:
            from_port = None
        if to_port < 0:
            to_port = None
        if isinstance(ip_protocol, int) and ip_protocol < 0:
            ip_protocol = None

        body = {'security_group_rule':
                {'security_group_id': parent_group_id,
                 'direction': direction,
                 'ethertype': ethertype,
                 'protocol': ip_protocol,
                 'port_range_min': from_port,
                 'port_range_max': to_port,
                 'remote_ip_prefix': cidr,
                 'remote_group_id': group_id}}
        client = kwargs['client']
        rule = client.create_security_group_rule(body)
        return rule.get('security_group_rule')

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def security_group_rule_delete(self, context, sgr_id, **kwargs):
        client = kwargs['client']
        return client.delete_security_group_rule(sgr_id)

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def server_security_groups(self, context, instance_id, **kwargs):
        """Gets security groups of an instance."""
        ports = self._get_ports(context, device_id=instance_id, **kwargs)
        sg_ids = []
        for p in ports:
            sg_ids += p['security_groups']

        return list(set(sg_ids))

    @synchronized(neutronlock)
    @exception_handler(ignore_exception=False)
    def server_update_security_groups(
            self, context, instance_id, new_security_group_ids, **kwargs):
        ports = self._get_ports(context, device_id=instance_id, **kwargs)
        for p in ports:
            params = {'security_groups': new_security_group_ids}
            self._modify_port(context, p.id, **params)
