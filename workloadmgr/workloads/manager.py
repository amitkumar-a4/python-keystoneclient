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

from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import *
from datetime import datetime, timedelta
import time
import uuid
import cPickle as pickle
import json
from threading import Lock
import subprocess
from subprocess import check_output
import shutil

import smtplib
import socket
import os

# Import the email modules
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from keystoneclient.v2_0 import client as keystone_v2

from oslo.config import cfg

from taskflow.patterns import linear_flow as lf
from taskflow import engines

from workloadmgr import context
from workloadmgr import flags
from workloadmgr import manager
from workloadmgr import mountutils
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
from workloadmgr import utils

import  workloadmgr.workflows
from workloadmgr.workflows import vmtasks_openstack
from workloadmgr.workflows import vmtasks_vcloud
from workloadmgr.workflows import vmtasks
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import exception as wlm_exceptions
from workloadmgr.openstack.common import timeutils
from taskflow.exceptions import WrappedFailure
from workloadmgr.workloads import workload_utils
from workloadmgr.openstack.common import fileutils

from workloadmgr import autolog
from workloadmgr import settings

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

workloads_manager_opts = [
    cfg.StrOpt('mountdir',
               default='/var/triliovault/tvault-mounts',
               help='Root directory where all snapshots are mounted.'),
    cfg.BoolOpt('pause_vm_before_snapshot',
                default=False,
                help='pause VM before snapshot operation'
                     ' libvirt calls'),
]

scheduler_config = {'standalone': 'True'}

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)

CONF = cfg.CONF
       
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
  

class objectview(object):
    def __init__(self, d):
        self.__dict__ = d

    
class WorkloadMgrManager(manager.SchedulerDependentManager):
    """Manages WorkloadMgr """

    RPC_API_VERSION = '1.0'

    
    @autolog.log_method(logger=Logger)
    def __init__(self, service_name=None, *args, **kwargs):
        self.az = FLAGS.storage_availability_zone
        self.scheduler = Scheduler(scheduler_config)
        self.scheduler.start()       
        self.pool = ThreadPoolExecutor(max_workers=5)
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
            
        vault.mount_backup_media()
    
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

        compute_service = nova.API(production=True)
        for vm in self.db.workload_vms_get(context, workload.id):
            self.db.workload_vms_delete(context, vm.vm_id, workload.id) 
            compute_service.delete_meta(context, vm.vm_id,
                                   ["workload_id", "workload_name"])
        
        if instances and 'instances' in instances:
            for instance in instances['instances']:
                values = {'workload_id': workload.id,
                          'vm_id': instance['vm_id'],
                          'metadata': instance['vm_metadata'],
                          'vm_name': instance['vm_name']}
                vm = self.db.workload_vms_create(context, values)                                       
                compute_service.set_meta_item(context, vm.vm_id,
                                    "workload_id", workload.id)
                compute_service.set_meta_item(context, vm.vm_id,
                                    "workload_name", workload.display_name)
        
        if instances and 'topology' in instances:
            workload_metadata = {'topology': json.dumps(instances['topology'])}
            self.db.workload_update(context, 
                                    workload_id,
                                    {'metadata': workload_metadata})
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
        Return workload workflow
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

            compute_service = nova.API(production=True)
            for vm in vms:
                compute_service.set_meta_item(context, vm.vm_id,
                                    "workload_id", workload_id)
                compute_service.set_meta_item(context, vm.vm_id,
                                    "workload_name", workload['display_name'])
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.workload_update(context, workload_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})

    #@synchronized(workloadlock)
    @autolog.log_method(logger=Logger)
    def workload_snapshot(self, context, snapshot_id):
        """
        Take a snapshot of the workload
        """
        
        try:
            try:
                import gc
                gc.collect()
            except Exception as ex:
                LOG.exception(ex)  
                
            snapshot = self.db.snapshot_update( context, 
                                                snapshot_id,
                                                {'host': self.host,
                                                  'progress_percent': 0, 
                                                  'progress_msg': 'Snapshot of workload is starting',
                                                  'status': 'starting'})
            workload = self.db.workload_get(context, snapshot.workload_id)
            pause_at_snapshot = CONF.pause_vm_before_snapshot
            for metadata in workload.metadata:
                for key in metadata:
                    if key == 'pause_at_snapshot':
                       pause_at_snapshot = bool(int(metadata[key]))

            context_dict = dict([('%s' % key, value)
                              for (key, value) in context.to_dict().iteritems()])            
            context_dict['conf'] =  None # RpcContext object looks for this during init
            store = {
                'connection': FLAGS.sql_connection,     # taskflow persistence connection
                'context': context_dict,                # context dictionary
                'snapshot': dict(snapshot.iteritems()), # snapshot dictionary
                'workload_id': snapshot.workload_id,    # workload_id                
                'source_platform': workload.source_platform,
                'pause_at_snapshot': pause_at_snapshot,
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

            self.db.snapshot_type_time_size_update(context, snapshot_id)               
            # Update vms of the workload
            if  'instances' in workflow._store and workflow._store['instances']:
                compute_service = nova.API(production=True)                
                for vm in self.db.workload_vms_get(context, workload.id):
                    self.db.workload_vms_delete(context, vm.vm_id, workload.id) 
                    compute_service.delete_meta(context, vm.vm_id,
                                            ["workload_id", 'workload_name'])


                for instance in workflow._store['instances']:
                    values = {'workload_id': workload.id,
                              'status': 'available',
                              'vm_id': instance['vm_id'],
                              'metadata': instance['vm_metadata'],
                              'vm_name': instance['vm_name']}
                    vm = self.db.workload_vms_create(context, values)                                       
                    compute_service.set_meta_item(context, vm.vm_id,
                                                  "workload_id", workload.id)
                    compute_service.set_meta_item(context, vm.vm_id,
                                                  "workload_name", workload.display_name)
            
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
            workload_utils.upload_snapshot_db_entry(context, snapshot_id, snapshot_status = 'available')
            
            # upload the data to object store... this function will check if the object store is configured
            vault.upload_snapshot_metatdata_to_object_store(context, {'workload_id': workload.id, 'workload_name': workload.display_name, 'snapshot_id': snapshot.id})

            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': 'Snapshot of workload is complete',
                                     'finished_at' : timeutils.utcnow(),
                                     'status': 'available',
                                     'metadata': snapshot_metadata})
            
        except WrappedFailure as ex:
            LOG.exception(ex)

            flag = self.db.snapshot_get_metadata_cancel_flag(context, snapshot_id, 1)
            if flag == '1':
                msg =  _("%(exception)s") %{'exception': ex}
                status = 'cancelled'
                for vm in self.db.workload_vms_get(context, workload.id):
                    self.db.snapshot_vm_update(context, vm.vm_id, snapshot_id, {'status': status,})
            else:
                msg = _("Failed creating workload snapshot with following error(s):")
                if hasattr(ex, '_causes'):
                    for cause in ex._causes:
                        if cause._exception_str not in msg:
                            msg = msg + ' ' + cause._exception_str
                LOG.error(msg)  
                status = 'error'
            
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'finished_at' : timeutils.utcnow(),
                                     'status': status
                                    })  
            try:
                self.db.snapshot_type_time_size_update(context, snapshot_id)
            except Exception as ex:
                LOG.exception(ex)
                
                                      
        except Exception as ex:
            LOG.exception(ex)

            flag = self.db.snapshot_get_metadata_cancel_flag(context, snapshot_id, 1)            
            if flag == '1':
                msg =  _("%(exception)s") %{'exception': ex}
                status = 'cancelled'
                for vm in self.db.workload_vms_get(context, workload.id):
                    self.db.snapshot_vm_update(context, vm.vm_id, snapshot_id, {'status': status,})
            else:       
                msg = _("Failed creating workload snapshot: %(exception)s") %{'exception': ex}
                LOG.error(msg)
                status = 'error'
            
            self.db.snapshot_update(context, 
                                    snapshot_id, 
                                    {'progress_percent': 100, 
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'finished_at' : timeutils.utcnow(),
                                     'status': status
                                    })
            try:
                self.db.snapshot_type_time_size_update(context, snapshot_id)
            except Exception as ex:
                LOG.exception(ex)
                
        finally:
            try:
                vault.purge_snapshot_from_staging_area(context, {'workload_id' : workload.id,
                                                                 'snapshot_id' : snapshot.id})
            except Exception as ex:
                LOG.exception(ex) 
                                           
            try:
                vault.purge_staging_area(context)
            except Exception as ex:
                LOG.exception(ex) 
                
            try:
                import gc
                gc.collect() 
            except Exception as ex:
                LOG.exception(ex)
            
            try:                
                snapshot = self.db.snapshot_get(context, snapshot_id)
                if settings.get_settings(context).get('smtp_email_enable') == 'yes' or settings.get_settings(context).get('smtp_email_enable') == '1':
                    self.send_email(context,snapshot,'snapshot')
            except Exception as ex:
                LOG.exception(ex)
                        
            #unlock the workload
            try:                
                snapshot = self.db.snapshot_get(context, snapshot_id)            
                self.db.workload_update(context,snapshot.workload_id,{'status': 'available'})
            except Exception as ex:
                LOG.exception(ex)
                            
    @autolog.log_method(logger=Logger)
    def workload_reset(self, context, workload_id):
        """
        Reset an existing workload
        """
        try:
            workload = self.db.workload_get(context, workload_id)
            vms = self.db.workload_vms_get(context, workload.id)
 
            # get the recent snapshot
            if workload.source_platform == 'openstack': 
                virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
                for vm in vms:
                    virtdriver.reset_vm(context, workload_id, vm.vm_id)
        except Exception as ex:
            LOG.exception(ex)
            msg = _("Failed to  reset: %(exception)s") %{'exception': ex}
            LOG.error(msg)
        finally:
            self.db.workload_update(context, workload_id, {'status': 'available'})
        return


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
            
        LOG.info(_('Deleting the data of workload %s %s %s') % (workload.display_name, 
                                                                workload.id,
                                                                workload.created_at.strftime("%d-%m-%Y %H:%M:%S")))                 
        vault.workload_delete(context, {'workload_id': workload.id,
                                        'workload_name': workload.display_name,})
        self.workload_reset(context, workload_id)

        compute_service = nova.API(production=True)                
        workload_vms = self.db.workload_vms_get(context, workload.id)
        for vm in workload_vms:
            compute_service.delete_meta(context, vm.vm_id,
                                   ["workload_id", 'workload_name'])
            self.db.workload_vms_delete(context, vm.vm_id, workload.id)
        self.db.workload_delete(context, workload.id)


    @autolog.log_method(logger=Logger)
    def _oneclick_restore_options(self, context, restore, options):
        if options['type'] == "openstack":
            return options

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
                if meta.key == 'cluster' and metavalue:
                    optionsinst['computeresource'] = {'moid': metavalue[0]['value'], 'name': metavalue[0]['name']}
                elif meta.key == 'parent' and metavalue:
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
                elif meta.key == 'datastores':
                    optionsinst['datastores'] = []
                    for ds in metavalue:
                        optionsinst['datastores'].append({'moid': ds['value'],
                                                          'name': ds['name']})
            options['vmware']['instances'].append(optionsinst)

        return options

    #@synchronized(workloadlock)
    @autolog.log_method(logger=Logger)
    def snapshot_restore(self, context, restore_id):
        """
        Restore VMs and all its LUNs from a snapshot
        """
        restore_type = 'restore'
        try:
            try:
                import gc
                gc.collect() 
            except Exception as ex:
                LOG.exception(ex)
                            
            restore = self.db.restore_get(context, restore_id)
            snapshot = self.db.snapshot_get(context, restore.snapshot_id)
            workload = self.db.workload_get(context, snapshot.workload_id)
            
            vault.purge_workload_from_staging_area(context, {'workload_id': workload.id})            

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
            restore_user_selected_value = 'Selective Restore'
            if options and 'oneclickrestore' in options and options['oneclickrestore']:
                restore_user_selected_value = 'Oneclick Restore'
                # Override traget platfrom for clinets not specified on oneclick
                if workload.source_platform != target_platform:
                   target_platform = workload.source_platform
                # Fill the restore options from the snapshot instances metadata
                options = self._oneclick_restore_options(context, restore, options)
                values['pickle'] = pickle.dumps(options, 0)

            restore = self.db.restore_update(context, restore.id, values)
            if options and 'oneclickrestore' in options and \
               options['oneclickrestore'] and target_platform == 'openstack':
                compute_service = nova.API(production=True)                
                for vm in self.db.snapshot_vms_get(context, restore.snapshot_id):
                    instance_options = utils.get_instance_restore_options(options, vm.vm_id, target_platform)
                    if instance_options and instance_options.get('include', True) == False:
                        continue
                    else:
                        instance = compute_service.get_server_by_id(context, vm.vm_id, admin=True)
                        if instance:
                            msg = _('Original instance ' +  vm.vm_name + ' is still present. '
                                    'Please delete this instance and try again.')
                            raise wlm_exceptions.InvalidState(reason=msg)

            restore_size = vmtasks_openstack.get_restore_data_size( context, self.db, dict(restore.iteritems()))
            if restore_type == 'test':
                self.db.restore_update( context, restore_id, {'size': restore_size})
            else:
                if target_platform == 'openstack':
                    restore_size = vmtasks_openstack.get_restore_data_size( context, self.db, dict(restore.iteritems()))
                    restore = self.db.restore_update( context, restore_id, {'size': (restore_size)})
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
                'target_platform': target_platform,                
            }
            workflow_class = get_workflow_class(context, workload.workload_type_id, True)
            workflow = workflow_class(restore.display_name, store)
            workflow.initflow()
            workflow.execute()
            
            compute_service = nova.API(production=True)
            restore_data_transfer_time = 0
            restore_object_store_transfer_time = 0            
            workload_vms = self.db.workload_vms_get(context, workload.id)
            if target_platform == 'openstack':
               for restored_vm in self.db.restored_vms_get(context, restore_id):
                   instance = compute_service.get_server_by_id(context, restored_vm.vm_id, admin=True)
                   if instance == None:
                      pass 
                   else:
                        #production = bool(self.db.get_metadata_value(restored_vm.metadata, 'production', True))
                        instance_id = self.db.get_metadata_value(restored_vm.metadata, 'instance_id', None)
                        production = compute_service.get_server_by_id(context, instance_id, admin=False)
                        if production == None:
                           production = True
                        else:
                             production = False

                        if production == True:
                           workload_metadata = {}
                           if instance_id is not None:
                              restored_ids, snap_ins = self.get_metadata_value_by_chain(workload.metadata, instance_id, None)
                              workload_metadata[instance_id] = restored_vm.vm_id
                              if restored_ids == None:
                                 self.db.workload_vms_delete(context, instance_id, workload.id)
                                 compute_service.delete_meta(context, instance_id,
                                                         ["workload_id", "workload_name"])
                              else:
                                   for ins in snap_ins:
                                       workload_metadata[ins] = restored_vm.vm_id
 
                                   for restored_id in restored_ids:
                                       self.db.workload_vms_delete(context, restored_id, workload.id)
                                       compute_service.delete_meta(context, restore_id,
                                                            ["workload_id", ["workload_name"]])

                              self.db.workload_update(context,
                                   workload.id,
                                   {
                                     'metadata' : workload_metadata,
                                   })

                           self.db.restored_vm_update( context, restored_vm.vm_id,
                                               restore_id, {'metadata': instance.metadata})
                           values = {'workload_id': workload.id,
                                     'vm_id': restored_vm.vm_id,
                                     'metadata': instance.metadata,
                                     'vm_name': instance.name,
                                     'status': 'available'}
                           vm = self.db.workload_vms_create(context, values)
                           compute_service.set_meta_item(context, vm.vm_id,
                                     "workload_id", workload.id)
                           compute_service.set_meta_item(context, vm.vm_id,
                                     "workload_name", workload.display_name)

                   restore_data_transfer_time += int(self.db.get_metadata_value(restored_vm.metadata, 'data_transfer_time', '0'))
                   restore_object_store_transfer_time += int(self.db.get_metadata_value(restored_vm.metadata, 'object_store_transfer_time', '0'))                                        

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
                             'metadata' : {'data_transfer_time' : restore_data_transfer_time,
                                           'object_store_transfer_time' : restore_object_store_transfer_time,
                                           'restore_user_selected_value' : restore_user_selected_value,
                                          },                              
                             'status': 'available'
                            })
        except WrappedFailure as ex:

            flag = self.db.restore_get_metadata_cancel_flag(context, restore_id, 1)
            if flag == '1':
                msg =  _("%(exception)s") %{'exception': ex}
                status = 'cancelled'
            else:
                status = 'error'
                LOG.exception(ex)
                msg = _("Failed restoring snapshot with following error(s):")
                if hasattr(ex, '_causes'):
                    for cause in ex._causes:
                        if cause._exception_str not in msg:
                            msg = msg + ' ' + cause._exception_str
                LOG.error(msg)
            
            time_taken = 0
            if 'restore' in locals() or 'restore' in globals():
                if restore:
                    time_taken = int((timeutils.utcnow() - restore.created_at).total_seconds())
                        
            self.db.restore_update( context,
                                    restore_id,
                                    {'progress_percent': 100,
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'finished_at' : timeutils.utcnow(),
                                     'time_taken' : time_taken,
                                     'metadata' : {'data_transfer_time' : 0,
                                                   'object_store_transfer_time' : 0,
                                                   'restore_user_selected_value' : restore_user_selected_value,
                                                  },                                        
                                     'status': status
                                    })       
        except Exception as ex:
            
            flag = self.db.restore_get_metadata_cancel_flag(context, restore_id, 1)
            if flag == '1':
                msg =  _("%(exception)s") %{'exception': ex}
                status = 'cancelled'
            else:
                status = 'error'
                LOG.exception(ex)
                if restore_type == 'test':
                    msg = _("Failed creating test bubble: %(exception)s") %{'exception': ex}
                else:
                    msg = _("Failed restoring snapshot: %(exception)s") %{'exception': ex}
                LOG.error(msg)
            
            time_taken = 0
            if 'restore' in locals() or 'restore' in globals():
                if restore:
                    time_taken = int((timeutils.utcnow() - restore.created_at).total_seconds())
                                
            self.db.restore_update( context,
                                    restore_id,
                                    {'progress_percent': 100,
                                     'progress_msg': '',
                                     'error_msg': msg,
                                     'finished_at' : timeutils.utcnow(),
                                     'time_taken' : time_taken,
                                     'metadata' : {'data_transfer_time' : 0,
                                                   'object_store_transfer_time' : 0,
                                                   'restore_user_selected_value' : restore_user_selected_value,
                                                  },                                        
                                     'status': status
                                    })
        finally:
            try:
                vault.purge_staging_area(context)
            except Exception as ex:
                LOG.exception(ex)  
            
            try:
                vault.purge_restore_from_staging_area(context, {'restore_id': restore_id})
            except Exception as ex:
                LOG.exception(ex)             
            
            try:
                import gc
                gc.collect() 
            except Exception as ex:
                LOG.exception(ex)
            
            try:
                restore = self.db.restore_get(context, restore_id)
                self.db.snapshot_update(context, restore.snapshot_id, {'status': 'available'})
                self.db.workload_update(context, workload.id,{'status': 'available'})
                if settings.get_settings(context).get('smtp_email_enable') == 'yes' or settings.get_settings(context).get('smtp_email_enable') == '1':
                    self.send_email(context,restore,'restore')       
            except Exception as ex:
                LOG.exception(ex)                     

    @autolog.log_method(logger=Logger)
    def snapshot_delete(self, context, snapshot_id, task_id):
        """
        Delete an existing snapshot
        """
        def execute(context, snapshot_id, task_id):
            workload_utils.snapshot_delete(context, snapshot_id)
                    
            #unlock the workload
            snapshot = self.db.snapshot_get(context, snapshot_id, read_deleted='yes')
            self.db.workload_update(context,snapshot.workload_id,{'status': 'available'})
            self.db.snapshot_update(context, snapshot_id, {'status': 'available'})

            status_messages = {'message': 'Snapshot delete operation completed'}
            self.db.task_update(context,task_id,{'status': 'done','finished_at': timeutils.utcnow(),
                                'status_messages': status_messages})

        self.pool.submit(execute, context, snapshot_id, task_id)
                    
    @autolog.log_method(logger=Logger)
    def snapshot_mount(self, context, snapshot_id, mount_vm_id):
        """
        Mount an existing snapshot
        """
        def _prepare_snapshot_for_mount(cntx, db, snapshot_id):

            pervmdisks = {}
            snapshot_obj = db.snapshot_get(cntx, snapshot_id)
            snapshotvms = self.db.snapshot_vms_get(context, snapshot_id)
            if not FLAGS.vault_storage_type in ("nfs", "local"):

                context_dict = dict([('%s' % key, value)
                                      for (key, value) in cntx.to_dict().iteritems()])            
                context_dict['conf'] =  None # RpcContext object looks for this during init

                #restore, rebase, commit & upload
                LOG.info(_('Processing disks'))
                _preparevmflow = lf.Flow(snapshot_id + "DownloadInstance")
                store = {
                           'connection': FLAGS.sql_connection,
                           'context': context_dict,
                           'snapshot_id': snapshot_id,
                           'mount_id': str(uuid.uuid4()),
                        }
                for instance in snapshotvms:
                    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx,
                                                     instance['vm_id'], snapshot_obj.id)
   

                    for snapshot_vm_resource in snapshot_vm_resources:
                        store[snapshot_vm_resource.id] = snapshot_vm_resource.id
                        store['devname_'+snapshot_vm_resource.id] = snapshot_vm_resource.resource_name

                    childflow = vmtasks.LinearPrepareBackupImages(cntx, instance, snapshot_obj)
                    if childflow:
                        _preparevmflow.add(childflow)

                # execute the workflow
                result = engines.run(_preparevmflow, engine_conf='serial',
                                 backend={'connection': store['connection'] }, store=store)
                snapshot_vm_resources = db.snapshot_vm_resources_get(cntx,
                                                     instance['vm_id'], snapshot_obj.id)
                snapshot_vm_resources = self.db.snapshot_resources_get(context, snapshot_id)
                for snapshot_vm_resource in snapshot_vm_resources:
                    if snapshot_vm_resource.resource_type == 'disk':
                        if not snapshot_vm_resource.vm_id in pervmdisks:
                            pervmdisks[snapshot_vm_resource.vm_id] = []
                        if 'restore_file_path_'+snapshot_vm_resource.id in result:
                            path = result['restore_file_path_'+snapshot_vm_resource.id]
                            pervmdisks[snapshot_vm_resource.vm_id].append(path)
            else:
                snapshot_vm_resources = self.db.snapshot_resources_get(context, snapshot_id)
                for snapshot_vm_resource in snapshot_vm_resources:
                    if snapshot_vm_resource.resource_type == 'disk':
                        if not snapshot_vm_resource.vm_id in pervmdisks:
                            pervmdisks[snapshot_vm_resource.vm_id] = []
                        vm_disk_resource_snap = self.db.vm_disk_resource_snap_get_top(context,snapshot_vm_resource.id)
                        pervmdisks[snapshot_vm_resource.vm_id].append(vm_disk_resource_snap.vault_path)
            return pervmdisks

        try:
            devpaths = {}
            logicalobjects = {}
            snapshot_metadata = {}
            
            head, tail = os.path.split(FLAGS.mountdir + '/')
            fileutils.ensure_tree(head)

            snapshot = self.db.snapshot_get(context, snapshot_id, read_deleted='yes')
            workload = self.db.workload_get(context, snapshot.workload_id, read_deleted='yes')
            pervmdisks = _prepare_snapshot_for_mount(context, self.db, snapshot_id)

            if workload.source_platform == 'openstack': 
                virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
                fminstance = virtdriver.snapshot_mount(context, snapshot, pervmdisks,
                                            mount_vm_id=mount_vm_id)
                urls = []
                for netname, addresses in fminstance.addresses.iteritems():
                    for addr in addresses:
                        if 'addr' in addr:
                            urls.append("http://" + addr['addr'])
 
                self.db.snapshot_update(context, snapshot['id'],
                                        {'status': 'mounted',
                                         'metadata': {
                                              'mount_vm_id': mount_vm_id,
                                              'urls': json.dumps(urls)
                                           }
                                        })
                return {"urls": urls}
            elif workload.source_platform == 'vmware': 
                virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')            


                for vmid, diskfiles in pervmdisks.iteritems():
                    # the goal is to mount as many artifacts as possible from snapshot
                    devpaths[vmid] = virtdriver.snapshot_mount(context, snapshot, diskfiles)

                    try:
                        partitions = {}

                        for diskpath, mountpath in devpaths[vmid].iteritems():
                            partitions[mountpath] = mountutils.read_partition_table(mountpath)

                        logicalobjects[vmid] = mountutils.discover_lvs_and_partitions(devpaths[vmid], partitions)

                        mountutils.mount_logicalobjects(FLAGS.mountdir, snapshot_id, vmid, logicalobjects[vmid])
                    except Exception as ex:
                        if vmid in logicalobjects:
                            for vg in logicalobjects[vmid]['vgs']:
                                mountutils.deactivatevgs(vg['LVM2_VG_NAME'])
                            logicalobjects.pop(vmid)
                        LOG.exception(ex)

                snapshot_metadata['devpaths'] = json.dumps(devpaths)
                snapshot_metadata['logicalobjects'] = json.dumps(logicalobjects)
                snapshot_metadata['fsmanagerpid'] = -1
            
                self.db.snapshot_update(context, snapshot['id'],
                                 {'metadata': snapshot_metadata})

                ## TODO: Spin up php webserver
                try:
                    snapshot_metadata = {}
                    snapshot_metadata['fsmanagerpid'] = \
                          mountutils.start_filemanager_server(FLAGS.mountdir)
                    snapshot_metadata['mounturl'] = "http://" + [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")][:1][0] + ":8888"
                    self.db.snapshot_update(context, snapshot['id'],
                                 {'status': 'mounted', 'metadata': snapshot_metadata})
                except Exception as ex:
                    LOG.error(_("Could not start file manager server"))
                    LOG.exception(ex)
                    raise

                return "http://" + [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")][:1][0] + ":8888"

        except Exception as ex:
            self.snapshot_dismount(context, snapshot['id'])
            LOG.exception(ex)
            raise

    @autolog.log_method(logger=Logger)
    def snapshot_dismount(self, context, snapshot_id):
        """
        Dismount an existing snapshot
        """
        snapshot = self.db.snapshot_get(context, snapshot_id, read_deleted='yes')
        workload = self.db.workload_get(context, snapshot.workload_id, read_deleted='yes')
        if workload.source_platform == 'openstack': 
            mount_vm_id = self.db.get_metadata_value(snapshot.metadata, 'mount_vm_id')

            if mount_vm_id == None:
                msg = _("Could not find recovery manager vm id in the snapshot metadata")
                LOG.error(msg)
                raise wlm_exceptions.Invalid(reason=msg)

            virtdriver = driver.load_compute_driver(None, 'libvirt.LibvirtDriver')
            virtdriver.snapshot_dismount(context, snapshot, None, mount_vm_id)
            self.db.snapshot_update(context, snapshot_id,
                         {'status': 'available', 'metadata': {}})
        elif workload.source_platform == 'vmware': 
            virtdriver = driver.load_compute_driver(None, 'vmwareapi.VMwareVCDriver')        
            devpaths_json = self.db.get_metadata_value(snapshot.metadata, 'devpaths')
            if devpaths_json:
                devpaths = json.loads(devpaths_json)
            else:
                devpaths = {}
       
            fspid = self.db.get_metadata_value(snapshot.metadata, 'fsmanagerpid')
            if (fspid and int(fspid) != -1):
                mountutils.stop_filemanager_server(FLAGS.mountdir, fspid)

            logicalobjects_json = self.db.get_metadata_value(snapshot.metadata, 'logicalobjects')
            if logicalobjects_json:
                logicalobjects = json.loads(logicalobjects_json)
            else:
                logicalobjects = {}

            for vmid, objects in logicalobjects.iteritems():
                try:
                    mountutils.umount_logicalobjects(FLAGS.mountdir, snapshot_id, vmid, objects)
                except Exception as ex:
                    # always cleanup as much as possible
                    LOG.exception(ex)
                    pass

                vgs = objects['vgs']
                for vg in vgs:
                    try:
                        mountutils.deactivatevgs(vg['LVM2_VG_NAME'])
                    except Exception as ex:
                        # always cleanup as much as possible
                        LOG.exception(ex)
                        pass
 
            for vmid, paths in devpaths.iteritems():
                try:
                    virtdriver.snapshot_dismount(context, snapshot, paths)
                except Exception as ex:
                    # always cleanup as much as possible
                    LOG.exception(ex)
                    pass
            if not FLAGS.vault_storage_type in ("nfs", "local"):
                for vmid, paths in devpaths.iteritems():
                    try:
                        os.remove(paths.keys()[0])
                    except:
                        pass
                parent = os.path.dirname(paths.keys()[0])
                parent = os.path.dirname(parent)
                shutil.rmtree(parent)

            snapshot_metadata = {}
            snapshot_metadata['devpaths'] = ""
            snapshot_metadata['logicalobjects'] = ""
            snapshot_metadata['mounturl'] = ""
            snapshot_metadata['fsmanagerpid'] = -1

            self.db.snapshot_update(context, snapshot_id,
                         {'status': 'available', 'metadata': snapshot_metadata})

    @autolog.log_method(logger=Logger)
    def restore_delete(self, context, restore_id):
        """
        Delete an existing restore
        """
        self.db.restore_delete(context, restore_id)		

    @autolog.log_method(logger=Logger)
    def get_metadata_value_by_chain(self, metadata, key, default=None):
        list_of_ids = []
        list_of_snap_ins = []
        while True:
              key1 = self.db.get_metadata_value(metadata, key, default=None)
              if key1 == None:
                 break
              list_of_snap_ins.append(key)
              list_of_ids.append(key1)
              key = key1

        for reverse_id in list_of_ids:
            ins_id = self.get_metadata_value(metadata, reverse_id, False)
            if ins_id is not None:
               if ins_id not in list_of_snap_ins:
                  list_of_snap_ins.append(ins_id)

            ins_reverse_id = self.db.get_metadata_value(metadata, reverse_id)
            if ins_reverse_id is None:
               list_of_snap_ins.append(reverse_id)

        if len(list_of_ids) == 0:
           return default, list_of_snap_ins
        return list_of_ids, list_of_snap_ins

    @autolog.log_method(logger=Logger)
    def get_metadata_value(self, metadata, value, default=None):
        for kvpair in metadata:
            if kvpair['value'] == value:
               return kvpair['key']
        return default

    @autolog.log_method(logger=Logger)
    def send_email(self,context,object,type):
        """
        Sends success email to administrator if snapshot/restore done
        else error email
        """  
        try:
            if type == 'snapshot':
                workload = self.db.workload_get(context, object.workload_id)
                workload_type = self.db.workload_type_get(context, workload.workload_type_id)
                snapshotvms = self.db.snapshot_vms_get(context, object.id)
            elif type == 'restore':
                snapshot = self.db.snapshot_get(context, object.snapshot_id)
                workload = self.db.workload_get(context, snapshot.workload_id)
                workload_type = self.db.workload_type_get(context, workload.workload_type_id)
                snapshotvms = self.db.snapshot_vms_get(context, object.snapshot_id)             

            try:
                keystone = keystone_v2.Client(token=context.auth_token, endpoint=CONF.keystone_endpoint_url)
                user = keystone.users.get(context.user_id)
                if user.email is None or user.email == '':
                    user.email = settings.get_settings(context).get('smtp_default_recipient')
            except:
                o = {'name':'admin','email':settings.get_settings(context).get('smtp_default_recipient')}
                user = objectview(o)
                pass
            with open('/opt/stack/workloadmgr/workloadmgr/templates/vms.html', 'r') as content_file:
                vms_html = content_file.read()
            
            if object.display_description is None:
                object.display_description = str()

            for inst in snapshotvms:
                size_kb = inst.size / 1024
                vms_html += """\
                            <tr style="height: 20px">
                            <td style="padding-left: 5px; font-size:12px; color:black; border: 1px solid #999;">
                            """+inst.vm_name+"""
                            </td><td style="padding-left: 5px; font-size:12px; color:black; border: 1px solid #999; ">
                            """+str(size_kb)+""" Kb or """+str(inst.size)+""" bytes </td></tr>
                            """
            
            if type == 'snapshot':
                subject = workload.display_name + ' Snapshot finished successfully'
                size_snap_kb = object.size / 1024

                minutes = object.time_taken / 60
                seconds = object.time_taken % 60
                time_unit = str(minutes)+' Minutes and '+str(seconds)+' Seconds'

                with open('/opt/stack/workloadmgr/workloadmgr/templates/snapshot_success.html', 'r') as content_file:
                    html = content_file.read()
                    
                html = html.replace('workload.display_name',workload.display_name)
                html = html.replace('workload_type.display_name',workload_type.display_name)
                html = html.replace('object.display_name',object.display_name)
                html = html.replace('object.snapshot_type',object.snapshot_type)
                html = html.replace('size_snap_kb',str(size_snap_kb))
                html = html.replace('object.size',str(object.size))
                html = html.replace('time_unit',str(time_unit))
                html = html.replace('object.host',object.host)
                html = html.replace('object.display_description',object.display_description)
                html = html.replace('vms_html',vms_html)

                
                if object.status == 'error':
                    subject = workload.display_name + ' Snapshot failed'                  
                    with open('/opt/stack/workloadmgr/workloadmgr/templates/snapshot_error.html', 'r') as content_file:
                        html = content_file.read()
                    html = html.replace('workload.display_name',workload.display_name)
                    html = html.replace('workload_type.display_name',workload_type.display_name)
                    html = html.replace('object.display_name',object.display_name)
                    html = html.replace('size_snap_kb',str(size_snap_kb))
                    html = html.replace('object.size',str(object.size))
                    html = html.replace('object.error_msg',object.error_msg)
                    html = html.replace('object.host',object.host)
                    html = html.replace('object.display_description',object.display_description)
                    html = html.replace('vms_html',vms_html) 


            elif type == 'restore':
                subject = workload.display_name + ' Restored successfully'

                size_snap_kb = object.size / 1024
                minutes = object.time_taken / 60
                seconds = object.time_taken % 60
                time_unit = str(minutes)+' Minutes and '+str(seconds)+' Seconds'

                with open('/opt/stack/workloadmgr/workloadmgr/templates/restore_success.html', 'r') as content_file:
                    html = content_file.read()
                html = html.replace('workload.display_name',workload.display_name)
                html = html.replace('workload_type.display_name',workload_type.display_name)
                html = html.replace('object.display_name',object.display_name)
                #html = html.replace('object.restore_type',object.restore_type)
                html = html.replace('size_snap_kb',str(size_snap_kb))
                html = html.replace('object.size',str(object.size))
                html = html.replace('time_unit',str(time_unit))
                html = html.replace('object.host',object.host)
                html = html.replace('object.display_description',object.display_description)
                html = html.replace('vms_html',vms_html)
                
                if object.status == 'error':
                    subject = workload.display_name + ' Restore failed'
                    with open('/opt/stack/workloadmgr/workloadmgr/templates/restore_error.html', 'r') as content_file:
                        html = content_file.read()
                    html = html.replace('workload.display_name',workload.display_name)
                    html = html.replace('workload_type.display_name',workload_type.display_name)
                    html = html.replace('object.display_name',object.display_name)
                    html = html.replace('size_snap_kb',str(size_snap_kb))
                    html = html.replace('object.size',str(object.size))
                    html = html.replace('object.error_msg',object.error_msg)
                    html = html.replace('object.host',object.host)
                    html = html.replace('object.display_description',object.display_description)
                    html = html.replace('vms_html',vms_html)

                
            msg = MIMEMultipart('alternative')
            msg['To'] = user.email
            #msg['From'] = 'admin@'+ socket.getfqdn()+'.vsphere'
            msg['From'] = settings.get_settings(context).get('smtp_default_sender')
            msg['Subject'] = subject        
            part2 = MIMEText(html, 'html')          
            msg.attach(part2)
            s = smtplib.SMTP(settings.get_settings(context).get('smtp_server_name'),
                             int(settings.get_settings(context).get('smtp_port')),
                             timeout= int(settings.get_settings(context).get('smtp_timeout')))
            if settings.get_settings(context).get('smtp_server_name') != 'localhost':
                s.ehlo()
                s.starttls()
                s.ehlo
                s.login(settings.get_settings(context).get('smtp_server_username'),settings.get_settings(context).get('smtp_server_password'))
            s.sendmail(msg['From'], msg['To'], msg.as_string())
            s.quit()
        
        except Exception as ex:
            LOG.exception(ex)
            pass
                
               
     
