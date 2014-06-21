# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to the  workloadmgr service.
"""
import socket
import cPickle as pickle

from eventlet import greenthread

from datetime import datetime
import time

from workloadmgr.apscheduler.scheduler import Scheduler
from workloadmgr.apscheduler.jobstores.sqlalchemy_store import SQLAlchemyJobStore
from sqlalchemy import create_engine

from novaclient import client
from workloadmgr.workloads import rpcapi as workloads_rpcapi
from workloadmgr.scheduler import rpcapi as scheduler_rpcapi
from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.image import glance
from workloadmgr import context


FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)

def _snapshot_create_callback(*args, **kwargs):
    from workloadmgr.workloads import API

    workloadmgrapi = API()
 
    workload_id = kwargs['workload_id']
    user_id = kwargs['user_id']
    project_id = kwargs['project_id']
    tenantcontext = nova._get_tenant_context(user_id, project_id)
    
    workload = workloadmgrapi.workload_get(tenantcontext, workload_id)

    #TODO: Make sure workload is in a created state
    if workload['status'] == 'error':
        msg = _("Workload is in error state. Cannot schedule snapshot operation")
        LOG.info(msg, {'workload_id': workload_id})
        return

    # wait for 5 minutes until the workload changes state to available
    count = 0
    while True:
        if workload['status'] == "available" or workload['status'] == 'error' or count > 10:
            break
        time.sleep(30)
        count += 1
        workload = workloadmgrapi.workload_get(tenantcontext, workload_id)

    # if workload hasn't changed the status to available
    if workload['status'] != 'available':
        msg = _("Workload is not in available state. Cannot schedule snapshot operation")
        LOG.info(msg, {'workload_id': workload_id})
        return

    try:
        snapshot = workloadmgrapi.workload_snapshot(tenantcontext, workload_id, "incremental", "jobscheduler", None)

        # Wait for snapshot to complete
        while True:
            snapshot_details = workloadmgrapi.snapshot_get(tenantcontext, snapshot['id'])
            if snapshot_details['status'].lower() == "available" or snapshot_details['status'].lower() == "error":
                break
            time.sleep(30)
    except Exception as ex:
        LOG.exception(_("Error creating a snapshot for workload %d") % workload_id)
        pass

class API(base.Base):
    """API for interacting with the Workload Manager."""

    ## This singleton implementation is not thread safe
    ## REVISIT: should the singleton be threadsafe

    __single = None # the one, true Singleton

    def __new__(classtype, *args, **kwargs):
        # Check to see if a __single exists already for this class
        # Compare class types instead of just looking for None so
        # that subclasses will create their own __single objects
        if classtype != type(classtype.__single):
            classtype.__single = object.__new__(classtype, *args, **kwargs)
        return classtype.__single

    def __init__(self, db_driver=None):
        if not hasattr(self, "workloads_rpcapi"):
            self.workloads_rpcapi = workloads_rpcapi.WorkloadMgrAPI()

        if not hasattr(self, "scheduler_rpcapi"):
           self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()

        if not hasattr(self, "_engine"):
            self._engine = create_engine(FLAGS.sql_connection)

        if not hasattr(self, "_jobstore"):
            self._jobstore = SQLAlchemyJobStore(engine=self._engine)

        if not hasattr(self, "_scheduler"):
            self._scheduler = Scheduler()
            self._scheduler.add_jobstore(self._jobstore, 'jobscheduler_store')
            self._scheduler.start()

            super(API, self).__init__(db_driver)
        
    def workload_type_get(self, context, workload_type_id):
        workload_type = self.db.workload_type_get(context, workload_type_id)
        workload_type_dict = dict(workload_type.iteritems())
        metadata = {}
        for kvpair in workload_type.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_type_dict['metadata'] = metadata        
        return workload_type_dict

    def workload_type_show(self, context, workload_type_id):
        workload_type = self.db.workload_type_get(context, workload_type_id)
        workload_type_dict = dict(workload_type.iteritems())
        metadata = {}
        for kvpair in workload_type.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_type_dict['metadata'] = metadata
        return workload_type_dict
    
    def workload_type_get_all(self, context, search_opts={}):
        workload_types = self.db.workload_types_get(context)
        return workload_types
    
    def workload_type_create(self, context, name, description, is_public, metadata):
        """
        Create a workload_type. No RPC call is made
        """
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'display_name': name,
                   'display_description': description,
                   'is_public' : is_public,
                   'status': 'available',
                   'metadata': metadata,}

        workload_type = self.db.workload_type_create(context, options)
        return workload_type
    
    def workload_type_delete(self, context, workload_type_id):
        """
        Delete a workload_type. No RPC call is made
        """
        workload_type = self.workload_type_get(context, workload_type_id)
        if workload_type['status'] not in ['available', 'error']:
            msg = _('WorkloadType status must be available or error')
            raise exception.InvalidWorkloadMgr(reason=msg)

        #TODO(giri): check if this workload_type is referenced by other workloads
                    
        self.db.workload_type_delete(context, workload_type_id)
        
    def workload_type_discover_instances(self, context, workload_type_id, metadata):
        """
        Discover Instances of a workload_type. RPC call is made
        """
        return self.workloads_rpcapi.workload_type_discover_instances(context,
                                                                      socket.gethostname(),
                                                                      workload_type_id,
                                                                      metadata) 

    def workload_get(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        
        workload_vm_ids = []
        for workload_vm in self.db.workload_vms_get(context, workload.id):
            workload_vm_ids.append(workload_vm.vm_id)  
        workload_dict['vm_ids'] = workload_vm_ids
        
        metadata = {}
        for kvpair in workload.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_dict['metadata'] = metadata        
        
                
        workload_dict['jobschedule'] = pickle.loads(str(workload.jobschedule))
        workload_dict['jobschedule']['enabled'] = False

        # find the job object based on workload_id
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                workload_dict['jobschedule']['enabled'] = True
                break


        return workload_dict

    def workload_show(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        
        workload_vm_ids = []
        for workload_vm in self.db.workload_vms_get(context, workload.id):
            workload_vm_ids.append(workload_vm.vm_id)  
        workload_dict['vm_ids'] = workload_vm_ids
        
        metadata = {}
        for kvpair in workload.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_dict['metadata'] = metadata
        
        workload_dict['jobschedule'] = pickle.loads(str(workload.jobschedule))
        workload_dict['jobschedule']['enabled'] = False 

        # find the job object based on workload_id
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                workload_dict['jobschedule']['enabled'] = True
                break

                
        return workload_dict
    
    def workload_get_all(self, context, search_opts={}):
        if context.is_admin:
            workloads = self.db.workload_get_all(context)
        else:
            workloads = self.db.workload_get_all_by_project(context,
                                                        context.project_id)

        return workloads
    
    def workload_create(self, context, name, description, workload_type_id,
                        instances, jobschedule, metadata,
                        availability_zone=None):
        """
        Make the RPC call to create a workload.
        """
        compute_service = nova.API(production=True)
        instances_with_name = compute_service.get_servers(context,admin=True)

        #TODO(giri): optimize this lookup
        for instance in instances:
            for instance_with_name in instances_with_name:
                if instance['instance-id'] == instance_with_name.id:
                    instance['instance-name'] = instance_with_name.name 
                   
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'display_name': name,
                   'display_description': description,
                   'status': 'creating',
                   'workload_type_id': workload_type_id,
                   'metadata' : metadata,
                   'jobschedule': pickle.dumps(jobschedule, 0),
                   'host': socket.gethostname(), }

        workload = self.db.workload_create(context, options)
        for instance in instances:
            values = {'workload_id': workload.id,
                      'vm_id': instance['instance-id'],
                      'vm_name': instance['instance-name']}
            vm = self.db.workload_vms_create(context, values)

        self.workloads_rpcapi.workload_create(context,
                                              workload['host'],
                                              workload['id'])

        # Now register the job with job scheduler
        # HEre is the catch. The workload may not been fully created yet
        # so the job call back should only start creating snapshots when
        # the workload is successfully created.
        # the workload has errored during workload creation, then it should
        # remove itself from the job queue
        # if we fail to schedule the job, we should fail the 
        # workload create request?
        #_snapshot_create_callback([], kwargs={  'workload_id':workload.id,  
        #                                        'user_id': workload.user_id, 
        #                                        'project_id':workload.project_id})
        #
        #               jobschedule = {'start_date': '06/05/2014',
        #                              'end_date': '07/05/2015',
        #                              'interval': '1 hr',
        #                              'start_time': '2:30 PM',
        #                              'snapshots_to_keep': '2'}
        
        if len(jobschedule):                                        
            self._scheduler.add_workloadmgr_job(_snapshot_create_callback, 
                                                jobschedule,
                                                jobstore='jobscheduler_store', 
                                                kwargs={'workload_id':workload.id,  
                                                        'user_id': workload.user_id, 
                                                        'project_id':workload.project_id})
        
        
        return workload

    def workload_modify(self, context, workload_id, workload):
        """
        Make the RPC call to create a workload.
        """
        compute_service = nova.API(production=True)
        instances_with_name = compute_service.get_servers(context,admin=True)

        try:
           self.workload_pause(context, workload_id)
        except:
           pass

        #TODO(giri): optimize this lookup
                   
        options = {'display_name': workload['workload']['name'],
                   'display_description': workload['workload']['description'],
                   'metadata' : workload['workload']['metadata'],
                   'jobschedule': pickle.dumps(workload['workload']['jobschedule'], 0),}

        self.db.workload_update(context, workload_id, options)
        # TODO: Update only when there is change is instances
        #for instance in workload['workload']['instances']:
            #for instance_with_name in instances_with_name:
                #if instance['instance-id'] == instance_with_name.id:
                    #instance['instance-name'] = instance_with_name.name 
        #for instance in workload.instances:
            #values = {'workload_id': workload['workload']['id'],
                      #'vm_id': instance['instance-id'],
                      #'vm_name': instance['instance-name']}
            #vm = self.db.workload_vms_create(context, values)

        self.workload_resume(context, workload_id)
    
    def workload_delete(self, context, workload_id):
        """
        Delete a workload. No RPC call is made
        """
        workload = self.workload_get(context, workload_id)
        if workload['status'] not in ['available', 'error']:
            msg = _('Workload status must be available or error')
            raise exception.InvalidWorkloadMgr(reason=msg)

        snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id)
        if len(snapshots) > 0:
            msg = _('This workload contains snapshots')
            raise exception.InvalidWorkloadMgr(reason=msg)
                    
        # First unschedule the job
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                self._scheduler.unschedule_job(job)
                break

        self.db.workload_delete(context, workload_id)
        
    def workload_get_workflow(self, context, workload_id):
        """
        Get the workflow of the workload. RPC call is made
        """
        return self.workloads_rpcapi.workload_get_workflow_details(context,
                                                                   socket.gethostname(),
                                                                   workload_id)    
    def workload_get_topology(self, context, workload_id):
        """
        Get the topology of the workload. RPC call is made
        """
        return self.workloads_rpcapi.workload_get_topology(context,
                                                           socket.gethostname(),
                                                           workload_id)                
             
    def workload_pause(self, context, workload_id):
        """
        Pause workload job schedule. No RPC call is made
        """
        paused = False
        workload = self.workload_get(context, workload_id)
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                self._scheduler.unschedule_job(job)
                paused = True
                break

        if not paused:
           msg = _('Workload job scheduler is already paused')
           raise exception.InvalidWorkloadMgr(reason=msg)

    def workload_resume(self, context, workload_id):
        workload = self.workload_get(context, workload_id)
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                msg = _('Workload job scheduler is not paused')
                raise exception.InvalidWorkloadMgr(reason=msg)
        jobschedule = workload['jobschedule']
        if len(jobschedule) < 5:
                msg = _('Job scheduler settings are not available')
                raise exception.InvalidWorkloadMgr(reason=msg)            
   
        self._scheduler.add_workloadmgr_job(_snapshot_create_callback, 
                                            jobschedule,
                                            jobstore='jobscheduler_store', 
                                            kwargs={'workload_id':workload_id,  
                                                    'user_id': workload['user_id'],
                                                    'project_id':workload['project_id']})

    def workload_snapshot(self, context, workload_id, snapshot_type, name, description):
        """
        Make the RPC call to snapshot a workload.
        """
        workload = self.workload_get(context, workload_id)
        if workload['status'] in ['running']:
            msg = _('Workload snapshot job is already executing, ignoring this execution')
            raise exception.InvalidWorkloadMgr(reason=msg)

        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'workload_id': workload_id,
                   'snapshot_type': snapshot_type,
                   'display_name': name,
                   'display_description': description,                   
                   'status': 'creating',}
        snapshot = self.db.snapshot_create(context, options)
        self.scheduler_rpcapi.workload_snapshot(context, FLAGS.scheduler_topic, snapshot['id'])
        return snapshot

    def snapshot_get(self, context, snapshot_id):
        rv = self.db.snapshot_get(context, snapshot_id)
        snapshot_details  = dict(rv.iteritems())
        instances = []
        try:
            vms = self.db.snapshot_vms_get(context, snapshot_id)
            for vm in vms:
                instances.append(dict(vm.iteritems()))
        except Exception as ex:
            pass
        snapshot_details.setdefault('instances', instances)    
        return snapshot_details

    def snapshot_show(self, context, snapshot_id):
        def _get_pit_resource_id(metadata, key):
            for metadata_item in metadata:
                if metadata_item['key'] == key:
                    pit_id = metadata_item['value']
                    return pit_id
                
        def _get_pit_resource(snapshot_vm_common_resources, pit_id):
            for snapshot_vm_resource in snapshot_vm_common_resources:
                if snapshot_vm_resource.resource_pit_id == pit_id:
                    return snapshot_vm_resource
                         
        rv = self.db.snapshot_show(context, snapshot_id)
        snapshot_details  = dict(rv.iteritems())
        instances = []
        try:
            vms = self.db.snapshot_vms_get(context, snapshot_id)
            for vm in vms:
                instance = dict(vm.iteritems())
                instance['nics'] = []
                snapshot_vm_resources = self.db.snapshot_vm_resources_get(context, vm.vm_id, snapshot_id)
                snapshot_vm_common_resources = self.db.snapshot_vm_resources_get(context, snapshot_id, snapshot_id)                
                for snapshot_vm_resource in snapshot_vm_resources:                
                    """ flavor """
                    if snapshot_vm_resource.resource_type == 'flavor': 
                        vm_flavor = snapshot_vm_resource
                        instance['flavor'] = {'vcpus' : self.db.get_metadata_value(vm_flavor.metadata, 'vcpus'),
                                              'ram' : self.db.get_metadata_value(vm_flavor.metadata, 'ram'),
                                              'disk': self.db.get_metadata_value(vm_flavor.metadata, 'disk'),
                                              'ephemeral': self.db.get_metadata_value(vm_flavor.metadata, 'ephemeral')
                                              }
                    """ nics """
                    if snapshot_vm_resource.resource_type == 'nic':
                        vm_nic_snapshot = self.db.vm_network_resource_snap_get(context, snapshot_vm_resource.id)
                        nic_data = pickle.loads(str(vm_nic_snapshot.pickle))
                        nic = {'mac_address': nic_data['mac_address'],
                               'ip_address': nic_data['ip_address'],}
                        nic['network'] = {'id': self.db.get_metadata_value(vm_nic_snapshot.metadata, 'network_id'),
                                          'name': self.db.get_metadata_value(vm_nic_snapshot.metadata, 'network_name')}
                        
                        pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'subnet_id')                        
                        vm_nic_subnet = _get_pit_resource(snapshot_vm_common_resources, pit_id)
                        vm_nic_subnet_snapshot = self.db.vm_network_resource_snap_get(context, vm_nic_subnet.id)
                        subnet = pickle.loads(str(vm_nic_subnet_snapshot.pickle))
                        nic['network']['subnet'] = { 'id' :subnet.get('id', None),
                                                     'name':subnet.get('name', None),
                                                     'cidr':subnet.get('cidr', None),
                                                     'ip_version':subnet.get('ip_version', None),
                                                     'gateway_ip':subnet.get('gateway_ip', None),
                                                     }
                        instance['nics'].append(nic)
                instances.append(instance)
        except Exception as ex:
            pass
        snapshot_details['instances'] = instances    
        return snapshot_details
    
    def snapshot_get_all(self, context, workload_id=None):
        if workload_id:
            snapshots = self.db.snapshot_get_all_by_project_workload(
                                                    context,
                                                    context.project_id,
                                                    workload_id)
        elif context.is_admin:
            snapshots = self.db.snapshot_get_all(context)
        else:
            snapshots = self.db.snapshot_get_all_by_project(
                                        context,context.project_id)
        return snapshots
    
    def snapshot_delete(self, context, snapshot_id):
        """
        Delete a workload snapshot. No RPC call required
        """
        snapshot = self.snapshot_get(context, snapshot_id)
        """
        if snapshot['status'] not in ['available', 'error']:
            msg = _('Snapshot status must be available or error')
            raise exception.InvalidWorkloadMgr(reason=msg)
        """
        restores = self.db.restore_get_all_by_project_snapshot(context, context.project_id, snapshot_id)
        for restore in restores:
            if restore.restore_type == 'test':
                msg = _('This workload snapshot contains testbubbles')
                raise exception.InvalidWorkloadMgr(reason=msg)      

        self.db.snapshot_delete(context, snapshot_id)
        
    def snapshot_restore(self, context, snapshot_id, test, name, description, options):
        """
        Make the RPC call to restore a snapshot.
        """
        snapshot = self.snapshot_get(context, snapshot_id)
        workload = self.workload_get(context, snapshot['workload_id'])
        if snapshot['status'] != 'available':
            msg = _('Snapshot status must be available')
            raise exception.InvalidWorkloadMgr(reason=msg)
        
        restore_type = "restore"
        if test:
            restore_type = "test"
        values = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'snapshot_id': snapshot_id,
                   'restore_type': restore_type,
                   'display_name': name,
                   'display_description': description,
                   'pickle': pickle.dumps(options, 0),
                   'status': 'restoring',}
        restore = self.db.restore_create(context, values)
        self.workloads_rpcapi.snapshot_restore(context, workload['host'], restore['id'])
        return restore

    def restore_get(self, context, restore_id):
        rv = self.db.restore_get(context, restore_id)
        restore_details  = dict(rv.iteritems())
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id)
        restore_details.setdefault('workload_id', snapshot.workload_id)
                
        instances = []
        try:
            vms = self.db.restore_vm_get(context, restore_id)
            for vm in vms:
                instances.append(dict(vm.iteritems()))
        except Exception as ex:
            pass
        restore_details.setdefault('instances', instances)    
        return restore_details

    def restore_show(self, context, restore_id):
        rv = self.db.restore_show(context, restore_id)
        restore_details  = dict(rv.iteritems())
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id)
        restore_details.setdefault('workload_id', snapshot.workload_id)
        
        instances = []
        try:
            vms = self.db.restored_vm_get(context, restore_id)
            for vm in vms:
                instances.append({'id':vm.vm_id, 'name':vm.vm_name})
        except Exception as ex:
            pass
        restore_details.setdefault('instances', instances) 
        
        ports_list = []
        networks_list = []
        subnets_list = []
        routers_list = []
        flavors_list = []
        security_groups_list = []
        try:
            resources = self.db.restored_vm_resources_get(context, restore_id, restore_id)
            for resource in resources:
                if resource.resource_type == 'port':
                    ports_list.append({'id':resource.id, 'name':resource.resource_name})                
                if resource.resource_type == 'network':
                    networks_list.append({'id':resource.id, 'name':resource.resource_name})
                elif resource.resource_type == 'subnet':
                    subnets_list.append({'id':resource.id, 'name':resource.resource_name})
                elif resource.resource_type == 'router':
                    routers_list.append({'id':resource.id, 'name':resource.resource_name})   
                elif resource.resource_type == 'flavor':
                    flavors_list.append({'id':resource.id, 'name':resource.resource_name}) 
                elif resource.resource_type == 'security_group':
                    security_groups_list.append({'id':resource.id, 'name':resource.resource_name})
                    
        except Exception as ex:
            pass        
        restore_details.setdefault('ports', ports_list)
        restore_details.setdefault('networks', networks_list) 
        restore_details.setdefault('subnets', subnets_list)
        restore_details.setdefault('routers', routers_list) 
        restore_details.setdefault('flavors', flavors_list) 
        restore_details.setdefault('security_groups', security_groups_list)                
        return restore_details
    
    def restore_get_all(self, context, snapshot_id=None):
        if snapshot_id:
            restores = self.db.restore_get_all_by_project_snapshot(
                                                    context,
                                                    context.project_id,
                                                    snapshot_id)
        elif context.is_admin:
            restores = self.db.restore_get_all(context)
        else:
            restores = self.db.restore_get_all_by_project(
                                        context,context.project_id)
        return restores
    
    def restore_delete(self, context, restore_id):
        """
        Delete a workload restore. RPC call may be required
        """
        restore_details = self.restore_show(context, restore_id)
        
        if restore_details['status'] not in ['available', 'error']:
            msg = _('Restore or Testbubble status must be completed or error')
            raise exception.InvalidWorkloadMgr(reason=msg)

        if restore_details['restore_type'] == 'test':
            network_service =  neutron.API(production=False)
            compute_service = nova.API(production=False)
        else:
            network_service =  neutron.API(production=True)
            compute_service = nova.API(production=True)
            
        image_service = glance.get_default_image_service(production= (restore_details['restore_type'] != 'test'))                    
            
        for instance in restore_details['instances']:
            try:
                vm = compute_service.get_server_by_id(context, instance['id'])
                compute_service.delete(context, instance['id']) 
                image_service.delete(context, vm.image['id'])
                #TODO(giri): delete the cinder volumes
            except Exception as exception:
                msg = _("Error deleting instance %(instance_id)s with failure: %(exception)s")
                LOG.debug(msg, {'instance_id': instance['id'], 'exception': exception})
                LOG.exception(exception)
                
        for port in restore_details['ports']:
            try:
                network_service.delete_port(context,port['id'])
            except Exception as exception:
                msg = _("Error deleting port %(port_id)s with failure: %(exception)s")
                LOG.debug(msg, {'port_id': port['id'], 'exception': exception})
                LOG.exception(exception)                 
                                
        for router in restore_details['routers']:
            try:
                network_service.delete_router(context,router['id'])
            except Exception as exception:
                msg = _("Error deleting router %(router_id)s with failure: %(exception)s")
                LOG.debug(msg, {'router_id': router['id'], 'exception': exception})
                LOG.exception(exception)  
                              
        for subnet in restore_details['subnets']:
            try:
                network_service.delete_subnet(context,subnet['id'])
            except Exception as exception:
                msg = _("Error deleting subnet %(subnet_id)s with failure: %(exception)s")
                LOG.debug(msg, {'subnet_id': subnet['id'], 'exception': exception})
                LOG.exception(exception)      
                             
        for network in restore_details['networks']:
            try:
                network_service.delete_network(context,network['id'])
            except Exception as exception:
                msg = _("Error deleting network %(network_id)s with failure: %(exception)s")
                LOG.debug(msg, {'network_id': network['id'], 'exception': exception})
                LOG.exception(exception) 
                
        for flavor in restore_details['flavors']:
            try:
                compute_service.delete_flavor(context,flavor['id'])
            except Exception as exception:
                msg = _("Error deleting flavor %(flavor_id)s with failure: %(exception)s")
                LOG.debug(msg, {'flavor_id': flavor['id'], 'exception': exception})
                LOG.exception(exception)                                     

        for security_group in restore_details['security_groups']:
            try:
                network_service.security_group_delete(context,security_group['id'])
            except Exception as exception:
                msg = _("Error deleting security_group %(security_group_id)s with failure: %(exception)s")
                LOG.debug(msg, {'security_group_id': security_group['id'], 'exception': exception})
                LOG.exception(exception)

        self.db.restore_delete(context, restore_id)
        
