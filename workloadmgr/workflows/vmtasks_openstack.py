# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement application
specific flows

"""

import os
import uuid
import time
import cPickle as pickle
from netaddr import IPNetwork, IPAddress
import threading
import time
import datetime

from neutronclient.common import exceptions as neutron_exceptions

from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import timeutils
from workloadmgr import autolog
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.volume import cinder
from workloadmgr.image import glance
from workloadmgr.vault import vault
from workloadmgr.virt import driver
from workloadmgr import utils
from workloadmgr import exception


LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

lock = threading.Lock()

def _get_pit_resource_id(metadata, key):
    for metadata_item in metadata:
        if metadata_item['key'] == key:
            pit_id = metadata_item['value']
            return pit_id
        
def _get_pit_resource(snapshot_vm_common_resources, pit_id):
    for snapshot_vm_resource in snapshot_vm_common_resources:
        if snapshot_vm_resource.resource_pit_id == pit_id:
            return snapshot_vm_resource 
            

@autolog.log_method(Logger, 'vmtasks_openstack.apply_retention_policy')
def apply_retention_policy(cntx, db, instances, snapshot):
    if instances[0]['hypervisor_type'] == 'QEMU':
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        virtdriver.apply_retention_policy(cntx, db, instances, snapshot)
    else:
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        virtdriver.apply_retention_policy(cntx, db, instances, snapshot)
             
@autolog.log_method(Logger, 'vmtasks_openstack.snapshot_vm_networks')
def snapshot_vm_networks(cntx, db, instances, snapshot):
    try:
        lock.acquire()
        compute_service = nova.API(production=True)
        network_service =  neutron.API(production=True)  
        subnets = []
        networks = []
        routers = []

        # refresh the token. token may have been invalidated during long running
        # tasks during upload and post snapshot processing
        user_id = cntx.user
        project_id = cntx.tenant
        cntx = nova._get_tenant_context(user_id, project_id)
        
        def _snapshot_neutron_networks(instance):
            interfaces = compute_service.get_interfaces(cntx, instance['vm_id'])
            nics = []
            for interface in interfaces:
                nic = {} #nic is dictionary to hold the following data
                #ip_address, mac_address, subnet_id, network_id, router_id, ext_subnet_id, ext_network_id
                
                nic.setdefault('ip_address', interface.fixed_ips[0]['ip_address'])
                nic.setdefault('mac_address', interface.mac_addr)
        
                port_data = network_service.get_port(cntx, interface.port_id)
                #TODO(giri): We may not need ports
                #utils.append_unique(ports, port_data['port']) 
                #nic.setdefault('port_id', interface.port_id)
                
                subnets_data = network_service.get_subnets_from_port(cntx,port_data['port'])
                #TODO(giri): we will support only one fixedip per interface for now
                if subnets_data['subnets'][0]:
                    utils.append_unique(subnets, subnets_data['subnets'][0])
                    nic.setdefault('subnet_id', subnets_data['subnets'][0]['id'])
                    nic.setdefault('subnet_name', subnets_data['subnets'][0]['name'])
        
                network = network_service.get_network(cntx,port_data['port']['network_id'])
                if network : 
                    utils.append_unique(networks, network)
                    nic.setdefault('network_id', network['id'])
                    nic.setdefault('network_name', network['name'])
                
                #Let's find our router
                routers_data = network_service.get_routers(cntx)
                router_found = None
                for router in routers_data:
                    if router_found : break
                    search_opts = {'device_id': router['id'], 'network_id':network['id']}
                    router_ports = network_service.get_ports(cntx,**search_opts)
                    for router_port in router_ports:
                        if router_found : break
                        router_port_fixed_ips = router_port['fixed_ips']
                        if router_port_fixed_ips:
                            for router_port_ip in router_port_fixed_ips:
                                if router_found : break
                                for subnet in subnets_data['subnets']:
                                    if router_port_ip['subnet_id'] == subnet['id']:
                                        router_found = router
                                        break;
                                
                if router_found:
                    utils.append_unique(routers, router_found)
                    nic.setdefault('router_id', router_found['id'])
                    nic.setdefault('router_name', router_found['name'])
                    if router_found['external_gateway_info'] and router_found['external_gateway_info']['network_id']:
                        search_opts = {'device_id': router_found['id'], 'network_id': router_found['external_gateway_info']['network_id']}
                        router_ext_ports = network_service.get_ports(cntx,**search_opts)
                        if router_ext_ports and len(router_ext_ports) and router_ext_ports[0]:
                            ext_port = router_ext_ports[0]
                            #utils.append_unique(ports, ext_port) TODO(giri): We may not need ports 
                            ext_subnets_data = network_service.get_subnets_from_port(cntx,ext_port)
                            #TODO(giri): we will capture only one subnet for now
                            if ext_subnets_data['subnets'][0]:
                                utils.append_unique(subnets, ext_subnets_data['subnets'][0])
                                nic.setdefault('ext_subnet_id', ext_subnets_data['subnets'][0]['id'])
                                nic.setdefault('ext_subnet_name', ext_subnets_data['subnets'][0]['name'])
                            ext_network = network_service.get_network(cntx,ext_port['network_id'])
                            if ext_network:
                                utils.append_unique(networks, ext_network)
                                nic.setdefault('ext_network_id', ext_network['id'])
                                nic.setdefault('ext_network_name', ext_network['name'])
                nics.append(nic)

            return nics
        
        def _snapshot_nova_networks(instance):
            interfaces = compute_service.get_interfaces(cntx, instance['vm_id'])
            networks = compute_service.get_networks(cntx)

            nics = []
            uniquemacs = set()
            for networkname, interfaceinfo in interfaces.iteritems():
                for interface in interfaceinfo:
                    if not interface['OS-EXT-IPS-MAC:mac_addr'] in uniquemacs: 
                        nic = {} #nic is dictionary to hold the following data
                
                        nic.setdefault('ip_address', interface['addr'])
                        nic.setdefault('mac_address', interface['OS-EXT-IPS-MAC:mac_addr'])
                        nic.setdefault('network_name', networkname)
                        for net in networks:
                            if net.label == networkname:
                                nic.setdefault('network_id', net.id)
                                break
                        nics.append(nic)
                        uniquemacs.add(interface['OS-EXT-IPS-MAC:mac_addr'])
            return nics

        #Store the nics in the DB

        network_type = ""
        for instance in instances: 
            try:
                network_service.get_networks(cntx)
                nics = _snapshot_neutron_networks(instance)
                network_type = "neutron"
            except neutron_exceptions.EndpointNotFound:
                # This is configured to use nova network
                nics = _snapshot_nova_networks(instance)
                network_type = "nova"

            for nic in nics:
                snapshot_vm_resource_values = { 'id': str(uuid.uuid4()),
                                                'vm_id': instance['vm_id'],
                                                'snapshot_id': snapshot['id'],       
                                                'resource_type': 'nic',
                                                'resource_name':  nic['mac_address'],
                                                'resource_pit_id': '',
                                                'metadata': {'network_type': network_type},
                                                'status': 'available'}
                snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, 
                                                    snapshot_vm_resource_values)
                # create an entry in the vm_network_resource_snaps table
                vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
                #ip_address, mac_address, subnet_id, network_id, router_id, ext_subnet_id, ext_network_id
                vm_network_resource_snap_metadata = nic
                vm_network_resource_snap_values = {'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                     'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                     'pickle': pickle.dumps(nic, 0),
                                                     'metadata': vm_network_resource_snap_metadata,       
                                                     'status': 'available'}     
                                                             
                vm_network_resource_snap = db.vm_network_resource_snap_create(cntx, vm_network_resource_snap_values)                
                                
        #store the subnets, networks and routers in the DB
        for subnet in subnets:
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                           'vm_id': snapshot['id'], 
                                           'snapshot_id': snapshot['id'],       
                                           'resource_type': 'subnet',
                                           'resource_name':  subnet['name'],
                                           'resource_pit_id': subnet['id'],
                                           'metadata': {},
                                           'status': 'available'}
            snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, 
                                                snapshot_vm_resource_values)
            # create an entry in the vm_network_resource_snaps table
            vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_network_resource_snap_values = {  'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                 'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                 'pickle': pickle.dumps(subnet, 0),
                                                 'metadata': vm_network_resource_snap_metadata,       
                                                 'status': 'available'}     
                                                         
            vm_network_resource_snap = db.vm_network_resource_snap_create(cntx, vm_network_resource_snap_values)                
            
        for network in networks:
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                           'vm_id': snapshot['id'],
                                           'snapshot_id': snapshot['id'],       
                                           'resource_type': 'network',
                                           'resource_name':  network['name'],
                                           'resource_pit_id': network['id'],
                                           'metadata': {},
                                           'status': 'available'}
            snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, 
                                                snapshot_vm_resource_values)                                                
            # create an entry in the vm_network_resource_snaps table
            vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_network_resource_snap_values = {  'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                 'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                 'pickle': pickle.dumps(network, 0),
                                                 'metadata': vm_network_resource_snap_metadata,       
                                                 'status': 'available'}     
                                                         
            vm_network_resource_snap = db.vm_network_resource_snap_create(cntx, vm_network_resource_snap_values)                
        
        for router in routers:
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                           'vm_id': snapshot['id'],
                                           'snapshot_id': snapshot['id'],       
                                           'resource_type': 'router',
                                           'resource_name':  router['name'],
                                           'resource_pit_id': router['id'],
                                           'metadata': {},
                                           'status': 'available'}
            snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, 
                                                snapshot_vm_resource_values)                                                
            # create an entry in the vm_network_resource_snaps table
            vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_network_resource_snap_values = {  'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                 'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                 'pickle': pickle.dumps(router, 0),
                                                 'metadata': vm_network_resource_snap_metadata,       
                                                 'status': 'available'}     
                                                         
            vm_network_resource_snap = db.vm_network_resource_snap_create(cntx, vm_network_resource_snap_values)
    finally:
        lock.release()

@autolog.log_method(Logger, 'vmtasks_openstack.snapshot_vm_flavors')
def snapshot_vm_flavors(cntx, db, instances, snapshot):

    compute_service = nova.API(production=True)
    for instance in instances:
        # Create  a flavor resource
        flavor = compute_service.get_flavor_by_id(cntx, instance['vm_flavor_id'])
        metadata = {'name':flavor.name, 'vcpus':flavor.vcpus, 'ram':flavor.ram, 
                    'disk':flavor.disk, 'ephemeral':flavor.ephemeral, 'swap': flavor.swap}
        snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                       'vm_id': instance['vm_id'],
                                       'snapshot_id': snapshot['id'],       
                                       'resource_type': 'flavor',
                                       'resource_name':  flavor.name,
                                       'metadata': metadata,
                                       'status': 'available'}
        snapshot_vm_resource = db.snapshot_vm_resource_create(cntx,  snapshot_vm_resource_values) 
        
@autolog.log_method(Logger, 'vmtasks_openstack.snapshot_vm_security_groups')        
def snapshot_vm_security_groups(cntx, db, instances, snapshot):
    compute_service = nova.API(production=True)
    network_service =  neutron.API(production=True)  
    
    def _snapshot_neutron_security_groups():
        security_group_ids = []
        for instance in instances:
            server_security_group_ids = network_service.server_security_groups(cntx, instance['vm_id'])
            security_group_ids += server_security_group_ids
            for security_group_id in server_security_group_ids:
                security_group = network_service.security_group_get(cntx, security_group_id)
                snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                               'vm_id': instance['vm_id'],
                                               'snapshot_id': snapshot['id'],       
                                               'resource_type': 'security_group',
                                               'resource_name':  security_group['id'],
                                               'resource_pit_id': security_group['id'],
                                               'metadata': {'name': security_group['name'],
                                                            'security_group_type': 'neutron',
                                                            'description' : security_group['description']},
                                               'status': 'available'}
                snapshot_vm_resource = db.snapshot_vm_resource_create(cntx,  snapshot_vm_resource_values)        
        
        unique_security_group_ids = list(set(security_group_ids))
        for security_group_id in unique_security_group_ids:
            security_group = network_service.security_group_get(cntx, security_group_id)
            security_group_rules = security_group['security_group_rules']
            vm_security_group_snap_values = {'id': str(uuid.uuid4()),
                                           'vm_id': snapshot['id'],
                                           'snapshot_id': snapshot['id'],       
                                           'resource_type': 'security_group',
                                           'resource_name':  security_group['id'],
                                           'resource_pit_id': security_group['id'],
                                           'metadata': {'name': security_group['name'],
                                                        'security_group_type': 'neutron',
                                                        'description' : security_group['description']},
                                           'status': 'available'}
            vm_security_group_snap = db.snapshot_vm_resource_create(cntx,  vm_security_group_snap_values)
        
            for security_group_rule in security_group_rules:
                vm_security_group_rule_snap_metadata = {'security_group_type': 'neutron',}
                vm_security_group_rule_snap_values = {  'id': str(uuid.uuid4()),
                                                        'vm_security_group_snap_id': vm_security_group_snap.id,
                                                        'pickle': pickle.dumps(security_group_rule, 0),
                                                        'metadata': vm_security_group_rule_snap_metadata,       
                                                        'status': 'available'}     
                                                         
                vm_security_group_rule_snap = db.vm_security_group_rule_snap_create(cntx, vm_security_group_rule_snap_values)
                if security_group_rule['remote_group_id']:
                    if (security_group_rule['remote_group_id'] in unique_security_group_ids) == False:
                        unique_security_group_ids.append(vm_security_group_snap['remote_group_id'])

    def _snapshot_nova_security_groups():
        security_group_ids = []
        security_groups = compute_service.get_security_groups(cntx)
        for instance in instances:
            server = compute_service.get_server_by_id(cntx, instance['vm_id'])

            for secgrp in server.security_groups:
                for group in security_groups:
                    if secgrp['name'] == group.name:
                        security_group_ids.append(secgrp['name'])
                        snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                               'vm_id': instance['vm_id'],
                                               'snapshot_id': snapshot['id'],       
                                               'resource_type': 'security_group',
                                               'resource_name':  group.id,
                                               'resource_pit_id': group.id,
                                               'metadata': {'name': group.name,
                                                            'security_group_type': 'nova',
                                                            'description' : group.description},
                                               'status': 'available'}
                        snapshot_vm_resource = db.snapshot_vm_resource_create(cntx,  snapshot_vm_resource_values)        
                        break
        
        unique_security_group_ids = list(set(security_group_ids))
        for security_group_id in unique_security_group_ids:
            for group in security_groups:
                if security_group_id == group.name:
                    security_group_rules = group.rules
                    vm_security_group_snap_values = {'id': str(uuid.uuid4()),
                                                  'vm_id': snapshot['id'],
                                                  'snapshot_id': snapshot['id'],       
                                                  'resource_type': 'security_group',
                                                  'resource_name':  group.id,
                                                  'resource_pit_id': group.id,
                                                  'metadata': {'name': group.name,
                                                               'security_group_type': 'nova',
                                                               'description' : group.description},
                                                  'status': 'available'}
                    vm_security_group_snap = db.snapshot_vm_resource_create(cntx,  vm_security_group_snap_values)
        
                    for security_group_rule in security_group_rules:
                        vm_security_group_rule_snap_metadata = {'security_group_type': 'nova',}
                        vm_security_group_rule_snap_values = {  'id': str(uuid.uuid4()),
                                                                'vm_security_group_snap_id': vm_security_group_snap.id,
                                                                'pickle': pickle.dumps(security_group_rule, 0),
                                                                'metadata': vm_security_group_rule_snap_metadata,       
                                                                'status': 'available'}     
                                                         
                        vm_security_group_rule_snap = db.vm_security_group_rule_snap_create(cntx, vm_security_group_rule_snap_values)

    try:
        network_service.get_networks(cntx)
        _snapshot_neutron_security_groups()
    except neutron_exceptions.EndpointNotFound:
        # This is configured to use nova network
        _snapshot_nova_security_groups()

@autolog.log_method(Logger, 'vmtasks_openstack.pause_vm')
def pause_vm(cntx, db, instance):
    compute_service = nova.API(production=True)
    if 'imported_from_vcenter' in instance['vm_metadata'] and \
       instance['vm_metadata']['imported_from_vcenter'] == "True":
        suspend_vm(cntx, db, instance)
    elif instance['hypervisor_type'] == 'VMware vCenter Server':
        suspend_vm(cntx, db, instance)
    else:
        compute_service.pause(cntx, instance['vm_id'])
        instance_ref =  compute_service.get_server_by_id(cntx, instance['vm_id'])
        start_time = timeutils.utcnow()
        while hasattr(instance_ref,'status') and instance_ref.status != 'PAUSED':
            time.sleep(5)
            instance_ref =  compute_service.get_server_by_id(cntx, instance['vm_id'])
            if hasattr(instance_ref,'status') and instance_ref.status == 'ERROR':
                raise Exception(_("Error suspending instance " + instance_ref.id))
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=4):
                raise exception.ErrorOccurred(reason='Timeout waiting for the instance to pause')                       

@autolog.log_method(Logger, 'vmtasks_openstack.unpause_vm')
def unpause_vm(cntx, db, instance):
    compute_service = nova.API(production=True)
    if 'imported_from_vcenter' in instance['vm_metadata'] and \
       instance['vm_metadata']['imported_from_vcenter'] == "True":
        suspend_vm(cntx, db, instance)
    elif instance['hypervisor_type'] == 'VMware vCenter Server':
        resume_vm(cntx, db, instance)
    else:
        compute_service.unpause(cntx, instance['vm_id'])

@autolog.log_method(Logger, 'vmtasks_openstack.suspend_vm')
def suspend_vm(cntx, db, instance):
    
    compute_service = nova.API(production=True)
    compute_service.suspend(cntx, instance['vm_id'])
    instance_ref =  compute_service.get_server_by_id(cntx, instance['vm_id'])
    start_time = timeutils.utcnow()
    while hasattr(instance_ref,'status') and instance_ref.status != 'SUSPENDED':
        time.sleep(5)
        instance_ref =  compute_service.get_server_by_id(cntx, instance['vm_id'])
        if hasattr(instance_ref,'status') and instance_ref.status == 'ERROR':
            raise Exception(_("Error suspending instance " + instance_ref.id))
        now = timeutils.utcnow()
        if (now - start_time) > datetime.timedelta(minutes=4):
            raise exception.ErrorOccurred(reason='Timeout waiting for the instance to pause')         
    
@autolog.log_method(Logger, 'vmtasks_openstack.resume_vm')
def resume_vm(cntx, db, instance):
    
    compute_service = nova.API(production=True)
    compute_service.resume(cntx, instance['vm_id'])  
    
@autolog.log_method(Logger, 'vmtasks_openstack.pre_snapshot_vm')
def pre_snapshot_vm(cntx, db, instance, snapshot):
    # pre processing of snapshot
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        return virtdriver.pre_snapshot_vm(cntx, db, instance, snapshot)    
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        return virtdriver.pre_snapshot_vm(cntx, db, instance, snapshot)   
    
@autolog.log_method(Logger, 'vmtasks_openstack.freeze_vm')
def freeze_vm(cntx, db, instance, snapshot):
    # freeze instance
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        return virtdriver.freeze_vm(cntx, db, instance, snapshot)    
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        return virtdriver.freeze_vm(cntx, db, instance, snapshot)  
    
@autolog.log_method(Logger, 'vmtasks_openstack.thaw_vm')
def thaw_vm(cntx, db, instance, snapshot):
    # thaw instance
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        return virtdriver.thaw_vm(cntx, db, instance, snapshot)    
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        return virtdriver.thaw_vm(cntx, db, instance, snapshot)          

@autolog.log_method(Logger, 'vmtasks_openstack.snapshot_vm')
def snapshot_vm(cntx, db, instance, snapshot):

    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        return virtdriver.snapshot_vm(cntx, db, instance, snapshot)
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        return virtdriver.snapshot_vm(cntx, db, instance, snapshot) 

@autolog.log_method(Logger, 'vmtasks_openstack.get_snapshot_data_size')
def get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data):  
        
    LOG.debug(_("instance: %(instance_id)s") %{'instance_id': instance['vm_id'],})
    vm_data_size = 0;
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        vm_data_size = virtdriver.get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data)
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        vm_data_size = virtdriver.get_snapshot_data_size(cntx, db, instance, snapshot, snapshot_data)
         
    LOG.debug(_("vm_data_size: %(vm_data_size)s") %{'vm_data_size': vm_data_size,})
    return vm_data_size
        
@autolog.log_method(Logger, 'vmtasks_openstack.upload_snapshot')
def upload_snapshot(cntx, db, instance, snapshot, snapshot_data_ex):

    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        return virtdriver.upload_snapshot(cntx, db, instance, snapshot, snapshot_data_ex)
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        return virtdriver.upload_snapshot(cntx, db, instance, snapshot, snapshot_data_ex)

@autolog.log_method(Logger, 'vmtasks_openstack.post_snapshot')
def post_snapshot(cntx, db, instance, snapshot, snapshot_data):
        
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        virtdriver.post_snapshot_vm(cntx, db, instance, snapshot, snapshot_data)
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        virtdriver.post_snapshot_vm(cntx, db, instance, snapshot, snapshot_data)

@autolog.log_method(Logger, 'vmtasks_openstack.delete_restored_vm')
def delete_restored_vm(cntx, db, instance, restore):

    if instance['hypervisor_type'] == 'QEMU':
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        virtdriver.delete_restored_vm(cntx, db, instance, restore)
    else:
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        virtdriver.delete_restored_vm(cntx, db, instance, restore)

@autolog.log_method(Logger, 'vmtasks_openstack.restore_vm_flavor')
def restore_vm_flavor(cntx, db, instance, restore):

    restore_obj = db.restore_update( cntx, restore['id'],
                       {'progress_msg': 'Restoring VM Flavor for Instance ' + instance['vm_id']})

    compute_service = nova.API(production = (restore['restore_type'] != 'test'))

    #default values
    vcpus = '1'
    ram = '512'
    disk = '1'
    ephemeral = '0'
    swap = '0'
    
    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'], restore['snapshot_id'])
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type == 'flavor':
            snapshot_vm_flavor = db.snapshot_vm_resource_get(cntx, snapshot_vm_resource.id)
            vcpus = db.get_metadata_value(snapshot_vm_flavor.metadata, 'vcpus', vcpus)
            ram = db.get_metadata_value(snapshot_vm_flavor.metadata, 'ram', ram)
            disk = db.get_metadata_value(snapshot_vm_flavor.metadata, 'disk', ram)
            ephemeral = db.get_metadata_value(snapshot_vm_flavor.metadata, 'ephemeral', ram)
            swap =  db.get_metadata_value(snapshot_vm_flavor.metadata, 'swap', swap)           
            break
    
    
    restore_options = pickle.loads(str(restore_obj.pickle))
    instance_options = utils.get_instance_restore_options(restore_options, instance['vm_id'],'openstack')
    if instance_options and 'flavor' in instance_options:
        if instance_options['flavor'].get('vcpus', "") != "":
            vcpus = instance_options['flavor'].get('vcpus', vcpus)
        if instance_options['flavor'].get('ram', "") != "":
            ram = instance_options['flavor'].get('ram', ram)
        if instance_options['flavor'].get('disk', "") != "":
            disk = instance_options['flavor'].get('disk', disk)
        if instance_options['flavor'].get('ephemeral', "") != "":
            ephemeral = instance_options['flavor'].get('ephemeral', ephemeral)
        if instance_options['flavor'].get('swap', "") != "":
            swap = instance_options['flavor'].get('swap', swap)
 
    restored_compute_flavor = None
    for flavor in compute_service.get_flavors(cntx):
        if ((str(flavor.vcpus) ==  vcpus) and
            (str(flavor.ram) ==  ram) and
            (str(flavor.disk) ==  disk) and
            (str(flavor.ephemeral) == ephemeral) and
            (str(flavor.swap) == swap)):
            restored_compute_flavor = flavor
            break            
    if not restored_compute_flavor:
        #TODO(giri):create a new flavor
        name = str(uuid.uuid4())
        restored_compute_flavor = compute_service.create_flavor(cntx, name, ram, vcpus, disk, ephemeral)
        restored_vm_resource_values = {'id': restored_compute_flavor.id,
                                       'vm_id': restore['id'],
                                       'restore_id': restore['id'],       
                                       'resource_type': 'flavor',
                                       'resource_name':  name,
                                       'metadata': {},
                                       'status': 'available'}
        restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)         
    return restored_compute_flavor 

@autolog.log_method(Logger, 'vmtasks_openstack.get_vm_nics')
def get_vm_nics(cntx, db, instance, restore, restored_net_resources):     

    db.restore_update( cntx, restore['id'],
                       {'progress_msg': 'Restoring network interfaces for Instance ' + instance['vm_id']})
    restored_nics = []
    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'], restore['snapshot_id'])
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type == 'nic':
            vm_nic_snapshot = db.vm_network_resource_snap_get(cntx, snapshot_vm_resource.id)
            
            network_type = db.get_metadata_value(vm_nic_snapshot.metadata,
                                                  'network_type')

            nic_data = pickle.loads(str(vm_nic_snapshot.pickle))
            nic_info = {}

            # adjust IP address here
            compute_service = nova.API(production=True)
            networks = compute_service.get_networks(cntx)
            nic_info.setdefault('v4-fixed-ip', db.get_metadata_value(vm_nic_snapshot.metadata, 'ip_address'))
            network_id = db.get_metadata_value(vm_nic_snapshot.metadata, 'network_id')

            # Adjust network id to new network id
            if nic_data['mac_address'] in restored_net_resources:
                network_id = restored_net_resources[nic_data['mac_address']]['network_id']
            nic_info.setdefault('net-id', network_id)

            ipinfo = None
            try:
                ipinfo = compute_service.get_fixed_ip(cntx, nic_info['v4-fixed-ip'])
            except:
                # the old IP address may not belong to any of the subnets 
                pass
            if ipinfo:
                if ipinfo.hostname:
                    # IP in use. Raise an exception
                    raise Exception("IP address %s is in use. Cannot restore VM" % \
                                         nic_info['v4-fixed-ip'])
                    # else reuse existing ip address
            else:
                # find a free fixed ip on the subnet that we can use
                for net in networks:
                    if net.id == nic_info['net-id']:
                        if net.cidr is None:
                            network_type = 'neutron'
                        else:
                            network_type = 'nova'
                        break
                if net.id != nic_info['net-id']:
                    raise Exception("Network by netid %s not found" % net.id)
            if network_type != 'neutron' and network_type is not None:
                for ip in IPNetwork(net.cidr):
                    if ip >= IPAddress(net.dhcp_start) and \
                        ip != IPAddress(net.gateway):
                        ipinfo = compute_service.get_fixed_ip(cntx, str(ip))
                        if not ipinfo.hostname:
                            nic_info['v4-fixed-ip'] = str(ip)
                            break
            else:
                if nic_data['mac_address'] in restored_net_resources and \
                   'id' in restored_net_resources[nic_data['mac_address']]:
                    nic_info.setdefault('port-id',
                           restored_net_resources[nic_data['mac_address']]['id'])
                    network_id = restored_net_resources[nic_data['mac_address']]['network_id']
                    'network-id' in nic_info and nic_info.pop('network-id')
                    'v4-fixed-ip' in nic_info and nic_info.pop('v4-fixed-ip')
                    nic_info.setdefault('network-id', network_id)
                    nic_info.setdefault('v4-fixed-ip',
                           restored_net_resources[nic_data['mac_address']]['fixed_ips'][0]['ip_address'])
                else:
                    #private network
                    pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'network_id')
                    try:
                        new_network = restored_net_resources[pit_id]
                        nic_info.setdefault('network-id', new_network['id']) 
                    except:
                           pass

                    #TODO(giri): the ip address sometimes may not be available due to one of the router or network
                    #interfaces taking them over
                    #nic_info.setdefault('v4-fixed-ip', db.get_metadata_value(vm_nic_snapshot.metadata, 'ip_address'))
            restored_nics.append(nic_info) 
    return restored_nics 

@autolog.log_method(Logger, 'vmtasks_openstack.get_vm_restore_data_size')
def get_vm_restore_data_size(cntx, db, instance, restore):

    instance_size = 0          
    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'], restore['snapshot_id'])
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
        instance_size = instance_size + vm_disk_resource_snap.size
        while vm_disk_resource_snap.vm_disk_resource_snap_backing_id is not None:
            vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(cntx, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            instance_size = instance_size + vm_disk_resource_snap_backing.size
            vm_disk_resource_snap  = vm_disk_resource_snap_backing                           

    return instance_size

@autolog.log_method(Logger, 'vmtasks_openstack.get_restore_data_size')
def get_restore_data_size(cntx, db, restore):
    restore_size = 0
    restore_options = pickle.loads(restore['pickle'].encode('ascii','ignore'))
    for vm in db.snapshot_vms_get(cntx, restore['snapshot_id']):
        instance_options = utils.get_instance_restore_options(restore_options, vm.vm_id, restore_options['type'])
        if instance_options and instance_options.get('include', True) == False:
            continue
        restore_size = restore_size + vm.restore_size        

    return restore_size

@autolog.log_method(Logger, 'vmtasks_openstack.pre_restore_vm')
def pre_restore_vm(cntx, db, instance, restore):
    # pre processing of restore
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        return virtdriver.pre_restore_vm(cntx, db, instance, restore)    
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        return virtdriver.pre_restore_vm(cntx, db, instance, restore)  
    
@autolog.log_method(Logger, 'vmtasks_openstack.restore_networks')                    
def restore_vm_networks(cntx, db, restore):
    """
    Restore the networking configuration of VMs of the snapshot
    nic_mappings: Dictionary that holds the nic mappings. { nic_id : { network_id : network_uuid, etc. } }
    """
   
    def _get_nic_restore_options(restore_options, instance_id, mac_address):
        instance_options = utils.get_instance_restore_options(restore_options, instance_id, 'openstack')
        if instance_options and 'nics' in instance_options:
            for nic_options in instance_options['nics']:
                if 'mac_adress' in nic_options:
                    if nic_options['mac_adress'] == mac_address:
                        return nic_options
                if 'mac_address' in nic_options:
                    if nic_options['mac_address'] == mac_address:
                        return nic_options                    
        return None
                
    def _get_nic_port_from_restore_options(restore_options,
                                           snapshot_vm_nic_options,
                                           instance_id, mac_address):

        def _get_port_for_ip(ports, ip_address):
            if ports and ip_address:
                for port in ports:
                 
                    if 'fixed_ips' in port:
                        for fixed_ip in port['fixed_ips']:
                            if fixed_ip['ip_address'] == ip_address:
                                return port
            return None
        
        def _create_port(name, ip_address, network_id,
                         subnet_id):
            
            params = {'name': name,
                      'fixed_ips': [{'ip_address': ip_address,
                                     'subnet_id': subnet_id} ],
                      'network_id': network_id,
                      'tenant_id': cntx.tenant}

            new_port = network_service.create_port(cntx, **params)
               
            restored_vm_resource_values = {'id': new_port['id'],
                                           'vm_id': restore['id'],
                                           'restore_id': restore['id'],       
                                           'resource_type': 'port',
                                           'resource_name':  new_port['name'],
                                           'metadata': {},
                                           'status': 'available'}
            restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)              
            return new_port

        networks_mapping = []
        if 'networks_mapping' in restore_options['openstack'] and\
            'networks' in restore_options['openstack']['networks_mapping']:
            networks_mapping = restore_options['openstack']['networks_mapping']['networks']

        oneclickrestore = 'oneclickrestore' in restore_options and \
                          restore_options['oneclickrestore']

        # default to original VM network id, subnet id and ip address
        network_id = snapshot_vm_nic_options['network_id']
        subnet_id = None
        if 'subnet_id' in snapshot_vm_nic_options:
            subnet_id = snapshot_vm_nic_options['subnet_id']

        if 'ip_address' in snapshot_vm_nic_options:
            ip_address = snapshot_vm_nic_options['ip_address']
  
        # if this is not one click restore, then get new network id,
        # subnet id and ip address
        if not oneclickrestore:
            ip_address = None
            instance_options = utils.get_instance_restore_options(restore_options,
                                                     instance_id, 'openstack') 
            port_name = instance_options.get('name','')
            ip_address = None
            nic_options = _get_nic_restore_options(restore_options, instance_id, mac_address)
            if nic_options:
                network_id = nic_options['network']['id']

                if 'subnet' in nic_options['network']:
                    subnet_id = nic_options['network']['subnet']['id']
                else:
                    subnet_id = None

                if 'ip_address' in nic_options:
                    ip_address = nic_options['ip_address']
            else:
                for net in networks_mapping:
                    if net['snapshot_network']['id'] == network_id:
                        if subnet_id:
                            if net['snapshot_network']['subnet']['id'] == subnet_id:
                                subnet_id = net['target_network']['subnet']['id']
                                network_id = net['target_network']['id']
                                break
                        else:
                            network_id = net['target_network']['id']
                            subnet_id = net['target_network']['subnet']['id']
                            break

        # Make sure networks and subnets exists
        try:
            network_service.get_network(cntx, network_id)
        except Exception as ex:
            raise Exception("Could not find the network that matches the restore options")

        try:
            network_service.get_subnet(cntx, subnet_id)
        except Exception as ex:
            raise Exception("Could not find the subnet that matches the restore options")

        ports = network_service.get_ports(cntx, **{'subnet_id':subnet_id})

        # If IP address is set, then choose the port with that ip address
        if ports and ip_address:
            port = _get_port_for_ip(ports, ip_address)
            if port: 
                if 'device_id' in port and \
                    port['device_id'] in ('', None):
                    return port
                else:
                    raise Exception(_("Given IP address %s is in use" % ip_address))
            else:
                try:
                    return _create_port(port_name, ip_address,
                                        network_id, subnet_id)
                except Exception as ex:
                    LOG.exception(ex)

        else:
            # Choose free IP address
            subnet = network_service.get_subnet(cntx, subnet_id)
            for ip in IPNetwork(subnet['subnet']['cidr']):
                if ip < IPAddress(subnet['subnet']['allocation_pools'][0]['start']) or \
                    ip == IPAddress(subnet['subnet']['gateway_ip']):
                    continue

                new_ip_address =  str(ip)
                try:
                    return _create_port(port_name, new_ip_address,
                                        network_id, subnet_id)
                except Exception as ex:
                    LOG.exception(ex)

        raise Exception("Could not find the network that matches the restore options")

    restore_obj = db.restore_update( cntx, restore['id'], {'progress_msg': 'Restoring network resources'})    
    restore_options = pickle.loads(str(restore_obj.pickle))
    restored_net_resources = {}

    network_service =  neutron.API(production=restore['restore_type'] != 'test')  
    dst_network_type = 'nova'
    try:
        networks = network_service.get_networks(cntx)
        dst_network_type = 'neutron'
    except:
        pass

    snapshot_vm_common_resources = db.snapshot_vm_resources_get(cntx, restore['snapshot_id'], restore['snapshot_id'])           
    for snapshot_vm in db.snapshot_vms_get(cntx, restore['snapshot_id']):
        snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, snapshot_vm.vm_id, restore['snapshot_id'])        
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type == 'nic':

                src_network_type = db.get_metadata_value(snapshot_vm_resource.metadata,
                                                         'network_type')              
                vm_nic_snapshot = db.vm_network_resource_snap_get(cntx, snapshot_vm_resource.id)
                nic_data = pickle.loads(str(vm_nic_snapshot.pickle))
                if dst_network_type != 'neutron':
                    instance_id = snapshot_vm.vm_id
                    mac_address = nic_data['mac_address']
                    nic_options = _get_nic_restore_options(restore_options, instance_id, mac_address)
                    if nic_options and 'new_network_id' in nic_options:
                        nic_data['network_id'] = nic_options['new_network_id']
                    restored_net_resources.setdefault(nic_data['mac_address'], nic_data)
                    restored_net_resources[nic_data['mac_address']]['production'] = False
                    if restored_net_resources[nic_data['mac_address']]['ip_address'] == nic_data['ip_address']:
                        restored_net_resources[nic_data['mac_address']]['production'] = True
                else:
                    new_port = _get_nic_port_from_restore_options(restore_options, nic_data,
                                                               snapshot_vm.vm_id,
                                                               nic_data['mac_address'])
                    if new_port:
                        restored_net_resources.setdefault(nic_data['mac_address'], new_port)
                        restored_net_resources[nic_data['mac_address']]['production'] = False
                        if restored_net_resources[nic_data['mac_address']]['fixed_ips'][0]['ip_address'] == \
                           nic_data['ip_address']:
                            restored_net_resources[nic_data['mac_address']]['production'] = True

                        continue
                    #private network
                    pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'network_id')
                    if pit_id:
                        if pit_id in restored_net_resources:
                            new_network = restored_net_resources[pit_id]
                        else:
                            raise Exception("Could not find the network that matches the restore options")

                    #private subnet
                    pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'subnet_id')
                    if pit_id:
                        if pit_id in restored_net_resources:
                            new_subnet = restored_net_resources[pit_id]
                        else:
                            raise Exception("Could not find the network that matches the restore options")

                    #external network
                    pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'ext_network_id')
                    if pit_id:
                        if pit_id in restored_net_resources:
                            new_ext_network = restored_net_resources[pit_id]
                        else:
                            raise Exception("Could not find the network that matches the restore options")
                        
                        #external subnet
                        pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'ext_subnet_id')
                        if pit_id:
                            if pit_id in restored_net_resources:
                                new_ext_subnet = restored_net_resources[pit_id]
                            else:
                                raise Exception("Could not find the network that matches the restore options")

                    #router
                    pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'router_id')
                    if pit_id:
                        if pit_id in restored_net_resources:
                            new_router = restored_net_resources[pit_id]
                        else:
                            raise Exception("Could not find the network that matches the restore options")


    return restored_net_resources

@autolog.log_method(Logger, 'vmtasks_openstack.delete_networks')                    
def delete_vm_networks(cntx, restored_net_resources):
    network_service =  neutron.API(production=True)
    # Delete routers first
    for resid, netresource in restored_net_resources.iteritems():
        try:
            if 'external_gateway_info' in netresource:
                network_service.delete_router(cntx, netresource['id'])
        except:
            pass

    # Delete public networks
    for resid, netresource in restored_net_resources.iteritems():
        try:
            if 'router:external' in netresource and \
                netresource['router:external']:
                network_service.delete_network(cntx, netresource['id'])
        except:
            pass

    # Delete private networks
    for resid, netresource in restored_net_resources.iteritems():
        try:
            if 'router:external' in netresource and \
                not netresource['router:external']:
                network_service.delete_network(cntx, netresource['id'])
        except:
            pass

    # Delete subnets
    for resid, netresource in restored_net_resources.iteritems():
        try:
            if 'cidr' in netresource:
                network_service.delete_subnet(cntx, netresource['id'])
        except:
            pass

@autolog.log_method(Logger, 'vmtasks_openstack.restore_vm_security_groups')
def restore_vm_security_groups(cntx, db, restore):

    def security_group_exists(snapshot_vm_resource):
        existing_secgroups = network_service.security_group_list(cntx)
        existinggroup = None
        for secgrp in existing_secgroups['security_groups']:
            if snapshot_vm_resource.resource_name == secgrp['id']:
                existinggroup = secgrp
                break
        if existinggroup == None:
            return False

        vm_security_group_rule_snaps = db.vm_security_group_rule_snaps_get(cntx,
                                               snapshot_vm_resource.id)
        if len(vm_security_group_rule_snaps) != \
               len(existinggroup['security_group_rules']):
            return False

        for vm_security_group_rule in vm_security_group_rule_snaps:
            vm_security_group_rule_values = pickle.loads(str(vm_security_group_rule.pickle))
            found = False
            for rule in existinggroup['security_group_rules']:
                if vm_security_group_rule_values['id'] == rule['id']:
                    found = True
                    break

            if not found:
                return False

        return True

    network_service =  neutron.API(production=restore['restore_type'] != 'test')
    restored_security_groups = {}

    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, restore['snapshot_id'], restore['snapshot_id'])        
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type == 'security_group':

            security_group_type = db.get_metadata_value(snapshot_vm_resource.metadata,
                                                         'security_group_type')
            if security_group_type != 'neutron':
                continue
            if  security_group_exists(snapshot_vm_resource):
                continue

            name = 'snap_of_' + db.get_metadata_value(snapshot_vm_resource.metadata, 'name')
            description = 'snapshot - ' + db.get_metadata_value(snapshot_vm_resource.metadata, 'description')
            security_group = network_service.security_group_create(cntx, name, description).get('security_group')
            restored_security_groups[snapshot_vm_resource.resource_pit_id] = security_group['id']
            restored_vm_resource_values = {'id': security_group['id'],
                                           'vm_id': restore['id'],
                                           'restore_id': restore['id'],
                                           'resource_type': 'security_group',
                                           'resource_name':  security_group['name'],
                                           'metadata': {},
                                           'status': 'available'}
            restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)
            #delete default rules
            for security_group_rule in security_group['security_group_rules']:
                network_service.security_group_rule_delete(cntx, security_group_rule['id'])

            vm_security_group_rule_snaps = db.vm_security_group_rule_snaps_get(cntx, snapshot_vm_resource.id)
            for vm_security_group_rule in vm_security_group_rule_snaps:
                vm_security_group_rule_values = pickle.loads(str(vm_security_group_rule.pickle))
                if vm_security_group_rule_values['remote_group_id']:
                    remote_group_id = restored_security_groups[vm_security_group_rule_values['remote_group_id']]
                else:
                    remote_group_id = None

                network_service.security_group_rule_create( cntx, 
                                            restored_security_groups[snapshot_vm_resource.resource_pit_id],
                                            vm_security_group_rule_values['direction'],
                                            vm_security_group_rule_values['ethertype'],
                                            vm_security_group_rule_values['protocol'], 
                                            vm_security_group_rule_values['port_range_min'], 
                                            vm_security_group_rule_values['port_range_max'],
                                            vm_security_group_rule_values['remote_ip_prefix'],
                                            remote_group_id) 
    return restored_security_groups      

@autolog.log_method(Logger, 'vmtasks_openstack.delete_vm_security_groups')        
def delete_vm_security_groups(cntx, security_groups):
    network_service =  neutron.API(production=True)
    for resid, secid in security_groups.iteritems():
        network_service.security_group_delete(cntx, secid)

@autolog.log_method(Logger, 'vmtasks_openstack.restore_vm')                    
def restore_vm(cntx, db, instance, restore, restored_net_resources, restored_security_groups):

    restored_compute_flavor = restore_vm_flavor(cntx, db, instance,restore)                      

    restored_nics = get_vm_nics( cntx, db, instance, restore, restored_net_resources)
    
    restore_obj = db.restore_get(cntx, restore['id']) 
    restore_options = pickle.loads(str(restore_obj.pickle))
    instance_options = utils.get_instance_restore_options(restore_options, instance['vm_id'],'openstack')
         
    virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
  
    # call with new context
    user_id = cntx.user
    project_id = cntx.tenant
    cntx = nova._get_tenant_context(user_id, project_id)
    return virtdriver.restore_vm( cntx, db, instance, restore, 
                                  restored_net_resources,
                                  restored_security_groups,
                                  restored_compute_flavor,
                                  restored_nics,
                                  instance_options)

@autolog.log_method(Logger, 'vmtasks_openstack.poweron_vm')
def poweron_vm(cntx, instance, restore, restored_instance):
    pass

@autolog.log_method(Logger, 'vmtasks_openstack.post_restore_vm')
def post_restore_vm(cntx, db, instance, restore):
    # post processing of restore
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        return virtdriver.post_restore_vm(cntx, db, instance, restore)    
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        return virtdriver.post_restore_vm(cntx, db, instance, restore)      
