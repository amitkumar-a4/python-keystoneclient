# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to compute + nova.
"""

import time

from novaclient import exceptions as nova_exception
from novaclient import service_catalog
from novaclient.v1_1 import client as nova_client
from oslo.config import cfg

from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr.openstack.common import log as logging

nova_opts = [
    cfg.StrOpt('nova_production_endpoint_template',
               default= 'http://localhost:8774/v2/%(project_id)s',
               help='nova production endpoint e.g. http://localhost:8774/v2/%(project_id)s'),
    cfg.StrOpt('nova_tvault_endpoint_template',
               default= 'http://localhost:8774/v2/%(project_id)s',
               help='nova production endpoint e.g. http://localhost:8774/v2/%(project_id)s'),             
    cfg.StrOpt('os_region_name',
               default=None,
               help='region name of this node'),
    cfg.BoolOpt('nova_api_insecure',
                default=False,
                help='Allow to perform insecure SSL requests to nova'),
              
]

CONF = cfg.CONF
CONF.register_opts(nova_opts)

LOG = logging.getLogger(__name__)

    
def novaclient(context, production):
    if production == True:
        url = CONF.nova_production_endpoint_template % context.to_dict()
    else:
        url = CONF.nova_tvault_endpoint_template % context.to_dict() 

    LOG.debug(_('Novaclient connection created using URL: %s') % url)

    c = nova_client.Client(context.user_id,
                           context.auth_token,
                           project_id=context.project_id,
                           auth_url=url,
                           insecure=CONF.nova_api_insecure)
    # noauth extracts user_id:tenant_id from auth_token
    c.client.auth_token = context.auth_token or '%s:%s' % (context.user_id,
                                                           context.project_id)
    c.client.management_url = url
    return c


class API(base.Base):
    """API for interacting with the volume manager."""
    
    def __init__(self, production = True):
        self._production = production    

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
            item = novaclient(context, self._production).servers.create(name, image, flavor, 
                                                      meta, files,
                                                      reservation_id, min_count,
                                                      max_count, security_groups, userdata,
                                                      key_name, availability_zone,
                                                      block_device_mapping, nics=nics, scheduler_hints=scheduler_hints,
                                                      config_drive=config_drive, **kwargs)
            time.sleep(15)#TODO(gbasava): Creation is asynchronous. Wait and check for the status
            #Perform translation required if any
            return item 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return       
            
    def get_server(self, context, name):
        """
        Get the server given the name
        :rtype: :class:`Server`
        """   
    
        try:
            return novaclient(context, self._production).servers.find(name=name) 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return 
        
    def get_server_by_id(self, context, id):
        """
        :param id to query.
        :rtype: :class:`Server`
        """   
    
        try:
            return novaclient(context, self._production).servers.find(id=id) 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return         

    def stop(self, context, server):
        """
        Stop the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """   
    
        try:
            return novaclient(context, self._production).servers.stop(server=server) 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return         
        
    def start(self, context, server):
        """
        Start the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """   
    
        try:
            return novaclient(context, self._production).servers.start(server=server) 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return                 
        
    def suspend(self, context, server):
        """
        Suspend the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """   
    
        try:
            return novaclient(context, self._production).servers.suspend(server=server) 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return         

    def resume(self, context, server):
        """
        Resume the server given the id
        :param server: The :class:`Server` (or its ID) to query.
        """   
    
        try:
            return novaclient(context, self._production).servers.resume(server=server) 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return         
                    
    def attach_volume(self, context, server_id, volume_id, device):
        """
        Attach a volume identified by the volume ID to the given server ID

        :param server_id: The ID of the server
        :param volume_id: The ID of the volume to attach.
        :param device: The device name
        :rtype: :class:`Volume`
        """   
  
        try:
            return novaclient(context, self._production).volumes.create_server_volume(server_id, volume_id, device) 
        except Exception:
            #TODO(gbasava): Handle the exception   
            return 
                    
    def get_image(self, context, id):
        """
        Get the image given the name

        :param name: name of the image
        :rtype: :class:`Image`
        """   
    
        try:
            return novaclient(context, self._production).images.find(id=id) 
        except Exception:
            #TODO(gbasava): Handle the exception 
            return 
                      
    def get_flavor(self, context, name):
        """
        Get the flavors given the name

        :param name: name of the flavors
        :rtype: :class:`Flavor`
        """   
    
        try:
            return novaclient(context, self._production).flavors.find(name=name) 
        except Exception:
            #TODO(gbasava): Handle the exception   
            return  
       
    def get_interfaces(self, context, server):   
        """
        List attached network interfaces

        :param server: The :class:`Server` (or its ID) to query.
        """        
        try:
            return novaclient(context, self._production).servers.interface_list(server=server) 
        except Exception:
            #TODO(gbasava): Handle the exception   
            return              
                                              