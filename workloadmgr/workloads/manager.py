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
from threading import Lock


from oslo.config import cfg

from workloadmgr import context
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr import manager
from workloadmgr.virt import driver
from workloadmgr.virt import virtapi
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import jsonutils
from workloadmgr.apscheduler.scheduler import Scheduler
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.vault import vault
from workloadmgr.workflows import vmtasks_openstack
from workloadmgr.workflows import vmtasks_vcloud
from workloadmgr.workflows import vmtasks
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import exception as wlm_exceptions
from workloadmgr.openstack.common import timeutils

from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

workloads_manager_opts = [
]

scheduler_config = {'standalone': 'True'}

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)
       

def get_workflow_class(context, workload_type_id, restore=False):
    #TODO(giri): implement a driver model for the workload types
    if workload_type_id:
        workload_type = WorkloadMgrDB().db.workload_type_get(context, workload_type_id)
        if(workload_type.display_name == 'Serial'):
            if restore:
                workflow_class_name = 'workloadmgr.workflows.restoreworkflow.RestoreWorkflow'
            else:
                workflow_class_name = 'workloadmgr.workflows.serialworkflow.SerialWorkflow'
        elif(workload_type.display_name == 'Parallel'):
            if restore:
                workflow_class_name = 'workloadmgr.workflows.restoreworkflow.RestoreWorkflow'
            else:
                workflow_class_name = 'workloadmgr.workflows.parallelworkflow.ParallelWorkflow'
        elif(workload_type.display_name == 'MongoDB'):
            if restore:
                workflow_class_name = 'workloadmgr.workflows.restoreworkflow.RestoreWorkflow'
            else:
                workflow_class_name = 'workloadmgr.workflows.mongodbflow.MongoDBWorkflow'   
        elif(workload_type.display_name == 'Hadoop'):
            if restore:
                workflow_class_name = 'workloadmgr.workflows.restoreworkflow.RestoreWorkflow'
            else:
                workflow_class_name = 'workloadmgr.workflows.hadoopworkflow.HadoopWorkflow' 
        elif(workload_type.display_name == 'Cassandra'):
            if restore:
                workflow_class_name = 'workloadmgr.workflows.cassandraworkflow.CassandraRestore'             
            else:
                workflow_class_name = 'workloadmgr.workflows.cassandraworkflow.CassandraWorkflow'             
        elif(workload_type.display_name == 'Composite'):
            if restore:
                workflow_class_name = 'workloadmgr.workflows.restoreworkflow.RestoreWorkflow'
            else:
                workflow_class_name = 'workloadmgr.workflows.compositeworkflow.CompositeWorkflow'             
                      
    parts = workflow_class_name.split('.')
    module = ".".join(parts[:-1])
    workflow_class = __import__( module )
    for comp in parts[1:]:
        workflow_class = getattr(workflow_class, comp)            
    return workflow_class        

workloadlock = Lock()
def synchronized(lock):
    '''Synchronization decorator.'''
    def wrap(f):
        def new_function(*args, **kw):
            lock.acquire()
            try:
                return f(*args, **kw)
            finally:
                lock.release()
        return new_function
    return wrap
  
    
class WorkloadMgrManager(manager.SchedulerDependentManager):
    """Manages WorkloadMgr """

    RPC_API_VERSION = '1.0'

    def __init__(self, service_name=None, *args, **kwargs):
        self.az = FLAGS.storage_availability_zone
        self.scheduler = Scheduler(scheduler_config)
        self.scheduler.start()
        self.driver = driver.load_compute_driver(None, None)
        super(WorkloadMgrManager, self).__init__(service_name='workloadscheduler',*args, **kwargs)
        
    def init_host(self):
        """
        Do any initialization that needs to be run if this is a standalone service.
        """

        ctxt = context.get_admin_context()

        LOG.info(_("Cleaning up incomplete operations"))
        
        self.db.snapshot_mark_incomplete_as_error(ctxt, self.host)
        self.db.restore_mark_incomplete_as_error(ctxt, self.host)        
        
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
    def workload_type_discover_instances(self, context, workload_type_id,
                                         metadata, workload_id=None):
        """
        Discover instances of a workload_type
        """        
        context_dict = dict([('%s' % key, value)
                          for (key, value) in context.to_dict().iteritems()])            
        context_dict['conf'] =  None # RpcContext object looks for this during init
        store = {
            'context': context_dict,                # context dictionary
            'source_platform': 'openstack',
            'workload_id': workload_id,
        }

        for key in metadata:
            store[key] = metadata[key]
        
        workflow_class = get_workflow_class(context, workload_type_id)
        workflow = workflow_class("discover_instances", store)
        instances = workflow.discover()
        return instances   

    @autolog.log_method(logger=Logger)        
    def workload_discover_instances(self, context, workload_id):
        """
        Discover instances of workload
        """        
        workload = self.db.workload_get(context, workload_id)
        context_dict = dict([('%s' % key, value)
                          for (key, value) in context.to_dict().iteritems()])            
        context_dict['conf'] =  None # RpcContext object looks for this during init
        store = {
            'context': context_dict,                # context dictionary
            'source_platform': 'openstack',
            'workload_id': workload_id,
        }

        for meta in workload.metadata:
            store[meta.key] = meta.value
        
        workflow_class = get_workflow_class(context, workload.workload_type_id)
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
        workload = self.db.workload_get(context, workload_id)
        store = {
                'context': context_dict,                # context dictionary
                'workload_id': workload_id,             # workload_id
                'source_platform': workload.source_platform,
        }
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
        workload = self.db.workload_get(context, workload_id)
        store = {
                'context': context_dict,                # context dictionary
                'workload_id': workload_id,             # workload_id
                'source_platform': workload.source_platform
        }
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
            vms = self.db.workload_vms_get(context, workload_id)

            # Create swift container for the workload
            json_wl = jsonutils.dumps(workload)
            json_wl_vms = jsonutils.dumps(vms)

            # update metadata hostnames
            metadatahash = {}
            for meta in workload.metadata:
                metadatahash[meta.key] = meta.value

            instances = self.workload_type_discover_instances(context,
                                         workload.workload_type_id,
                                         metadatahash,
                                         workload_id=workload_id)

            hostnames = ""
            for inst in instances['instances']:
                hostnames += inst['hostname']
                hostnames += ";"

            self.db.workload_update(context, 
                                    workload_id, 
                                    {
                                     'host': self.host,
                                     'status': 'available',
                                     'availability_zone': self.az,
                                     'metadata': {'hostnames': hostnames}, 
                                    })
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.workload_update(context, workload_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})
        
    @autolog.log_method(logger=Logger)
    @synchronized(workloadlock)
    def workload_snapshot(self, context, snapshot_id):
        """
        Take a snapshot of the workload
        """
        try:
            snapshot = self.db.snapshot_update( context, 
                                                snapshot_id,
                                                {'host': self.host,
                                                  'progress_percent': 0, 
                                                  'progress_msg': 'Snapshot of workload is starting',
                                                  'status': 'starting'})
            workload = self.db.workload_get(context, snapshot.workload_id)

            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'connection': FLAGS.sql_connection,     # taskflow persistence connection
                'context': context_dict,                # context dictionary
                'snapshot': dict(snapshot.iteritems()), # snapshot dictionary
                'workload_id': snapshot.workload_id,    # workload_id                
                'source_platform': workload.source_platform,
            }
            for kvpair in workload.metadata:
                store[kvpair['key']] = kvpair['value']

            workflow_class = get_workflow_class(context, workload.workload_type_id)
            workflow = workflow_class(workload.display_name, store)
            instances = workflow.discover()


            workflow.initflow()
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 0, 
                                     'progress_msg': 'Snapshot of workload is starting',
                                     'status': 'executing'
                                    })            
            workflow.execute()
            self.db.snapshot_type_update(context, snapshot_id)               
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': 'Snapshot of workload is complete',
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'available'
                                    })             

            # update metadata hostnames
            hostnames = ""
            for inst in instances['instances']:
                hostnames += inst['hostname']
                hostnames += ";"

            self.db.workload_update(context, 
                                    snapshot.workload_id, 
                                    {'metadata': {'hostnames': hostnames}, 
                                    })             
             
            # Upload snapshot metadata to the vault
            vmtasks.UploadSnapshotDBEntry(context, snapshot_id)

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
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'error'
                                    })
        
        snapshot = self.db.snapshot_get(context, snapshot_id)
        self.db.workload_update(context,snapshot.workload_id,{'status': 'available'})
        
            
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
    @synchronized(workloadlock)
    def snapshot_restore(self, context, restore_id):
        """
        Restore VMs and all its LUNs from a snapshot
        """
        restore_type = 'restore'
        try:
            restore = self.db.restore_get(context, restore_id)
            snapshot = self.db.snapshot_get(context, restore.snapshot_id)
            workload = self.db.workload_get(context, snapshot.workload_id)
            
            target_platform = 'vmware'
            if hasattr(restore, 'pickle'):
                options = pickle.loads(restore['pickle'].encode('ascii','ignore'))
                if options and 'type' in options:
                    target_platform = options['type'] 
            
            restore_type = restore.restore_type
            
            
            if restore_type == 'test':
                self.db.restore_update( context, 
                            restore_id, 
                            {'host': self.host,
                             'progress_percent': 0, 
                             'progress_msg': 'Create testbubble from snapshot is starting',
                             'status': 'starting'
                            })  
            else:
                self.db.restore_update( context, 
                            restore_id, 
                            {'host': self.host,
                             'progress_percent': 0, 
                             'progress_msg': 'Restore from snapshot is starting',
                             'status': 'starting'
                            })
            
            self.db.restore_update(context, restore.id, {'status': 'executing'})
          
            restore_size = vmtasks_openstack.get_restore_data_size( context, self.db, dict(restore.iteritems()))
            if restore_type == 'test':                     
                self.db.restore_update( context, restore_id, {'size': restore_size})
            else:
                if target_platform == 'openstack':
                    restore_size = vmtasks_openstack.get_restore_data_size( context, self.db, dict(restore.iteritems()))
                    self.db.restore_update( context, restore_id, {'size': (restore_size * 2)})
                else:
                    restore_size = vmtasks_vcloud.get_restore_data_size( context, self.db, dict(restore.iteritems()))
                    self.db.restore_update( context, restore_id, {'size': (restore_size)})
                    
                
            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'connection': FLAGS.sql_connection,     # taskflow persistence connection
                'context': context_dict,                # context dictionary
                'restore': dict(restore.iteritems()),   # restore dictionary
            }
                
            workflow_class = get_workflow_class(context, workload.workload_type_id, True)
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
                             'finished_at' : timeutils.utcnow(),
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
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'error'
                                    })             
            return;                  
    @autolog.log_method(logger=Logger)
    def snapshot_delete(self, context, snapshot_id):
        """
        Delete an existing snapshot
        """
        snapshot = self.db.snapshot_get(context, snapshot_id)
        self.driver.snapshot_delete(context, self.db, snapshot)


    @autolog.log_method(logger=Logger)        
    def restore_delete(self, context, restore_id):
        """
        Delete an existing restore 
        """
        self.db.restore_delete(context, restore_id)        
 
