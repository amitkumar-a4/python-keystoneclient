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
from workloadmgr.workflows import vmtasks_openstack
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB

from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

workloads_manager_opts = [
]

scheduler_config = {'standalone': 'True'}

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)

def get_workflow_class(context, workload_type_id):
    #TODO(giri): implement a driver model for the workload types
    workflow_class_name = 'workloadmgr.workflows.restoreworkflow.RestoreWorkflow'
    if workload_type_id:
        workload_type = WorkloadMgrDB().db.workload_type_get(context, workload_type_id)
        if(workload_type.display_name == 'Serial'):
            workflow_class_name = 'workloadmgr.workflows.serialworkflow.SerialWorkflow'
        elif(workload_type.display_name == 'Parallel'):
            workflow_class_name = 'workloadmgr.workflows.parallelworkflow.ParallelWorkflow'
        elif(workload_type.display_name == 'MongoDB'):
            workflow_class_name = 'workloadmgr.workflows.mongodbflow.MongoDBWorkflow'   
        elif(workload_type.display_name == 'Hadoop'):
            workflow_class_name = 'workloadmgr.workflows.hadoopworkflow.HadoopWorkflow' 
        elif(workload_type.display_name == 'Cassandra'):
            workflow_class_name = 'workloadmgr.workflows.cassandraworkflow.CassandraWorkflow'             
        elif(workload_type.display_name == 'Composite'):
            workflow_class_name = 'workloadmgr.workflows.compositeworkflow.CompositeWorkflow'             
                      
    parts = workflow_class_name.split('.')
    module = ".".join(parts[:-1])
    workflow_class = __import__( module )
    for comp in parts[1:]:
        workflow_class = getattr(workflow_class, comp)            
    return workflow_class        
    
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
        
    def _get_snapshot_size_of_vm(self, context, snapshot_vm):
        """
        calculate the restore data size
        """  
        instance_size = 0          
        snapshot_vm_resources = self.db.snapshot_vm_resources_get(context, snapshot_vm.vm_id, snapshot_vm.snapshot_id)
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type != 'disk':
                continue
            vm_disk_resource_snap = self.db.vm_disk_resource_snap_get_top(context, snapshot_vm_resource.id)
            instance_size = instance_size + vm_disk_resource_snap.size
            while vm_disk_resource_snap.vm_disk_resource_snap_backing_id is not None:
                vm_disk_resource_snap_backing = self.db.vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                instance_size = instance_size + vm_disk_resource_snap_backing.size
                vm_disk_resource_snap  = vm_disk_resource_snap_backing                           

        return instance_size                  
        

        
    def _get_metadata_value(self, vm_network_resource_snap, key):
        for metadata in vm_network_resource_snap.metadata:
            if metadata['key'] == key:
                return metadata['value']
                
    @autolog.log_method(logger=Logger)        
    def workload_type_discover_instances(self, context, workload_type_id, metadata):
        """
        Discover instances of a workload_type
        """        
        context_dict = dict([('%s' % key, value)
                          for (key, value) in context.to_dict().iteritems()])            
        context_dict['conf'] =  None # RpcContext object looks for this during init
        store = {
            'context': context_dict,                # context dictionary
        }

        for key in metadata:
            store[key] = metadata[key]
        
        workflow_class = get_workflow_class(context, workload_type_id)
        workflow = workflow_class("discover_instances", store)
        instances = workflow.discover()
        return instances   

    @autolog.log_method(logger=Logger)
    def workload_get_topology(self, context, workload_id):
        """
        Return workload topology
        """        
        context_dict = dict([('%s' % key, value)
                          for (key, value) in context.to_dict().iteritems()])            
        context_dict['conf'] =  None # RpcContext object looks for this during init
        store = {
                'context': context_dict,                # context dictionary
                'workload_id': workload_id,             # workload_id
        }
        workload = self.db.workload_get(context, workload_id)
        for kvpair in workload.metadata:
            store[kvpair['key']] = kvpair['value']
            
        workflow_class = get_workflow_class(context, workload.workload_type_id)
        workflow = workflow_class("workload_topology", store)
        topology = workflow.topology()
        return topology
    
    @autolog.log_method(logger=Logger)    
    def workload_get_workflow_details(self, context, workload_id):
        """
        Return workload topology
        """        
        context_dict = dict([('%s' % key, value)
                          for (key, value) in context.to_dict().iteritems()])            
        context_dict['conf'] =  None # RpcContext object looks for this during init
        store = {
                'context': context_dict,                # context dictionary
                'workload_id': workload_id,             # workload_id
        }
        workload = self.db.workload_get(context, workload_id)
        for kvpair in workload.metadata:
            store[kvpair['key']] = kvpair['value']
            
        workflow_class = get_workflow_class(context, workload.workload_type_id)
        workflow = workflow_class("workload_workflow_details", store)
        workflow.initflow()
        details = workflow.details()
        return details
    
    @autolog.log_method(Logger, 'WorkloadMgrManager.workload_create')
    def workload_create(self, context, workload_id):
        """
        Create a scheduled workload in the workload scheduler
        """
        try:
            workload = self.db.workload_get(context, workload_id)
            #vm = self.db.workload_vms_get(context, workload_id)

            self.db.workload_update(context, 
                                    workload_id, 
                                    {'host': self.host})

        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.workload_update(context, workload_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})

        self.db.workload_update(context, 
                                workload_id, 
                                {'status': 'available',
                                 'availability_zone': self.az})
        
    @autolog.log_method(logger=Logger)
    def workload_snapshot(self, context, snapshot_id):
        """
        Take a snapshot of the workload
        """
        try:
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 0, 
                                     'progress_msg': 'Snapshot of workload is starting',
                                     'status': 'starting'
                                    })
            
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
           
            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'connection': FLAGS.sql_connection,     # taskflow persistence connection
                'context': context_dict,                # context dictionary
                'snapshot': dict(snapshot.iteritems()), # snapshot dictionary
                'workload_id': snapshot.workload_id,    # workload_id                
            }
            workload = self.db.workload_get(context, snapshot.workload_id)
            for kvpair in workload.metadata:
                store[kvpair['key']] = kvpair['value']
                
            workflow_class = get_workflow_class(context, workload.workload_type_id)
            workflow = workflow_class(workload.display_name, store)
            workflow.initflow()
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 0, 
                                     'progress_msg': 'Snapshot of workload is starting',
                                     'status': 'executing'
                                    })            
            workflow.execute()
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': 'Snapshot of workload is complete',
                                     'status': 'available'
                                    })             
            return 
         
        except Exception as ex:
            msg = _("Error creating workload snapshot %(snapshot_id)s with failure: %(exception)s") %{
                    'snapshot_id': snapshot_id, 'exception': ex,}
            LOG.debug(msg)
            LOG.exception(ex)
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'status': 'error'
                                    })             
            return;          
            
    @autolog.log_method(logger=Logger)
    def workload_delete(self, context, workload_id):
        """
        Delete an existing workload
        """
        snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id)
        for snapshot in snapshots:
            self.snapshot_delete(context, snapshot['id'])
        self.db.workload_delete(context, workload_id)

    @autolog.log_method(logger=Logger)
    def snapshot_restore(self, context, restore_id):
        """
        Restore VMs and all its LUNs from a snapshot
        """
        restore_type = 'restore'
        try:
            restore = self.db.restore_get(context, restore_id)
            snapshot = self.db.snapshot_get(context, restore.snapshot_id)
            
            restore_type = restore.restore_type
            
            if restore_type == 'test':
                self.db.restore_update( context, 
                            restore_id, 
                            {'progress_percent': 0, 
                             'progress_msg': 'Create testbubble from snapshot is starting',
                             'status': 'starting'
                            })  
            else:
                self.db.restore_update( context, 
                            restore_id, 
                            {'progress_percent': 0, 
                             'progress_msg': 'Restore from snapshot is starting',
                             'status': 'starting'
                            })
            
            self.db.restore_update(context, restore.id, {'status': 'executing'})
                         
            restore_size = vmtasks_openstack.get_restore_data_size( context, self.db, dict(restore.iteritems()))
            if restore_type == 'test':                     
                self.db.restore_update( context, restore_id, {'size': restore_size})
            else:
                self.db.restore_update( context, restore_id, {'size': (restore_size * 2)})
                
            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'connection': FLAGS.sql_connection,     # taskflow persistence connection
                'context': context_dict,                # context dictionary
                'restore': dict(restore.iteritems()),   # restore dictionary
            }
                
            workflow_class = get_workflow_class(context, None)
            workflow = workflow_class(restore.display_name, store)
            workflow.initflow()
            workflow.execute()                                                
            
            if restore_type == 'test':
                self.db.restore_update( context, 
                            restore_id, 
                            {'progress_percent': 100, 
                             'progress_msg': 'Create testbubble from snapshot is complete',
                             'status': 'available'
                            })  
            else:
                self.db.restore_update( context, 
                            restore_id, 
                            {'progress_percent': 100, 
                             'progress_msg': 'Restore from snapshot is complete',
                             'status': 'available'
                            })                         

        except Exception as ex:
            if restore_type == 'test':
                msg = _("Error creating test bubble %(restore_id)s with failure: %(exception)s") %{
                        'restore_id': restore_id, 'exception': ex,}
            else:
                msg = _("Error restoring %(restore_id)s with failure: %(exception)s") %{
                        'restore_id': restore_id, 'exception': ex,}
            LOG.debug(msg)
            LOG.exception(ex)
            self.db.restore_update( context, 
                                    restore_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'status': 'error'
                                    })             
            return;                  
    @autolog.log_method(logger=Logger)
    def snapshot_delete(self, context, snapshot_id):
        """
        Delete an existing snapshot
        """
        self.db.snapshot_delete(context, snapshot_id)

    @autolog.log_method(logger=Logger)        
    def restore_delete(self, context, restore_id):
        """
        Delete an existing restore 
        """
        self.db.restore_delete(context, restore_id)        
 
