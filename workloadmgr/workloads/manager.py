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
import json
from threading import Lock
import shutil


from oslo.config import cfg

from workloadmgr import context
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
import  workloadmgr.workflows
from workloadmgr.workflows import vmtasks_openstack
from workloadmgr.workflows import vmtasks_vcloud
from workloadmgr.workflows import vmtasks
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import exception as wlm_exceptions
from workloadmgr.openstack.common import timeutils
from taskflow.exceptions import WrappedFailure

from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

workloads_manager_opts = [
]

scheduler_config = {'standalone': 'True'}

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)
       
@autolog.log_method(logger=Logger)
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
    
    @autolog.log_method(logger=Logger)
    def __init__(self, service_name=None, *args, **kwargs):
        self.az = FLAGS.storage_availability_zone
        self.scheduler = Scheduler(scheduler_config)
        self.scheduler.start()
        self.driver = driver.load_compute_driver(None, None)
        super(WorkloadMgrManager, self).__init__(service_name='workloadscheduler',*args, **kwargs)
    
    @autolog.log_method(logger=Logger)    
    def init_host(self):
        """
        Do any initialization that needs to be run if this is a standalone service.
        """

        ctxt = context.get_admin_context()

        LOG.info(_("Cleaning up incomplete operations"))
        
        try:
            self.db.snapshot_mark_incomplete_as_error(ctxt, self.host)
            self.db.restore_mark_incomplete_as_error(ctxt, self.host)
        except Exception as ex:
            LOG.exception(ex)
            
        vault_service = vault.get_vault_service(None)
        vault_service.mount()
    
    @autolog.log_method(logger=Logger)    
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
    
    @autolog.log_method(logger=Logger)    
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
            store[key] = str(metadata[key])
        
        workflow_class = get_workflow_class(context, workload_type_id)
        workflow = workflow_class("discover_instances", store)
        instances = workflow.discover()
        return instances   

    @autolog.log_method(logger=Logger)        
    def workload_type_topology(self, context, workload_type_id,
                               metadata, workload_id=None):
        """
        Topology of a workload_type
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
            store[key] = str(metadata[key])
        
        workflow_class = get_workflow_class(context, workload_type_id)
        workflow = workflow_class("workload_topology", store)
        topology = workflow.topology()
        return topology   

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
            if meta.key == 'preferredgroup':
                continue            
            store[meta.key] = meta.value
            
        
        workflow_class = get_workflow_class(context, workload.workload_type_id)
        workflow = workflow_class("discover_instances", store)
        instances = workflow.discover()


        for vm in self.db.workload_vms_get(context, workload.id):
            self.db.workload_vms_delete(context, vm.vm_id, workload.id) 
        
        if instances and 'instances' in instances:
            for instance in instances['instances']:
                values = {'workload_id': workload.id,
                          'vm_id': instance['vm_id'],
                          'metadata': instance['vm_metadata'],
                          'vm_name': instance['vm_name']}
                vm = self.db.workload_vms_create(context, values)                                       
        
        return instances

    @autolog.log_method(logger=Logger)
    def workload_get_topology(self, context, workload_id):
        """
        Return workload topology
        """
        try:
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
        except Exception as err:
            with excutils.save_and_reraise_exception():
                msg = _("Error getting workload topology %(workload_id)s with failure: %(exception)s") %{
                        'workload_id': workload_id, 'exception': err,}
                LOG.error(msg)
                LOG.exception(err)
                pass
    
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
            self.db.workload_update(context, 
                                    workload_id, 
                                    {
                                     'host': self.host,
                                     'status': 'available',
                                     'availability_zone': self.az,
                                    })
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.workload_update(context, workload_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})
        
    @synchronized(workloadlock)
    @autolog.log_method(logger=Logger)
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
            snapshot_metadata = {}
            for kvpair in workload.metadata:
                store[kvpair['key']] = str(kvpair['value'])
                snapshot_metadata[kvpair['key']] = str(kvpair['value']) 

            store['topology'] = json.dumps("")
            workflow_class = get_workflow_class(context, workload.workload_type_id)
            workflow = workflow_class(workload.display_name, store)

            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 0, 
                                     'progress_msg': 'Initializing Snapshot Workflow',
                                     'status': 'executing'
                                    })       
            workflow.initflow()
            workflow.execute()
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': 'Snapshot of workload is complete',
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'available',
                                     'metadata': snapshot_metadata})
            self.db.snapshot_type_time_size_update(context, snapshot_id)               

             
            # Update vms of the workload
            if  'instances' in workflow._store and workflow._store['instances']:
                for vm in self.db.workload_vms_get(context, workload.id):
                    self.db.workload_vms_delete(context, vm.vm_id, workload.id) 

                for instance in workflow._store['instances']:
                    values = {'workload_id': workload.id,
                              'vm_id': instance['vm_id'],
                              'metadata': instance['vm_metadata'],
                              'vm_name': instance['vm_name']}
                    vm = self.db.workload_vms_create(context, values)                                       
            
            hostnames = []
            for inst in workflow._store['instances']:
                hostnames.append(inst['hostname'])

                if not 'root_partition_type' in inst:
                    inst['root_partition_type'] = "Linux"
                self.db.snapshot_vm_update(context, inst['vm_id'], snapshot.id,
                                           {'metadata':{'root_partition_type':inst['root_partition_type']}})

            workload_metadata = {'hostnames': json.dumps(hostnames),
                                 'topology': json.dumps(workflow._store['topology'])}
            self.db.workload_update(context, 
                                    snapshot.workload_id, 
                                    {'metadata': workload_metadata})
            snapshot_metadata['topology'] = json.dumps(workflow._store['topology'])
            self.db.snapshot_update(context,
                                    snapshot_id, 
                                    {'metadata': snapshot_metadata})

            # Upload snapshot metadata to the vault
            vmtasks.UploadSnapshotDBEntry(context, snapshot_id)

        except WrappedFailure as ex:
            LOG.exception(ex)
            msg = _("Failed creating workload snapshot with following error(s):")
            if hasattr(ex, '_causes'):
                for cause in ex._causes:
                    if cause._exception_str not in msg:
                        msg = msg + ' ' + cause._exception_str
            LOG.error(msg)        
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'error'
                                    })  
            try:
                self.db.snapshot_type_time_size_update(context, snapshot_id)
            except Exception as ex:
                LOG.exception(ex)
                      
        except Exception as ex:
            LOG.exception(ex)
            msg = _("Failed creating workload snapshot: %(exception)s") %{'exception': ex}
            LOG.error(msg)
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'error'
                                    })
            try:
                self.db.snapshot_type_time_size_update(context, snapshot_id)
            except Exception as ex:
                LOG.exception(ex)            
        
        snapshot = self.db.snapshot_get(context, snapshot_id)
        self.db.workload_update(context,snapshot.workload_id,{'status': 'available'})
        
            
    @autolog.log_method(logger=Logger)
    def workload_delete(self, context, workload_id):
        """
        Delete an existing workload
        """
        workload = self.db.workload_get(context, workload_id)
        snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload.id)
        if len(snapshots) > 0:
            msg = _('This workload contains snapshots. Please delete all snapshots and try again..')
            raise wlm_exceptions.InvalidState(reason=msg)
            
        self.db.workload_delete(context, workload.id)
        try:
            LOG.info(_('Deleting the data of workload %s %s %s') % (workload.display_name, 
                                                                    workload.id,
                                                                    workload.created_at.strftime("%d-%m-%Y %H:%M:%S")))                 
            shutil.rmtree(vault.get_vault_service(context).get_workload_path({'workload_id': workload.id}))
        except Exception as ex:
            LOG.exception(ex)          
        
    @autolog.log_method(logger=Logger)
    def _oneclick_restore_options(self, context, restore, options):
        if options['type'] != "vmware":
            msg= _("Platforms other than VMware are not supported for oneclick restore")
            LOG.error(msg)
            raise wlm_exceptions.InvalidState(reason=msg)

        snapshot_id = restore.snapshot_id
        snapshotvms = self.db.snapshot_vms_get(context, restore.snapshot_id)
        options['vmware']['instances'] = [] 
        for inst in snapshotvms:
            optionsinst = {
                           'name': inst.vm_name, 'id':inst.vm_id,
                           'power': {'state': 'on', 'sequence': 1},
                          }
            snapshot_vm_resources = self.db.snapshot_vm_resources_get(context, inst.vm_id, snapshot_id)
            for snapshot_vm_resource in snapshot_vm_resources:
                """ flavor """
                if snapshot_vm_resource.resource_type == 'flavor':
                    vm_flavor = snapshot_vm_resource
                    optionsinst['flavor'] = {'vcpus' : self.db.get_metadata_value(vm_flavor.metadata, 'vcpus'),
                                             'ram' : self.db.get_metadata_value(vm_flavor.metadata, 'ram'),
                                             'disk': self.db.get_metadata_value(vm_flavor.metadata, 'disk'),
                                             'ephemeral': self.db.get_metadata_value(vm_flavor.metadata, 'ephemeral')
                                            }

            instmeta = inst.metadata
            for meta in inst.metadata:
                if not meta.key  in ['cluster', 'parent', 'networks',
                                     'resourcepool', 'vdisks', 'datastores',
                                     'vmxpath']:
                    continue

                metavalue = json.loads(meta.value)
                if meta.key == 'cluster':
                    optionsinst['computeresource'] = {'moid': metavalue[0]['value'], 'name': metavalue[0]['name']}
                elif meta.key == 'parent':
                    optionsinst['vmfolder'] = {'moid': metavalue['value'], 'name': metavalue['name']}
                elif meta.key == 'networks':
                    optionsinst['networks'] = []
                    for net in metavalue:
                        optionsinst['networks'].append({'mac_address': net['macAddress'],
                                                        'network_moid': net['value'],
                                                        'network_name': net['name'],
                                                        'new_network_moid': net['value'],
                                                        'new_network_name': net['name']})
                elif meta.key == 'resourcepool':
                    optionsinst['resourcepool'] = {'moid': metavalue['value'], 'name': metavalue['name']}
                elif meta.key == 'vdisks':
                    optionsinst['vdisks'] = metavalue
                elif meta.key == 'vmxpath':
                    optionsinst['vmxpath'] = metavalue
                elif 'datastores':
                    optionsinst['datastores'] = []
                    for ds in metavalue:
                        optionsinst['datastores'].append({'moid': ds['value'],
                                                          'name': ds['name']})
            options['vmware']['instances'].append(optionsinst)

        return options

    @synchronized(workloadlock)
    @autolog.log_method(logger=Logger)
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
                restore = self.db.restore_update(context,
                                                 restore_id,
                                                 {'host': self.host,
                                                  'target_platform': target_platform,
                                                  'progress_percent': 0,
                                                  'progress_msg': 'Create testbubble from snapshot is starting',
                                                  'status': 'starting'
                                                 })
            else:
                restore = self.db.restore_update(context,
                                                 restore_id,
                                                 {'host': self.host,
                                                  'target_platform': target_platform,
                                                  'progress_percent': 0,
                                                  'progress_msg': 'Restore from snapshot is starting',
                                                  'status': 'starting'
                                                 })

            values = {'status': 'executing'}
            if 'oneclickrestore' in options and options['oneclickrestore']:
                # Fill the restore options from the snapshot instances metadata
                options = self._oneclick_restore_options(context, restore, options)
                values['pickle'] = pickle.dumps(options, 0)

            restore = self.db.restore_update(context, restore.id, values)

            restore_size = vmtasks_openstack.get_restore_data_size( context, self.db, dict(restore.iteritems()))
            if restore_type == 'test':
                self.db.restore_update( context, restore_id, {'size': restore_size})
            else:
                if target_platform == 'openstack':
                    restore_size = vmtasks_openstack.get_restore_data_size( context, self.db, dict(restore.iteritems()))
                    restore = self.db.restore_update( context, restore_id, {'size': (restore_size * 2)})
                else:
                    restore_size = vmtasks_vcloud.get_restore_data_size( context, self.db, dict(restore.iteritems()))
                    restore = self.db.restore_update( context, restore_id, {'size': (restore_size)})

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
                             'time_taken' : int((timeutils.utcnow() - restore.created_at).total_seconds()),
                             'status': 'available'
                            })
        except WrappedFailure as ex:
            LOG.exception(ex)
            msg = _("Failed restoring snapshot with following error(s):")
            if hasattr(ex, '_causes'):
                for cause in ex._causes:
                    if cause._exception_str not in msg:
                        msg = msg + ' ' + cause._exception_str
            LOG.error(msg)        
            self.db.restore_update( context,
                                    restore_id,
                                    {'progress_percent': 100,
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'error'
                                    })       
        except Exception as ex:
            LOG.exception(ex)
            if restore_type == 'test':
                msg = _("Failed creating test bubble: %(exception)s") %{'exception': ex}
            else:
                msg = _("Failed restoring snapshot: %(exception)s") %{'exception': ex}
            LOG.error(msg)
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
        def _remove_data(snapshot):
            self.db.snapshot_update(context, snapshot.id, {'data_deleted':True})
            try:
                LOG.info(_('Deleting the data of snapshot %s %s %s') % (snapshot.display_name, 
                                                                            snapshot.id,
                                                                            snapshot.created_at.strftime("%d-%m-%Y %H:%M:%S")))                            
                
                shutil.rmtree(vault.get_vault_service(context).get_snapshot_path({'workload_id': snapshot.workload_id,
                                                                               'snapshot_id': snapshot.id}))
            except Exception as ex:
                LOG.exception(ex)            
        
        snapshot = self.db.snapshot_get(context, snapshot_id)    
        self.db.snapshot_delete(context, snapshot.id)
        if snapshot.status == 'error':
            return _remove_data(snapshot)
        try:
            snapshot_vm_resources = self.db.snapshot_resources_get(context, snapshot.id)
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type != 'disk':
                    continue
                if snapshot_vm_resource.status != 'deleted':
                    return
        except wlm_exceptions.SnapshotVMResourcesNotFound as ex:
            LOG.exception(ex)
            return 
                   
        return _remove_data(snapshot)

    @autolog.log_method(logger=Logger)
    def restore_delete(self, context, restore_id):
        """
        Delete an existing restore
        """
        self.db.restore_delete(context, restore_id)
