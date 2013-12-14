# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Job scheduler manages WorkloadMgr


**Related Flags**

:workloads_topic:  What :mod:`rpc` topic to listen to (default:
                        `workloadmgr-workloads`).
:workloads_manager:  The module name of a class derived from
                          :class:`manager.Manager` (default:
                          :class:`workloadmgr.workload.manager.Manager`).

"""

from sqlalchemy import *
from datetime import datetime, timedelta
import time
import uuid
import cPickle as pickle

from oslo.config import cfg

from workloadmgr import context
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr import manager
from workloadmgr.virt import driver
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.apscheduler.scheduler import Scheduler
from workloadmgr.compute import nova
from workloadmgr.network import neutron

from workloadmgr.vault import vault

LOG = logging.getLogger(__name__)

workloads_manager_opts = [
    cfg.StrOpt('vault_service',
               default='vault_service',
               help='vault_service'),
]

scheduler_config = {'standalone': 'True'}

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)

def workload_callback(workload_id):
    """
    Callback
    """
    #TODO(gbasava): Implementation



class WorkloadMgrManager(manager.SchedulerDependentManager):
    """Manages WorkloadMgr """

    RPC_API_VERSION = '1.0'

    def __init__(self, service_name=None, *args, **kwargs):

        self.az = FLAGS.storage_availability_zone
        self.scheduler = Scheduler(scheduler_config)
        self.scheduler.start()
        super(WorkloadMgrManager, self).__init__(service_name='workloadscheduler',*args, **kwargs)
        
    def init_host(self):
        """
        Do any initialization that needs to be run if this is a standalone service.
        """

        ctxt = context.get_admin_context()

        LOG.info(_("Cleaning up incomplete operations"))
        
    def _append_unique(self, list, new_item):
        for item in list:
            if item['id'] == new_item['id']:
                return
        list.append(new_item)
        
       
    def _snapshot_networks(self, context, production, snapshot):
        """
        Snapshot the networking configuration of VMs
        """
        try:
            compute_service = nova.API(production=production)
            network_service =  neutron.API(production=production)  
            subnets = []
            networks = []
            routers = []
            for snapshot_vm in self.db.snapshot_vm_get(context, snapshot.id): 
                interfaces = compute_service.get_interfaces(context, snapshot_vm.vm_id)
                nics = []
                for interface in interfaces:
                    nic = {} #nic is dictionary to hold the following data
                    #ip_address, mac_address, subnet_id, network_id, router_id, ext_subnet_id, ext_network_id
                    
                    nic.setdefault('ip_address', interface.fixed_ips[0]['ip_address'])
                    nic.setdefault('mac_address', interface.mac_addr)
    
                    port_data = network_service.get_port(context, interface.port_id)
                    #TODO(giri): We may not need ports
                    #self._append_unique(ports, port_data['port']) 
                    #nic.setdefault('port_id', interface.port_id)
                    
                    subnets_data = network_service.get_subnets_from_port(context,port_data['port'])
                    #TODO(giri): we will support only one fixedip per interface for now
                    if subnets_data['subnets'][0]:
                        self._append_unique(subnets, subnets_data['subnets'][0])
                        nic.setdefault('subnet_id', subnets_data['subnets'][0]['id'])
    
                    network = network_service.get_network(context,port_data['port']['network_id'])
                    if network : 
                        self._append_unique(networks, network)
                        nic.setdefault('network_id', network['id'])
                    
                    #Let's find our router
                    routers_data = network_service.get_routers(context)
                    router_found = None
                    for router in routers_data:
                        if router_found : break
                        search_opts = {'device_id': router['id'], 'network_id':network['id']}
                        router_ports_data = network_service.get_ports(context,**search_opts)
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
                            router_ext_ports_data = network_service.get_ports(context,**search_opts)
                            if router_ext_ports_data and router_ext_ports_data['ports'] and router_ext_ports_data['ports'][0]:
                                ext_port = router_ext_ports_data['ports'][0]
                                #self._append_unique(ports, ext_port) TODO(giri): We may not need ports 
                                ext_subnets_data = network_service.get_subnets_from_port(context,ext_port)
                                #TODO(giri): we will capture only one subnet for now
                                if ext_subnets_data['subnets'][0]:
                                    self._append_unique(subnets, ext_subnets_data['subnets'][0])
                                    nic.setdefault('ext_subnet_id', ext_subnets_data['subnets'][0]['id'])
                                ext_network = network_service.get_network(context,ext_port['network_id'])
                                if ext_network:
                                    self._append_unique(networks, ext_network)
                                    nic.setdefault('ext_network_id', ext_network['id'])
                    nics.append(nic)
                #Store the nics in the DB
                for nic in nics:
                    snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                                       'vm_id': snapshot_vm.vm_id,
                                                       'snapshot_id': snapshot.id,       
                                                       'resource_type': 'nic',
                                                       'resource_name':  '',
                                                       'resource_pit_id': '',
                                                       'status': 'available'}
                    snapshot_vm_resource = self.db.snapshot_vm_resource_create(context, 
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
                                                                 
                    vm_network_resource_snap = self.db.vm_network_resource_snap_create(context, vm_network_resource_snap_values)                
                                    
            #store the subnets, networks and routers in the DB
            for subnet in subnets:
                snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                                   'vm_id': snapshot.id, 
                                                   'snapshot_id': snapshot.id,       
                                                   'resource_type': 'subnet',
                                                   'resource_name':  subnet['name'],
                                                   'resource_pit_id': subnet['id'],
                                                   'status': 'available'}
                snapshot_vm_resource = self.db.snapshot_vm_resource_create(context, 
                                                    snapshot_vm_resource_values)                                                
                # create an entry in the vm_network_resource_snaps table
                vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
                vm_network_resource_snap_values = {'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                     'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                     'pickle': pickle.dumps(subnet, 0),
                                                     'metadata': vm_network_resource_snap_metadata,       
                                                     'status': 'available'}     
                                                             
                vm_network_resource_snap = self.db.vm_network_resource_snap_create(context, vm_network_resource_snap_values)                
                
            for network in networks:
                snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                                   'vm_id': snapshot.id,
                                                   'snapshot_id': snapshot.id,       
                                                   'resource_type': 'network',
                                                   'resource_name':  network['name'],
                                                   'resource_pit_id': network['id'],
                                                   'status': 'available'}
                snapshot_vm_resource = self.db.snapshot_vm_resource_create(context, 
                                                    snapshot_vm_resource_values)                                                
                # create an entry in the vm_network_resource_snaps table
                vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
                vm_network_resource_snap_values = {'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                     'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                     'pickle': pickle.dumps(network, 0),
                                                     'metadata': vm_network_resource_snap_metadata,       
                                                     'status': 'available'}     
                                                             
                vm_network_resource_snap = self.db.vm_network_resource_snap_create(context, vm_network_resource_snap_values)                
   
            for router in routers:
                snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                                   'vm_id': snapshot.id,
                                                   'snapshot_id': snapshot.id,       
                                                   'resource_type': 'router',
                                                   'resource_name':  router['name'],
                                                   'resource_pit_id': router['id'],
                                                   'status': 'available'}
                snapshot_vm_resource = self.db.snapshot_vm_resource_create(context, 
                                                    snapshot_vm_resource_values)                                                
                # create an entry in the vm_network_resource_snaps table
                vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
                vm_network_resource_snap_values = {'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                     'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                     'pickle': pickle.dumps(router, 0),
                                                     'metadata': vm_network_resource_snap_metadata,       
                                                     'status': 'available'}     
                                                             
                vm_network_resource_snap = self.db.vm_network_resource_snap_create(context, vm_network_resource_snap_values)                
             
            return
        except Exception as err:
            return;
        
    def _get_metadata_value(self, vm_network_resource_snap, key):
        for metadata in vm_network_resource_snap.metadata:
            if metadata['key'] == key:
                return metadata['value']
                
    def _get_pit_resource_id(self, vm_network_resource_snap, key):
        for metadata in vm_network_resource_snap.metadata:
            if metadata['key'] == key:
               pit_id = metadata['value']
               return pit_id
            
    def _get_pit_resource(self, snapshot_vm_common_resources, pit_id):
        for snapshot_vm_resource in snapshot_vm_common_resources:
            if snapshot_vm_resource.resource_pit_id == pit_id:
                return snapshot_vm_resource            
                    
    def _restore_networks(self, context, production, snapshot, new_net_resources):
        """
        Restore the networking configuration of VMs of the snapshot
        nic_mappings: Dictionary that holds the nic mappings. { nic_id : { network_id : network_uuid, etc. } }
        """
        try:
            network_service =  neutron.API(production=production)  

            snapshot_vm_common_resources = self.db.snapshot_vm_resources_get(context, snapshot.id, snapshot.id)           
            for snapshot_vm in self.db.snapshot_vm_get(context, snapshot.id):
                snapshot_vm_resources = self.db.snapshot_vm_resources_get(context, snapshot_vm.vm_id, snapshot.id)        
                for snapshot_vm_resource in snapshot_vm_resources:
                    if snapshot_vm_resource.resource_type == 'nic':                
                        vm_nic_snapshot = self.db.vm_network_resource_snap_get(context, snapshot_vm_resource.id)
                        #private network
                        pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'network_id')
                        if pit_id in new_net_resources:
                            new_network = new_net_resources[pit_id]
                        else:
                            vm_nic_network = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                            vm_nic_network_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_network.id)
                            network = pickle.loads(str(vm_nic_network_snapshot.pickle))
                            params = {'name': network['name'],
                                      'tenant_id': context.tenant,
                                      'admin_state_up': network['admin_state_up'],
                                      'shared': network['shared'],
                                      'router:external': network['router:external']} 
                            new_network = network_service.create_network(context,**params)
                            new_net_resources.setdefault(pit_id,new_network)
                            
                        #private subnet
                        pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'subnet_id')
                        if pit_id in new_net_resources:
                            new_subnet = new_net_resources[pit_id]
                        else:
                            vm_nic_subnet = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                            vm_nic_subnet_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_subnet.id)
                            subnet = pickle.loads(str(vm_nic_subnet_snapshot.pickle))
                            params = {'name': subnet['name'],
                                      'network_id': new_network['id'],
                                      'tenant_id': context.tenant,
                                      'cidr': subnet['cidr'],
                                      'ip_version': subnet['ip_version']} 
                            new_subnet = network_service.create_subnet(context,**params)
                            new_net_resources.setdefault(pit_id,new_subnet)
        
                        #external network
                        pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'ext_network_id')
                        if pit_id in new_net_resources:
                            new_ext_network = new_net_resources[pit_id]
                        else:
                            vm_nic_ext_network = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                            vm_nic_ext_network_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_ext_network.id)
                            ext_network = pickle.loads(str(vm_nic_ext_network_snapshot.pickle))
                            params = {'name': ext_network['name'],
                                      'admin_state_up': ext_network['admin_state_up'],
                                      'shared': ext_network['shared'],
                                      'router:external': ext_network['router:external']} 
                            new_ext_network = network_service.create_network(context,**params)
                            new_net_resources.setdefault(pit_id,new_ext_network)
                            
                        #external subnet
                        pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'ext_subnet_id')
                        if pit_id in new_net_resources:
                            new_ext_subnet = new_net_resources[pit_id]
                        else:
                            vm_nic_ext_subnet = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                            vm_nic_ext_subnet_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_ext_subnet.id)
                            ext_subnet = pickle.loads(str(vm_nic_ext_subnet_snapshot.pickle))
                            params = {'name': ext_subnet['name'],
                                      'network_id': new_ext_network['id'],
                                      'cidr': ext_subnet['cidr'],
                                      'ip_version': ext_subnet['ip_version']} 
                            new_ext_subnet = network_service.create_subnet(context,**params)
                            new_net_resources.setdefault(pit_id,new_ext_subnet)
                            
                        #router
                        pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'router_id')
                        if pit_id in new_net_resources:
                            new_router = new_net_resources[pit_id]
                        else:
                            vm_nic_router = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                            vm_nic_router_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_router.id)
                            router = pickle.loads(str(vm_nic_router_snapshot.pickle))
                            params = {'name': router['name'],
                                      'tenant_id': context.tenant} 
                            new_router = network_service.create_router(context,**params)
                            new_net_resources.setdefault(pit_id,new_router)
                        
                        try:
                            network_service.router_add_interface(context,new_router['id'], subnet_id=new_subnet['id'])
                            network_service.router_add_gateway(context,new_router['id'], new_ext_network['id'])
                        except Exception as err:
                            pass
            return
        except Exception as err:
            return             
        
    def workload_create(self, context, workload_id):
        """
        Create a scheduled workload in the workload scheduler
        """
        try:
            workload = self.db.workload_get(context, workload_id)
            #TODO(gbasava): Change it to list of VMs when we support multiple VMs
            vm = self.db.workload_vms_get(context, workload_id)

            LOG.info(_('create_workload started, %s:' %workload_id))
            self.db.workload_update(context, 
                                    workload_id, 
                                    {'host': self.host,'service': FLAGS.vault_service})

            schjob = self.scheduler.add_interval_job(context, workload_callback, hours=24,
                                     name=workload['display_name'], args=[workload_id], 
                                     workload_id=workload_id)
            LOG.info(_('scheduled workload: %s'), schjob.id)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.workload_update(context, workload_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})

        self.db.workload_update(context, 
                                workload_id, 
                                {'status': 'available',
                                 'availability_zone': self.az,
                                 'schedule_job_id':schjob.id})
        
        LOG.info(_('create_workload finished. workload: %s'), workload_id)

    def workload_snapshot(self, context, snapshot_id, full):
        """
        Take a snapshot of the workload
        """
        LOG.info(_('snapshot workload started, snapshot_id %s' %snapshot_id))
        snapshot = self.db.snapshot_get(context, snapshot_id)
        
        #TODO(giri): Make sure the workload has a full snapshot before scheduling an incremental snapshot
        if full == True:
            snapshot_type = 'full'
        else:
            snapshot_type = 'incremental'
            
        workload = self.db.workload_get(context, snapshot.workload_id)
        self.db.snapshot_update(context, snapshot.id, {'status': 'executing'})
        vault_service = vault.get_vault_service(context)
        for vm in self.db.workload_vms_get(context, snapshot.workload_id):
            #create an entry for the VM
            options = {'vm_id': vm.vm_id,
                       'snapshot_id': snapshot_id,
                       'snapshot_type': snapshot_type,
                       'status': 'creating',}
            snapshot_vm = self.db.snapshot_vm_create(context, options)
            
            #TODO(giri) load the driver based on hypervisor of VM
            #virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
            virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
            
            #disks snapshot    
            virtdriver.snapshot(workload, snapshot, snapshot_vm, vault_service, self.db, context)
            #TODO(giri): Check for the success (and update)
            snapshot_vm.update({'status': 'available',})
            #TODO(giri): handle the case where this can be updated by multiple workload snapshot requests coming from 
            #different workloadmgr.
            self.db.vm_recent_snapshot_update(context, vm.vm_id, {'snapshot_id': snapshot.id})
        
        self._snapshot_networks(context, True, snapshot)
        #TODO(gbasava): Check for the success (and update)                
        self.db.snapshot_update(context, snapshot.id, {'status': 'available'})   

        #workloadmgr_service = workloadmgr.API()
        #workloadmgr_service.hydrate(context, snapshot['id'])              

    def workload_delete(self, context, workload_id):
        """
        Delete an existing workload
        """
        workload = self.db.workload_get(context, workload_id)
        LOG.info(_('delete_workload started, workload: %s'), workload_id)
        #TODO(gbasava): Implement

    def snapshot_restore(self, context, snapshot_id, test):
        """
        Restore VMs and all its LUNs from a snapshot
        """
        LOG.info(_('restore_snapshot started, restoring snapshot id: %(snapshot_id)s') % locals())
        snapshot = self.db.snapshot_get(context, snapshot_id)
        workload = self.db.workload_get(context, snapshot.workload_id)
        #self.db.snapshot_update(context, snapshot.id, {'status': 'restoring'})
        
        new_net_resources = {}
        if test:
            self._restore_networks(context, False, snapshot, new_net_resources)
        else:
            self._restore_networks(context, True, snapshot, new_net_resources)    
        vault_service = vault.get_vault_service(context)
        
        #restore each VM
        for vm in self.db.snapshot_vm_get(context, snapshot.id): 
            #TODO(giri) load the driver based on hypervisor of VM
            virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
            #virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
            
            virtdriver.snapshot_restore(workload, snapshot, test, vm, vault_service, new_net_resources, self.db, context)

    def snapshot_delete(self, context, workload_id, snapshot_id):
        """
        Delete an existing snapshot
        """
        snapshot = self.db.snapshot_get(context, workload_id, snapshot_id)
        #TODO(gbasava):Implement
 