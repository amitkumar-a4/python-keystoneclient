# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement application
specific flows

"""

import contextlib
import logging
import os
import random
import sys
import time
import uuid
import cPickle as pickle

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)

from taskflow import engines
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow import task
from taskflow.utils import reflection

from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.virt import driver
from workloadmgr.vault import vault
from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

@contextlib.contextmanager
def show_time(name):
    start = time.time()
    yield
    end = time.time()
    print(" -- %s took %0.3f seconds" % (name, end - start))

       
class SnapshotVMNetworks(task.Task):

    def _append_unique(self, list, new_item):
        for item in list:
            if item['id'] == new_item['id']:
                return
        list.append(new_item)
        
    def execute(self, context, instances, snapshot):
        return self.execute_with_log(context, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    

    @autolog.log_method(Logger, 'SnapshotVMNetworks.execute')
    def execute_with_log(self, context, instances, snapshot):
        # Snapshot the networking configuration of VMs
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

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
                #self._append_unique(ports, port_data['port']) 
                #nic.setdefault('port_id', interface.port_id)
                
                subnets_data = network_service.get_subnets_from_port(cntx,port_data['port'])
                #TODO(giri): we will support only one fixedip per interface for now
                if subnets_data['subnets'][0]:
                    self._append_unique(subnets, subnets_data['subnets'][0])
                    nic.setdefault('subnet_id', subnets_data['subnets'][0]['id'])

                network = network_service.get_network(cntx,port_data['port']['network_id'])
                if network : 
                    self._append_unique(networks, network)
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
                    self._append_unique(routers, router_found)
                    nic.setdefault('router_id', router_found['id'])
                    if router_found['external_gateway_info'] and router_found['external_gateway_info']['network_id']:
                        search_opts = {'device_id': router_found['id'], 'network_id': router_found['external_gateway_info']['network_id']}
                        router_ext_ports_data = network_service.get_ports(cntx,**search_opts)
                        if router_ext_ports_data and router_ext_ports_data['ports'] and router_ext_ports_data['ports'][0]:
                            ext_port = router_ext_ports_data['ports'][0]
                            #self._append_unique(ports, ext_port) TODO(giri): We may not need ports 
                            ext_subnets_data = network_service.get_subnets_from_port(cntx,ext_port)
                            #TODO(giri): we will capture only one subnet for now
                            if ext_subnets_data['subnets'][0]:
                                self._append_unique(subnets, ext_subnets_data['subnets'][0])
                                nic.setdefault('ext_subnet_id', ext_subnets_data['subnets'][0]['id'])
                            ext_network = network_service.get_network(cntx,ext_port['network_id'])
                            if ext_network:
                                self._append_unique(networks, ext_network)
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

    @autolog.log_method(Logger, 'SnapshotVMNetworks.revert') 
    def revert_with_log(self, *args, **kwargs):
        pass
        
class SnapshotVMFlavors(task.Task):

    def execute(self, context, instances, snapshot):
        return self.execute_with_log(context, instances, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
      
    @autolog.log_method(Logger, 'SnapshotVMFlavors.execute')
    def execute_with_log(self, context, instances, snapshot):
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
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
          
    @autolog.log_method(Logger, 'SnapshotVMFlavors.revert')
    def revert_with_log(self, *args, **kwargs):
        pass
                            
class PauseVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs) 
    
    @autolog.log_method(Logger, 'PauseVM.execute')
    def execute_with_log(self, context, instance):
        # Pause the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        compute_service.pause(cntx, instance['vm_id'])

    @autolog.log_method(Logger, 'PauseVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass
        
class UnPauseVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'UnPauseVM.execute')
    def execute_with_log(self, context, instance):
        # UnPause the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        compute_service.unpause(cntx, instance['vm_id'])

    @autolog.log_method(Logger, 'UnPauseVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     

class SuspendVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'SuspendVM.execute')
    def execute_with_log(self, context, instance):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        compute_service.suspend(cntx, instance['vm_id'])

    @autolog.log_method(Logger, 'SuspendVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
            
class ResumeVM(task.Task):

    def execute(self, context, instance):
        return self.execute_with_log(context, instance)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'ResumeVM.execute')
    def execute_with_log(self, context, instance):
        # Resume the VM
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        compute_service.resume(cntx, instance['vm_id'])

    @autolog.log_method(Logger, 'ResumeVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
    
class PreSnapshot(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PreSnapshot.execute')
    def execute_with_log(self, context, instance, snapshot):
        # pre processing of snapshot
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        vault_service = vault.get_vault_service(cntx)
        
        if instance['hypervisor_type'] == 'QEMU': 
            compute_service = nova.API(production=True)
            vast_params = {'test1': 'test1','test2': 'test2'}
            compute_service.vast_prepare(context, instance['vm_id'], vast_params) 
        else: 
            #TODO(giri) Check for all other hypervisor types
            virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
            #TODO(giri): implement this for VMware
            #virtdriver.pre_snapshot(workload_obj, snapshot_obj, instance['vm_id'], instance['hypervisor_hostname'], vault_service, db, cntx)

    @autolog.log_method(Logger, 'PreSnapshot.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
           
class SnapshotVM(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'SnapshotVM.execute')
    def execute_with_log(self, context, instance, snapshot):
        # Snapshot the VM
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        
        if instance['hypervisor_type'] == 'QEMU': 
            compute_service = nova.API(production=True)
            vast_params = {'snapshot_id': snapshot_obj.id,
                           'workload_id': workload_obj.id}
            compute_service.vast_instance(cntx, instance['vm_id'], vast_params) 
        else: 
            #TODO(giri) Check for all other hypervisor types
            virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
            #TODO(giri): implement this for VMware
            #virtdriver.snapshot(workload_obj, snapshot_obj, instance['vm_id'], instance['hypervisor_hostname'], vault_service, db, cntx)

    @autolog.log_method(Logger, 'SnapshotVM.revert')
    def revert_with_log(self, *args, **kwargs):
        pass     
                
class SnapshotDataSize(task.Task):

    def execute(self, context, instances, snapshot):
        return self.execute_with_log(context, instances, snapshot)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)    
    
    @autolog.log_method(Logger, 'GetSnapshotDataSize.execute')    
    def execute_with_log(self, context, instances, snapshot):
        # Snapshot the VM
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)

        snapshot_data_size = 0;
        for instance in instances:
            LOG.debug(_("instance: %(instance_id)s") %{'instance_id': instance['vm_id'],})
            vm_data_size = 0;
            if instance['hypervisor_type'] == 'QEMU': 
                compute_service = nova.API(production=True)
                disks_info = compute_service.vast_get_info(cntx, instance['vm_id'], {})['info']
                for disk_info in disks_info:
                    LOG.debug(_("    disk: %(disk)s") %{'disk': disk_info['dev'],})
                    vm_disk_size = 0
                    pop_backings = True
                    vm_disk_resource_snap_id = None
                    if snapshot['snapshot_type'] != 'full':
                        vm_recent_snapshot = db.vm_recent_snapshot_get(cntx, instance['vm_id'])
                        if vm_recent_snapshot:
                            previous_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_name(
                                                                    cntx, 
                                                                    instance['vm_id'], 
                                                                    vm_recent_snapshot.snapshot_id, 
                                                                    disk_info['dev'])
                            previous_vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, previous_snapshot_vm_resource.id)
                            vm_disk_resource_snap_id = previous_vm_disk_resource_snap.id
                            if previous_snapshot_vm_resource.status == 'available':
                                pop_backings = False
    
                    if len(disk_info['backings']) > 0 and pop_backings == True:
                        base_backing_path = disk_info['backings'].pop()
                    else:
                        base_backing_path = disk_info['backings'][0]
                    
                    
                    while (base_backing_path != None):
                        top_backing_path = None
                        if len(disk_info['backings']) > 0 and pop_backings == True:
                            top_backing_path = disk_info['backings'].pop()
                        LOG.debug(_("        backing_file: %(backing_file)s") %{'backing_file': os.path.basename(base_backing_path['path']),})
                        LOG.debug(_("        vm_disk_size: %(vm_disk_size)s") %{'vm_disk_size': vm_disk_size,})
                        LOG.debug(_("        backing_size: %(backing_size)s") %{'backing_size': base_backing_path['size'],})     
                        vm_disk_size = vm_disk_size + base_backing_path['size']
                        LOG.debug(_("        vm_disk_size: %(vm_disk_size)s") %{'vm_disk_size': vm_disk_size,})
                        base_backing_path = top_backing_path

                    LOG.debug(_("    vm_data_size: %(vm_data_size)s") %{'vm_data_size': vm_data_size,})
                    LOG.debug(_("    vm_disk_size: %(vm_disk_size)s") %{'vm_disk_size': vm_disk_size,})
                    vm_data_size = vm_data_size + vm_disk_size
                    LOG.debug(_("vm_data_size: %(vm_data_size)s") %{'vm_data_size': vm_data_size,})
 
                        
            else: 
                #TODO(giri) Check for all other hypervisor types
                virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
                #TODO(giri): implement this for VMware
                #virtdriver.snapshot(workload_obj, snapshot_obj, instance['vm_id'], instance['hypervisor_hostname'], vault_service, db, cntx)

                
            db.snapshot_vm_update(cntx, instance['vm_id'], snapshot_obj.id, {'size': vm_data_size,})
            LOG.debug(_("snapshot_data_size: %(snapshot_data_size)s") %{'snapshot_data_size': snapshot_data_size,})
            LOG.debug(_("vm_data_size: %(vm_data_size)s") %{'vm_data_size': vm_data_size,})
            snapshot_data_size = snapshot_data_size + vm_data_size
            LOG.debug(_("snapshot_data_size: %(snapshot_data_size)s") %{'snapshot_data_size': snapshot_data_size,})

        db.snapshot_update(cntx, snapshot_obj.id, {'size': snapshot_data_size,})
        LOG.debug(_("snapshot_data_size: %(snapshot_data_size)s") %{'snapshot_data_size': snapshot_data_size,})
        return snapshot_data_size
            
    @autolog.log_method(Logger, 'GetSnapshotDataSize.revert')    
    def revert_with_log(self, *args, **kwargs):
        pass    
            
class UploadSnapshot(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'UploadSnapshot.execute')    
    def execute_with_log(self, context, instance, snapshot):
        # Upload snapshot data to swift endpoint
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        vault_service = vault.get_vault_service(cntx)
        
        if instance['hypervisor_type'] == 'QEMU': 
            compute_service = nova.API(production=True)
            vault_service = vault.get_vault_service(cntx)
            disks_info = compute_service.vast_get_info(cntx, instance['vm_id'], {})['info']

            for disk_info in disks_info:
                vm_disk_size = 0
                snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                               'vm_id': instance['vm_id'],
                                               'snapshot_id': snapshot_obj.id,       
                                               'resource_type': 'disk',
                                               'resource_name': disk_info['dev'],
                                               'metadata': {},
                                               'status': 'creating'}
    
                snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, snapshot_vm_resource_values)                                                
               
                
                pop_backings = True                
                vm_disk_resource_snap_id = None
                if snapshot['snapshot_type'] != 'full':
                    #TODO(giri): the disk can be a new disk than the previous snapshot  
                    vm_recent_snapshot = db.vm_recent_snapshot_get(cntx, instance['vm_id'])
                    if vm_recent_snapshot:
                        previous_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_name(
                                                                cntx, 
                                                                instance['vm_id'], 
                                                                vm_recent_snapshot.snapshot_id, 
                                                                disk_info['dev'])
                        previous_vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, previous_snapshot_vm_resource.id)
                        vm_disk_resource_snap_id = previous_vm_disk_resource_snap.id
                        if previous_snapshot_vm_resource.status == 'available':
                            pop_backings = False

                if len(disk_info['backings']) > 0 and pop_backings == True:
                    base_backing_path = disk_info['backings'].pop()
                else:
                    base_backing_path = disk_info['backings'][0]

                while (base_backing_path != None):
                    top_backing_path = None
                    if len(disk_info['backings']) > 0 and pop_backings == True:
                        top_backing_path = disk_info['backings'].pop()
                        
                    # create an entry in the vm_disk_resource_snaps table
                    vm_disk_resource_snap_backing_id = vm_disk_resource_snap_id
                    vm_disk_resource_snap_id = str(uuid.uuid4())
                    vm_disk_resource_snap_metadata = {} # Dictionary to hold the metadata
                    if(disk_info['dev'] == 'vda' and top_backing_path == None):
                        vm_disk_resource_snap_metadata.setdefault('base_image_ref','TODO')                    
                    vm_disk_resource_snap_metadata.setdefault('disk_format','qcow2')
                    
                    top = (top_backing_path == None)
                    vm_disk_resource_snap_values = { 'id': vm_disk_resource_snap_id,
                                                     'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                     'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                                                     'metadata': vm_disk_resource_snap_metadata,       
                                                     'top':  top,
                                                     'size': base_backing_path['size'],                                                     
                                                     'status': 'creating'}     
                                                                 
                    vm_disk_resource_snap = db.vm_disk_resource_snap_create(cntx, vm_disk_resource_snap_values)                
                    #upload to vault service
                    vault_metadata = {'metadata': vm_disk_resource_snap_metadata,
                                      'vm_disk_resource_snap_id' : vm_disk_resource_snap_id,
                                      'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                      'resource_name':  disk_info['dev'],
                                      'snapshot_vm_id': instance['vm_id'],
                                      'snapshot_id': snapshot_obj.id,}
    
                    vast_data = compute_service.vast_data(cntx, instance['vm_id'], {'path': base_backing_path['path']})
                    
                    snapshot_obj = db.snapshot_update(  cntx, snapshot_obj.id, 
                                                        {'progress_msg': 'Uploading '+ disk_info['dev'] + ' of VM:' + instance['vm_id'],
                                                         'status': 'uploading'
                                                        })
                    LOG.debug(_('Uploading '+ disk_info['dev'] + ' of VM:' + instance['vm_id'] + '; backing file:' + os.path.basename(base_backing_path['path'])))
                    vault_service_url = vault_service.store(vault_metadata, vast_data);
                    snapshot_obj = db.snapshot_update(  cntx, snapshot_obj.id, 
                                                        {'progress_msg': 'Uploaded '+ disk_info['dev'] + ' of VM:' + instance['vm_id'],
                                                         'status': 'uploading'
                                                        })                           
                    
                    # update the entry in the vm_disk_resource_snap table
                    vm_disk_resource_snap_values = {'vault_service_url' :  vault_service_url ,
                                                    'vault_service_metadata' : 'None',
                                                    'status': 'available'} 
                    db.vm_disk_resource_snap_update(cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
                    vm_disk_size = vm_disk_size + base_backing_path['size']
                    base_backing_path = top_backing_path
    
                db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, {'status': 'available', 'size': vm_disk_size})
            db.snapshot_vm_update(cntx, instance['vm_id'], snapshot_obj.id, {'status': 'available',})
        else: 
            #TODO(giri) Check for all other hypervisor types
            virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
            #TODO(giri): implement this for VMware
            virtdriver.upload_snapshot(workload_obj, snapshot_obj, instance['vm_id'], instance['hypervisor_hostname'], vault_service, db, cntx)
        
    @autolog.log_method(Logger, 'UploadSnapshot.revert')    
    def revert_with_log(self, *args, **kwargs):
        pass
      
class PostSnapshot(task.Task):

    def execute(self, context, instance, snapshot):
        return self.execute_with_log(context, instance, snapshot)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'PostSnapshot.execute')    
    def execute_with_log(self, context, instance, snapshot):
        # post processing of snapshot for ex. block commit
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        if instance['hypervisor_type'] == 'QEMU': 
            compute_service = nova.API(production=True)
            compute_service.vast_finalize(cntx,instance['vm_id'], {}) 
        else: 
            #TODO(giri) Check for all other hypervisor types
            virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
            #TODO(giri): implement this for VMware
            #virtdriver.post_snapshot(workload_obj, snapshot_obj, instance['vm_id'], instance['hypervisor_hostname'], vault_service, db, cntx)
        
        db.vm_recent_snapshot_update(cntx, instance['vm_id'], {'snapshot_id': snapshot['id']})

# Assume there is no ordering dependency between instances
# pause each VM in parallel.

    @autolog.log_method(Logger, 'PostSnapshot.revert')    
    def revert_with_log(self, *args, **kwargs):
        pass

def UnorderedPauseVMs(instances):
    flow = uf.Flow("pausevmsuf")
    for index,item in enumerate(instances):
        flow.add(PauseVM("PauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    return flow

# Assume there is dependency between instances
# pause each VM in the order that appears in the array.
def LinearPauseVMs(instances):
    flow = lf.Flow("pausevmslf")
    for index,item in enumerate(instances):
        flow.add(PauseVM("PauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

# Assume there is no ordering dependency between instances
# snapshot each VM in parallel.
def UnorderedSnapshotVMs(instances):
    flow = uf.Flow("snapshotvmuf")
    for index,item in enumerate(instances):
        flow.add(SnapshotVM("SnapshotVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

# Assume there is dependency between instances
# snapshot each VM in the order that appears in the array.
def LinearSnapshotVMs(instances):
    flow = lf.Flow("snapshotvmlf")
    for index,item in enumerate(instances):
        flow.add(SnapshotVM("SnapshotVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

# Assume there is no ordering dependency between instances
# resume each VM in parallel. Usually there should not be any
# order in which vms should be resumed.
def UnorderedUnPauseVMs(instances):
    flow = uf.Flow("unpausevmsuf")
    for index,item in enumerate(instances):
        flow.add(UnPauseVM("UnpauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def LinearUnPauseVMs(instances):
    flow = lf.Flow("unpausevmslf")
    for index,item in enumerate(instances):
        flow.add(UnPauseVM("UnPauseVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def UnorderedUploadSnapshot(instances):
    flow = uf.Flow("uploadsnapshotuf")
    for index,item in enumerate(instances):
        flow.add(UploadSnapshot("UploadSnapshot_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def UnorderedPostSnapshot(instances):
    flow = uf.Flow("postsnapshotuf")
    for index,item in enumerate(instances):
        flow.add(PostSnapshot("PostSnapshot_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))

    return flow

def CreateVMSnapshotDBEntries(context, instances, snapshot):
    #create an entry for the VM in the workloadmgr database
    cntx = amqp.RpcContext.from_dict(context)
    db = WorkloadMgrDB().db
    for instance in instances:
        options = {'vm_id': instance['vm_id'],
                   'vm_name': instance['vm_name'],
                   'snapshot_id': snapshot['id'],
                   'snapshot_type': snapshot['snapshot_type'],
                   'status': 'creating',}
        snapshot_vm = db.snapshot_vm_create(cntx, options)

