# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


"""
Handles all requests relating to network + neutron.
"""

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
                default=False,
                help='if set, ignore any SSL validation issues'),
    cfg.StrOpt('neutron_auth_strategy',
               default='keystone',
               help='auth strategy for connecting to '
                    'neutron in admin context'),
]

CONF = cfg.CONF
CONF.register_opts(neutron_opts)

LOG = logging.getLogger(__name__)


def _get_auth_token():
    try:
        httpclient = client.HTTPClient(
            username=CONF.neutron_admin_username,
            tenant_name=CONF.neutron_admin_tenant_name,
            region_name=CONF.neutron_region_name,
            password=CONF.neutron_admin_password,
            auth_url=CONF.neutron_admin_auth_url,
            timeout=CONF.neutron_url_timeout,
            auth_strategy=CONF.neutron_auth_strategy,
            insecure=CONF.neutron_api_insecure)
        httpclient.authenticate()
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_("_get_auth_token() failed"))
    return httpclient.auth_token

def _get_client(token=None, production= True):
    if not token and CONF.neutron_auth_strategy:
        token = _get_auth_token()
    if production == True:
        neutron_url = CONF.neutron_production_url
    else:
        neutron_url = CONF.neutron_tvault_url
    params = {
        'endpoint_url': neutron_url,
        'timeout': CONF.neutron_url_timeout,
        'insecure': CONF.neutron_api_insecure,
    }
    if token:
        params['token'] = token
    else:
        params['auth_strategy'] = None
    return clientv20.Client(**params)

def get_client(context, admin=False, production = True):
    if admin:
        token = None
    else:
        token = context.auth_token
    return _get_client(token=token, production=production)
    
class API(base.Base):
    """API for interacting with the network manager."""
    
    def __init__(self, production = True):
        self._production = production        

    def get_ports(self, context, **search_opts):
        return get_client(context, admin=True, production=self._production).list_ports(**search_opts)

    def get_port(self, context, port_id):
        return get_client(context, admin=True, production=self._production).show_port(port_id)
    
    def create_subnet(self, context, **kwargs):
        client = get_client(context, admin=True, production=self._production)
        body = {'subnet': kwargs}
        subnet = client.create_subnet(body=body).get('subnet')        
        subnet['label'] = subnet['name']
        return subnet    
    
    def get_subnets_from_port(self, context, port):
        """Return the subnets for a given port."""

        fixed_ips = port['fixed_ips']
        # No fixed_ips for the port means there is no subnet associated
        # with the network the port is created on.
        # Since list_subnets(id=[]) returns all subnets visible for the
        # current tenant, returned subnets may contain subnets which is not
        # related to the port. To avoid this, the method returns here.subnets
        if not fixed_ips:
            return []
        search_opts = {'id': [ip['subnet_id'] for ip in fixed_ips]}
        data = get_client(context, admin=True, production=self._production).list_subnets(**search_opts)
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

    def create_network(self, context, **kwargs):
        client = get_client(context, admin=True, production=self._production)
        body = {'network': kwargs}
        network = client.create_network(body=body).get('network')        
        network['label'] = network['name']
        return network

    def get_network(self, context, network_uuid):
        client = get_client(context, admin=True, production=self._production)
        network = client.show_network(network_uuid).get('network') or {}
        network['label'] = network['name']
        return network

    def get_networks(self, context):
        client = get_client(context, admin=True, production=self._production)
        networks = client.list_networks().get('networks')
        for network in networks:
            network['label'] = network['name']
        return networks
    
    def get_available_networks(self, context, project_id, net_ids=None):
        """
        Return a network list available for the tenant.
        The list contains networks owned by the tenant and public networks.
        If net_ids specified, it searches networks with requested IDs only.
        """
        client = get_client(context, admin=True, production=self._production)

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
    
    def create_router(self, context, **kwargs):
        client = get_client(context, admin=True, production=self._production)
        body = {'router': kwargs}
        router = client.create_router(body=body).get('router')        
        router['label'] = router['name']
        return router
        
    def get_routers(self, context):
        """Fetches a list of all routers for a tenant."""
        client = get_client(context, admin=True, production=self._production)
        search_opts = {}
        routers = client.list_routers(**search_opts).get('routers', [])
        return routers

    def router_add_interface(self, context, router_id, subnet_id=None, port_id=None):
        body = {}
        if subnet_id:
            body['subnet_id'] = subnet_id
        if port_id:
            body['port_id'] = port_id
        get_client(context, admin=True, production=self._production).add_interface_router(router_id, body)
    
    
    def router_remove_interface(self, request, router_id, subnet_id=None, port_id=None):
        body = {}
        if subnet_id:
            body['subnet_id'] = subnet_id
        if port_id:
            body['port_id'] = port_id
        get_client(context, admin=True, production=self._production).remove_interface_router(router_id, body)
    
    
    def router_add_gateway(self, context, router_id, network_id):
        body = {'network_id': network_id}
        get_client(context, admin=True, production=self._production).add_gateway_router(router_id, body)
    
        

       
    
            
