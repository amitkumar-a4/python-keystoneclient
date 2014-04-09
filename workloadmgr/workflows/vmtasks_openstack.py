# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement application
specific flows

"""

import os
import uuid
import cPickle as pickle

from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.volume import cinder
from workloadmgr.image import glance
from workloadmgr.vault import vault
from workloadmgr.virt import driver
from workloadmgr import utils

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

def _get_pit_resource_id(metadata, key):
    for metadata_item in metadata:
        if metadata_item['key'] == key:
            pit_id = metadata_item['value']
            return pit_id
        
def _get_pit_resource(snapshot_vm_common_resources, pit_id):
    for snapshot_vm_resource in snapshot_vm_common_resources:
        if snapshot_vm_resource.resource_pit_id == pit_id:
            return snapshot_vm_resource 
            
@autolog.log_method(Logger, 'vmtasks_openstack.snapshot_vm_networks')
def snapshot_vm_networks(cntx, db, instances, snapshot):

    compute_service = nova.API(production=True)
    network_service =  neutron.API(production=True)  
    subnets = []
    networks = []
    routers = []
    for instance in instances: 
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
    
            network = network_service.get_network(cntx,port_data['port']['network_id'])
            if network : 
                utils.append_unique(networks, network)
                nic.setdefault('network_id', network['id'])
            
            #Let's find our router
            routers_data = network_service.get_routers(cntx)
            router_found = None
            for router in routers_data:
                if router_found : break
                search_opts = {'device_id': router['id'], 'network_id':network['id']}
                router_ports_data = network_service.get_ports(cntx,**search_opts)
                for router_port in router_ports_data['ports']:
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
                if router_found['external_gateway_info'] and router_found['external_gateway_info']['network_id']:
                    search_opts = {'device_id': router_found['id'], 'network_id': router_found['external_gateway_info']['network_id']}
                    router_ext_ports_data = network_service.get_ports(cntx,**search_opts)
                    if router_ext_ports_data and router_ext_ports_data['ports'] and router_ext_ports_data['ports'][0]:
                        ext_port = router_ext_ports_data['ports'][0]
                        #utils.append_unique(ports, ext_port) TODO(giri): We may not need ports 
                        ext_subnets_data = network_service.get_subnets_from_port(cntx,ext_port)
                        #TODO(giri): we will capture only one subnet for now
                        if ext_subnets_data['subnets'][0]:
                            utils.append_unique(subnets, ext_subnets_data['subnets'][0])
                            nic.setdefault('ext_subnet_id', ext_subnets_data['subnets'][0]['id'])
                        ext_network = network_service.get_network(cntx,ext_port['network_id'])
                        if ext_network:
                            utils.append_unique(networks, ext_network)
                            nic.setdefault('ext_network_id', ext_network['id'])
            nics.append(nic)
        #Store the nics in the DB
        for nic in nics:
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                           'vm_id': instance['vm_id'],
                                           'snapshot_id': snapshot['id'],       
                                           'resource_type': 'nic',
                                           'resource_name':  '',
                                           'resource_pit_id': '',
                                           'metadata': {},
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

@autolog.log_method(Logger, 'vmtasks_openstack.snapshot_vm_flavors')
def snapshot_vm_flavors(cntx, db, instances, snapshot):

    compute_service = nova.API(production=True)
    for instance in instances:
        # Create  a flavor resource
        flavor = compute_service.get_flavor_by_id(cntx, instance['vm_flavor_id'])
        metadata = {'name':flavor.name, 'vcpus':flavor.vcpus, 'ram':flavor.ram, 'disk':flavor.disk, 'ephemeral':flavor.ephemeral}
        snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                       'vm_id': instance['vm_id'],
                                       'snapshot_id': snapshot['id'],       
                                       'resource_type': 'flavor',
                                       'resource_name':  flavor.name,
                                       'metadata': metadata,
                                       'status': 'available'}
        snapshot_vm_resource = db.snapshot_vm_resource_create(cntx,  snapshot_vm_resource_values)                                     
          
@autolog.log_method(Logger, 'vmtasks_openstack.pause_vm')
def pause_vm(cntx, db, instance):
    compute_service = nova.API(production=True)
    if instance['hypervisor_type'] == 'VMware vCenter Server':
        suspend_vm(cntx, db, instance)
    else:
        compute_service.pause(cntx, instance['vm_id'])

@autolog.log_method(Logger, 'vmtasks_openstack.unpause_vm')
def unpause_vm(cntx, db, instance):
    compute_service = nova.API(production=True)
    if instance['hypervisor_type'] == 'VMware vCenter Server':
        resume_vm(cntx, db, instance)
    else:
        compute_service.unpause(cntx, instance['vm_id'])

@autolog.log_method(Logger, 'vmtasks_openstack.suspend_vm')
def suspend_vm(cntx, db, instance):
    
    compute_service = nova.API(production=True)
    compute_service.suspend(cntx, instance['vm_id'])

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
def upload_snapshot(cntx, db, instance, snapshot, snapshot_data):

    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        virtdriver.upload_snapshot(cntx, db, instance, snapshot, snapshot_data)
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        virtdriver.upload_snapshot(cntx, db, instance, snapshot, snapshot_data)     

@autolog.log_method(Logger, 'vmtasks_openstack.post_snapshot')
def post_snapshot(cntx, db, instance, snapshot, snapshot_data):
        
    if instance['hypervisor_type'] == 'QEMU': 
        virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        virtdriver.post_snapshot_vm(cntx, db, instance, snapshot, snapshot_data)
    else: 
        virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
        virtdriver.post_snapshot_vm(cntx, db, instance, snapshot, snapshot_data)  

@autolog.log_method(Logger, 'vmtasks_openstack.restore_vm_flavor')
def restore_vm_flavor(cntx, db, instance, restore):

    db.restore_update( cntx, restore['id'],
                       {'progress_msg': 'Restoring VM Flavor for Instance ' + instance['vm_id']})
                    
    compute_service = nova.API(production = (restore['restore_type'] != 'test'))
    restored_compute_flavor = None
    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'], restore['snapshot_id'])
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type == 'flavor':
            snapshot_vm_flavor = db.snapshot_vm_resource_get(cntx, snapshot_vm_resource.id)
            for flavor in compute_service.get_flavors(cntx):
                if ((str(flavor.vcpus) ==  db.get_metadata_value(snapshot_vm_flavor.metadata, 'vcpus')) and
                    (str(flavor.ram) ==  db.get_metadata_value(snapshot_vm_flavor.metadata, 'ram')) and
                    (str(flavor.disk) ==  db.get_metadata_value(snapshot_vm_flavor.metadata, 'disk')) and
                    (str(flavor.ephemeral) == db.get_metadata_value(snapshot_vm_flavor.metadata, 'ephemeral'))):
                    restored_compute_flavor = flavor
                    break
            break
    if not restored_compute_flavor:
        #TODO(giri):create a new flavor
        restored_compute_flavor = compute_service.get_flavor_by_name(cntx, 'm1.small')
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
            #private network
            pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'network_id')
            new_network = restored_net_resources[pit_id]
            nic_info = {}
            nic_info.setdefault('net-id', new_network['id']) 
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
    for vm in db.snapshot_vms_get(cntx, restore['snapshot_id']):
        restore_size = restore_size + get_vm_restore_data_size(cntx, db, {'vm_id' : vm.vm_id}, restore)

    return restore_size

@autolog.log_method(Logger, 'vmtasks_openstack.restore_networks')                    
def restore_networks(cntx, db, restore):
    """
    Restore the networking configuration of VMs of the snapshot
    nic_mappings: Dictionary that holds the nic mappings. { nic_id : { network_id : network_uuid, etc. } }
    """
    db.restore_update( cntx, restore['id'], {'progress_msg': 'Restoring network resources'})    
    restored_net_resources = {}
    network_service =  neutron.API(production=restore['restore_type'] != 'test')  
    snapshot_vm_common_resources = db.snapshot_vm_resources_get(cntx, restore['snapshot_id'], restore['snapshot_id'])           
    for snapshot_vm in db.snapshot_vms_get(cntx, restore['snapshot_id']):
        snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, snapshot_vm.vm_id, restore['snapshot_id'])        
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type == 'nic':                
                vm_nic_snapshot = db.vm_network_resource_snap_get(cntx, snapshot_vm_resource.id)
                #private network
                pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'network_id')
                if pit_id in restored_net_resources:
                    new_network = restored_net_resources[pit_id]
                else:
                    vm_nic_network = _get_pit_resource(snapshot_vm_common_resources, pit_id)
                    vm_nic_network_snapshot = db.vm_network_resource_snap_get(cntx, vm_nic_network.id)
                    network = pickle.loads(str(vm_nic_network_snapshot.pickle))
                    params = {'name': network['name'] + '_' + restore['id'],
                              'tenant_id': cntx.tenant,
                              'admin_state_up': network['admin_state_up'],
                              'shared': network['shared'],
                              'router:external': network['router:external']} 
                    new_network = network_service.create_network(cntx,**params)
                    restored_net_resources.setdefault(pit_id,new_network)
                    restored_vm_resource_values = {'id': new_network['id'],
                                                   'vm_id': restore['id'],
                                                   'restore_id': restore['id'],       
                                                   'resource_type': 'network',
                                                   'resource_name':  new_network['name'],
                                                   'metadata': {},
                                                   'status': 'available'}
                    restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)                                        
                    
                #private subnet
                pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'subnet_id')
                if pit_id in restored_net_resources:
                    new_subnet = restored_net_resources[pit_id]
                else:
                    vm_nic_subnet = _get_pit_resource(snapshot_vm_common_resources, pit_id)
                    vm_nic_subnet_snapshot = db.vm_network_resource_snap_get(cntx, vm_nic_subnet.id)
                    subnet = pickle.loads(str(vm_nic_subnet_snapshot.pickle))
                    params = {'name': subnet['name'] + '_' + restore['id'],
                              'network_id': new_network['id'],
                              'tenant_id': cntx.tenant,
                              'cidr': subnet['cidr'],
                              'ip_version': subnet['ip_version']} 
                    new_subnet = network_service.create_subnet(cntx,**params)
                    restored_net_resources.setdefault(pit_id,new_subnet)
                    restored_vm_resource_values = {'id': new_subnet['id'],
                                                   'vm_id': restore['id'],
                                                   'restore_id': restore['id'],       
                                                   'resource_type': 'subnet',
                                                   'resource_name':  new_subnet['name'],
                                                   'metadata': {},
                                                   'status': 'available'}
                    restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)                              

                #external network
                pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'ext_network_id')
                if pit_id in restored_net_resources:
                    new_ext_network = restored_net_resources[pit_id]
                else:
                    vm_nic_ext_network = _get_pit_resource(snapshot_vm_common_resources, pit_id)
                    vm_nic_ext_network_snapshot = db.vm_network_resource_snap_get(cntx, vm_nic_ext_network.id)
                    ext_network = pickle.loads(str(vm_nic_ext_network_snapshot.pickle))
                    params = {'name': ext_network['name'] + '_' + restore['id'],
                              'admin_state_up': ext_network['admin_state_up'],
                              'shared': ext_network['shared'],
                              'router:external': ext_network['router:external']} 
                    new_ext_network = network_service.create_network(cntx,**params)
                    restored_net_resources.setdefault(pit_id,new_ext_network)
                    restored_vm_resource_values = {'id': new_ext_network['id'],
                                                   'vm_id': restore['id'],
                                                   'restore_id': restore['id'],       
                                                   'resource_type': 'network',
                                                   'resource_name':  new_ext_network['name'],
                                                   'metadata': {},
                                                   'status': 'available'}
                    restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)                             
                    
                #external subnet
                pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'ext_subnet_id')
                if pit_id in restored_net_resources:
                    new_ext_subnet = restored_net_resources[pit_id]
                else:
                    vm_nic_ext_subnet = _get_pit_resource(snapshot_vm_common_resources, pit_id)
                    vm_nic_ext_subnet_snapshot = db.vm_network_resource_snap_get(cntx, vm_nic_ext_subnet.id)
                    ext_subnet = pickle.loads(str(vm_nic_ext_subnet_snapshot.pickle))
                    params = {'name': ext_subnet['name'] + '_' + restore['id'],
                              'network_id': new_ext_network['id'],
                              'cidr': ext_subnet['cidr'],
                              'ip_version': ext_subnet['ip_version']} 
                    new_ext_subnet = network_service.create_subnet(cntx,**params)
                    restored_net_resources.setdefault(pit_id,new_ext_subnet)
                    restored_vm_resource_values = {'id': new_ext_subnet['id'],
                                                   'vm_id': restore['id'],
                                                   'restore_id': restore['id'],       
                                                   'resource_type': 'subnet',
                                                   'resource_name':  new_ext_subnet['name'],
                                                   'metadata': {},
                                                   'status': 'available'}
                    restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)                              
                    
                #router
                pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'router_id')
                if pit_id in restored_net_resources:
                    new_router = restored_net_resources[pit_id]
                else:
                    vm_nic_router = _get_pit_resource(snapshot_vm_common_resources, pit_id)
                    vm_nic_router_snapshot = db.vm_network_resource_snap_get(cntx, vm_nic_router.id)
                    router = pickle.loads(str(vm_nic_router_snapshot.pickle))
                    params = {'name': router['name'] + '_' + restore['id'],
                              'tenant_id': cntx.tenant} 
                    new_router = network_service.create_router(cntx,**params)
                    restored_net_resources.setdefault(pit_id,new_router)
                    restored_vm_resource_values = {'id': new_router['id'],
                                                   'vm_id': restore['id'],
                                                   'restore_id': restore['id'],       
                                                   'resource_type': 'router',
                                                   'resource_name':  new_router['name'],
                                                   'metadata': {},
                                                   'status': 'available'}
                    restored_vm_resource = db.restored_vm_resource_create(cntx,restored_vm_resource_values)                                   
                
                try:
                    network_service.router_add_interface(cntx,new_router['id'], subnet_id=new_subnet['id'])
                    network_service.router_add_gateway(cntx,new_router['id'], new_ext_network['id'])
                except Exception as err:
                    pass
    return restored_net_resources                     

@autolog.log_method(Logger, 'vmtasks_openstack.restore_vm')                    
def restore_vm(cntx, db, instance, restore, restored_net_resources):

    restored_compute_flavor = restore_vm_flavor(cntx, db, instance,restore)                      

    restored_nics = get_vm_nics( cntx, db, instance, restore, restored_net_resources)
     
    virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
    return virtdriver.restore_vm( cntx, db, instance, restore, 
                                  restored_net_resources,
                                  restored_compute_flavor,
                                  restored_nics)
    