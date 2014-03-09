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

logging.basicConfig(level=logging.ERROR)

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
from workloadmgr.db import base
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.virt import driver
from workloadmgr.vault import vault

@contextlib.contextmanager
def show_time(name):
    start = time.time()
    yield
    end = time.time()
    print(" -- %s took %0.3f seconds" % (name, end - start))

class WorkloadMgrDB(base.Base):

    def __init__(self, host=None, db_driver=None):
        super(WorkloadMgrDB, self).__init__(db_driver)
        
        
class CreateVMSnapshotDBEntries(task.Task):

    def execute(self, context, instances, snapshot):
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
            
    def revert(self, *args, **kwargs):
        # Resume VM
        print "Reverting CreateVMSnapshotDBEntries"                    
        
class SnapshotVMNetworks(task.Task):

    def _append_unique(self, list, new_item):
        for item in list:
            if item['id'] == new_item['id']:
                return
        list.append(new_item)
        
    def execute(self, context, instances, snapshot):
        # Snapshot the networking configuration of VMs
        print "NetworkSnapshot:"
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

    def revert(self, *args, **kwargs):
        # Resume VM
        print "Reverting NetworkSnapshot"
        
class SnapshotVMFlavors(task.Task):

    def execute(self, context, instances, snapshot):
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
                 
    def revert(self, *args, **kwargs):
        # Resume VM
        print "Reverting SnapshotVMFlavors"
                            
class PauseVM(task.Task):

    def execute(self, context, instance):
        # Pause the VM
        print "PauseVM: " + instance['vm_id']
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        compute_service.pause(cntx, instance['vm_id'])

    def revert(self, *args, **kwargs):
        # Resume VM
        print "Reverting PauseVM: " + kwargs['instance']['vm_id']

class ResumeVM(task.Task):

    def execute(self, context, instance):
        # Resume the VM
        print "ResumeVM: " + instance['vm_id']
        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)
        compute_service = nova.API(production=True)
        compute_service.resume(cntx, instance['vm_id'])

class SnapshotVM(task.Task):

    def execute(self, context, instance, snapshot):
        # Snapshot the VM
        print "SnapshotVM: " + instance['vm_id']
        cntx = amqp.RpcContext.from_dict(context)
        db = WorkloadMgrDB().db
        
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        vault_service = vault.get_vault_service(cntx)
        
        if instance['hypervisor_type'] == 'QEMU': 
            virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
        else: #TODO(giri) Check for all other hypervisor types
            virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
            
        virtdriver.snapshot(workload_obj, snapshot_obj, instance['vm_id'], instance['hypervisor_hostname'], vault_service, db, cntx)
        
class UploadSnapshot(task.Task):

    def execute(self, context, instance):
        # Upload snapshot data to swift endpoint
        cntx = amqp.RpcContext.from_dict(context)
        print "UploadSnapshot VM: " + instance['vm_id']
  
class BlockCommit(task.Task):
    def execute(self, context, instance):
        # Upload snapshot data to swift endpoint
        cntx = amqp.RpcContext.from_dict(context)
        print "BlockCommit VM: " + instance['vm_id']

# Assume there is no ordering dependency between instances
# pause each VM in parallel.
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
def UnorderedResumeVMs(instances):
    flow = uf.Flow("resumevmsuf")
    for index,item in enumerate(instances):
        flow.add(ResumeVM("ResumeVM_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def UnorderedUploadSnapshots(instances):
    flow = uf.Flow("resumevmsuf")
    for index,item in enumerate(instances):
        flow.add(UploadSnapshot("UploadSnapshot_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))
    
    return flow

def UnorderedBlockCommit(instances):
    flow = uf.Flow("resumevmsuf")
    for index,item in enumerate(instances):
        flow.add(BlockCommit("BlockCommit_" + item['vm_id'], rebind=dict(instance = "instance_" + str(index))))

    return flow



