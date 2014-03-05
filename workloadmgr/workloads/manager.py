# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Job scheduler manages WorkloadMgr


**Related Flags**

:workloads_topic:  What :mod:`rpc` topic to listen to (default:`workloadmgr-workloads`).
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
from workloadmgr.workflows import mongodbflow

LOG = logging.getLogger(__name__)

workloads_manager_opts = [
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
                                               'metadata': {},
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
                                           'metadata': {},
                                           'status': 'available'}
            snapshot_vm_resource = self.db.snapshot_vm_resource_create(context, 
                                                snapshot_vm_resource_values)                                                
            # create an entry in the vm_network_resource_snaps table
            vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_network_resource_snap_values = {  'vm_network_resource_snap_id': snapshot_vm_resource.id,
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
                                           'metadata': {},
                                           'status': 'available'}
            snapshot_vm_resource = self.db.snapshot_vm_resource_create(context, 
                                                snapshot_vm_resource_values)                                                
            # create an entry in the vm_network_resource_snaps table
            vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_network_resource_snap_values = {  'vm_network_resource_snap_id': snapshot_vm_resource.id,
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
                                           'metadata': {},
                                           'status': 'available'}
            snapshot_vm_resource = self.db.snapshot_vm_resource_create(context, 
                                                snapshot_vm_resource_values)                                                
            # create an entry in the vm_network_resource_snaps table
            vm_network_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_network_resource_snap_values = {  'vm_network_resource_snap_id': snapshot_vm_resource.id,
                                                 'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                 'pickle': pickle.dumps(router, 0),
                                                 'metadata': vm_network_resource_snap_metadata,       
                                                 'status': 'available'}     
                                                         
            vm_network_resource_snap = self.db.vm_network_resource_snap_create(context, vm_network_resource_snap_values)                
             
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
                    
    def _restore_networks(self, context, production, snapshot, restore, new_net_resources):
        """
        Restore the networking configuration of VMs of the snapshot
        nic_mappings: Dictionary that holds the nic mappings. { nic_id : { network_id : network_uuid, etc. } }
        """
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
                        params = {'name': network['name'] + '_' + restore.id,
                                  'tenant_id': context.tenant,
                                  'admin_state_up': network['admin_state_up'],
                                  'shared': network['shared'],
                                  'router:external': network['router:external']} 
                        new_network = network_service.create_network(context,**params)
                        new_net_resources.setdefault(pit_id,new_network)
                        restored_vm_resource_values = {'id': new_network['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'network',
                                                       'resource_name':  new_network['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                                        
                        
                    #private subnet
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'subnet_id')
                    if pit_id in new_net_resources:
                        new_subnet = new_net_resources[pit_id]
                    else:
                        vm_nic_subnet = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_subnet_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_subnet.id)
                        subnet = pickle.loads(str(vm_nic_subnet_snapshot.pickle))
                        params = {'name': subnet['name'] + '_' + restore.id,
                                  'network_id': new_network['id'],
                                  'tenant_id': context.tenant,
                                  'cidr': subnet['cidr'],
                                  'ip_version': subnet['ip_version']} 
                        new_subnet = network_service.create_subnet(context,**params)
                        new_net_resources.setdefault(pit_id,new_subnet)
                        restored_vm_resource_values = {'id': new_subnet['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'subnet',
                                                       'resource_name':  new_subnet['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                              
    
                    #external network
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'ext_network_id')
                    if pit_id in new_net_resources:
                        new_ext_network = new_net_resources[pit_id]
                    else:
                        vm_nic_ext_network = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_ext_network_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_ext_network.id)
                        ext_network = pickle.loads(str(vm_nic_ext_network_snapshot.pickle))
                        params = {'name': ext_network['name'] + '_' + restore.id,
                                  'admin_state_up': ext_network['admin_state_up'],
                                  'shared': ext_network['shared'],
                                  'router:external': ext_network['router:external']} 
                        new_ext_network = network_service.create_network(context,**params)
                        new_net_resources.setdefault(pit_id,new_ext_network)
                        restored_vm_resource_values = {'id': new_ext_network['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'network',
                                                       'resource_name':  new_ext_network['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                             
                        
                    #external subnet
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'ext_subnet_id')
                    if pit_id in new_net_resources:
                        new_ext_subnet = new_net_resources[pit_id]
                    else:
                        vm_nic_ext_subnet = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_ext_subnet_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_ext_subnet.id)
                        ext_subnet = pickle.loads(str(vm_nic_ext_subnet_snapshot.pickle))
                        params = {'name': ext_subnet['name'] + '_' + restore.id,
                                  'network_id': new_ext_network['id'],
                                  'cidr': ext_subnet['cidr'],
                                  'ip_version': ext_subnet['ip_version']} 
                        new_ext_subnet = network_service.create_subnet(context,**params)
                        new_net_resources.setdefault(pit_id,new_ext_subnet)
                        restored_vm_resource_values = {'id': new_ext_subnet['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'subnet',
                                                       'resource_name':  new_ext_subnet['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                              
                        
                    #router
                    pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'router_id')
                    if pit_id in new_net_resources:
                        new_router = new_net_resources[pit_id]
                    else:
                        vm_nic_router = self._get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_router_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_router.id)
                        router = pickle.loads(str(vm_nic_router_snapshot.pickle))
                        params = {'name': router['name'] + '_' + restore.id,
                                  'tenant_id': context.tenant} 
                        new_router = network_service.create_router(context,**params)
                        new_net_resources.setdefault(pit_id,new_router)
                        restored_vm_resource_values = {'id': new_router['id'],
                                                       'vm_id': restore.id,
                                                       'restore_id': restore.id,       
                                                       'resource_type': 'router',
                                                       'resource_name':  new_router['name'],
                                                       'metadata': {},
                                                       'status': 'available'}
                        restored_vm_resource = self.db.restored_vm_resource_create(context,restored_vm_resource_values)                                   
                    
                    try:
                        network_service.router_add_interface(context,new_router['id'], subnet_id=new_subnet['id'])
                        network_service.router_add_gateway(context,new_router['id'], new_ext_network['id'])
                    except Exception as err:
                        pass
        
    def workload_create(self, context, workload_id):
        """
        Create a scheduled workload in the workload scheduler
        """
        try:
            workload = self.db.workload_get(context, workload_id)
            vm = self.db.workload_vms_get(context, workload_id)

            LOG.info(_('create_workload started, %s:' %workload_id))
            self.db.workload_update(context, 
                                    workload_id, 
                                    {'host': self.host})

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

    def workload_snapshot(self, context, snapshot_id):
        """
        Take a snapshot of the workload
        """
        LOG.info(_('snapshot of workload started, snapshot_id %s' %snapshot_id))
        
        try:
            compute_service = nova.API(production=True)
            instances = compute_service.get_servers(context,admin=True)  
            hypervisors = compute_service.get_hypervisors(context)     
            
            snapshot = self.db.snapshot_get(context, snapshot_id)
            snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, snapshot.workload_id)
            full_snapshot_exists = False
            for snapshot in snapshots:
                if snapshot.snapshot_type == 'full' and snapshot.status == 'available':
                    full_snapshot_exists = True
                    break
    
            snapshot = self.db.snapshot_get(context, snapshot_id)
            if snapshot.snapshot_type != 'full' and full_snapshot_exists == True:
                snapshot.snapshot_type = 'incremental'
            else:
                snapshot.snapshot_type = 'full'

            self.db.snapshot_update(context, snapshot.id, {'snapshot_type': snapshot.snapshot_type})
           
            ############################################
            """
            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
    
            store = {
                "connection": FLAGS.sql_connection,     # taskflow persistence connection
                "context_dict": context_dict,           # context dictionary
                "snapshot_id": snapshot_id,             # snapshot_id
                "workload_id": snapshot.workload_id,    # workload_id
                
                "host": "mongodb1",                     # one of the nodes of mongodb cluster
                "port": 27017,                          # listening port of mongos service
                "username": "ubuntu",                   # mongodb admin user
                "password": "ubuntu",                   # mongodb admin password
                "hostuser": "ubuntu",                   # username on the host for ssh operations
                "hostpassword": "",                     # username on the host for ssh operations
                "sshport" : 22,                         # ssh port that defaults to 22
                "usesudo" : True,                       # use sudo when shutdown and restart of mongod instances
            }
            
            workflow = mongodbflow.MongoDBWorkflow("testflow", store)
            import pdb; pdb.set_trace()
            workflow.execute() 
            """
            ###########################################
            
            workload = self.db.workload_get(context, snapshot.workload_id)
            self.db.snapshot_update(context, snapshot.id, {'status': 'executing'})
            vault_service = vault.get_vault_service(context)
            for vm in self.db.workload_vms_get(context, snapshot.workload_id):
                vm_instance = None
                for instance in instances:
                    if vm.vm_id == instance.id:
                        vm_instance = instance
                        break;
                if vm_instance == None:
                    pass #TODO(giri): Throw exception
                
                vm_hypervisor = None
                for hypervisor in hypervisors:
                    if hypervisor.hypervisor_hostname == vm_instance.__dict__['OS-EXT-SRV-ATTR:host']:
                        vm_hypervisor = hypervisor
                if vm_hypervisor == None:
                    pass #TODO(giri): Throw exception
    
                if vm_hypervisor.hypervisor_type == 'QEMU': 
                    virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
                else: #TODO(giri) Check for all other hypervisor types
                    virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')
                
                #create an entry for the VM
                options = {'vm_id': vm.vm_id,
                           'vm_name': vm.vm_name,
                           'snapshot_id': snapshot_id,
                           'snapshot_type': snapshot.snapshot_type,
                           'status': 'creating',}
                snapshot_vm = self.db.snapshot_vm_create(context, options)
                
                # Create  a flavor resource
                flavor = compute_service.get_flavor_by_id(context, vm_instance.flavor['id'])
                metadata = {'name':flavor.name, 'vcpus':flavor.vcpus, 'ram':flavor.ram, 'disk':flavor.disk, 'ephemeral':flavor.ephemeral}
                snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                               'vm_id': snapshot_vm.vm_id,
                                               'snapshot_id': snapshot.id,       
                                               'resource_type': 'flavor',
                                               'resource_name':  flavor.name,
                                               'metadata': metadata,
                                               'status': 'available'}
                snapshot_vm_resource = self.db.snapshot_vm_resource_create(context,  snapshot_vm_resource_values)                         
                
                #disks snapshot 
                #import pdb; pdb.set_trace()
                #compute_service.vast_instance(context,snapshot_vm.vm_id) 
                #import pdb; pdb.set_trace()  
                virtdriver.snapshot(workload, snapshot, snapshot_vm, vm_hypervisor.hypervisor_hostname, vault_service, self.db, context)
                #TODO(giri): Check for the success (and update)
                self.db.snapshot_vm_update(context, snapshot_vm.id, {'status': 'executing'})
                #TODO(giri): handle the case where this can be updated by multiple workload snapshot requests 
                self.db.vm_recent_snapshot_update(context, vm.vm_id, {'snapshot_id': snapshot.id})
           
            self._snapshot_networks(context, True, snapshot)
            #TODO(gbasava): Check for the success (and update)                
            self.db.snapshot_update(context, snapshot.id, {'status': 'available'}) 
        
        except Exception as ex:
            msg = _("Error Creating Workload Snapshot %(snapshot_id)s with failure: %(exception)s")
            LOG.debug(msg, {'snapshot_id': snapshot_id, 'exception': ex})
            LOG.exception(ex)
            self.db.snapshot_update(context, snapshot.id, {'status': 'error'}) 
            return;          

        #workloadmgr_service = workloadmgr.API()
        #workloadmgr_service.hydrate(context, snapshot['id'])              

    def workload_delete(self, context, workload_id):
        """
        Delete an existing workload
        """
        LOG.info(_('deleting workload: %s'), workload_id)
        snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id)
        for snapshot in snapshots:
            self.snapshot_delete(context, snapshot['id'])
        self.db.workload_delete(context, workload_id)


    def snapshot_restore(self, context, restore_id):
        """
        Restore VMs and all its LUNs from a snapshot
        """
        LOG.info(_('restore_snapshot started, restore id: %(restore_id)s') % locals())
        try:
            restore = self.db.restore_get(context, restore_id)
            snapshot = self.db.snapshot_get(context, restore.snapshot_id)
            workload = self.db.workload_get(context, snapshot.workload_id)
            
            new_net_resources = {}
            if restore.restore_type == 'test':
                self._restore_networks(context, False, snapshot, restore, new_net_resources)
            else:
                self._restore_networks(context, True, snapshot, restore, new_net_resources)    
            vault_service = vault.get_vault_service(context)
            
            #restore each VM 
            #TODO(giri): If one VM restore fails, rollback the whole transaction
            for vm in self.db.snapshot_vm_get(context, snapshot.id): 
                virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
                restored_instance = virtdriver.snapshot_restore(workload, snapshot, restore, vm, vault_service, new_net_resources, self.db, context)
                restored_vm_values = {'vm_id': restored_instance.id,
                                      'vm_name':  restored_instance.name,    
                                      'restore_id': restore.id,
                                      'status': 'available'}
                restored_vm = self.db.restored_vm_create(context,restored_vm_values)    
                           
            self.db.restore_update(context, restore.id, {'status': 'completed'})
        except Exception as ex:
            msg = _("Error Restoring %(restore_id)s with failure: %(exception)s")
            LOG.debug(msg, {'restore_id': restore_id, 'exception': ex})
            LOG.exception(ex)
            self.db.restore_update(context, restore.id, {'status': 'error'}) 
            return;  

    def snapshot_delete(self, context, snapshot_id):
        """
        Delete an existing snapshot
        """
        LOG.info(_('deleting snapshot %s'), snapshot_id)        
        self.db.snapshot_delete(context, snapshot_id)
        
    def restore_delete(self, context, restore_id):
        """
        Delete an existing restore 
        """
        LOG.info(_('deleting restore %s'), restore_id)
        self.db.restore_delete(context, restore_id)        
 