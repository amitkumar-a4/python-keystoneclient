# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to the  workloadmgr service.
"""
import socket
import cPickle as pickle
import json
import importlib

from eventlet import greenthread

from datetime import datetime
from datetime import timedelta
import time
import threading
from distutils import version

from workloadmgr.apscheduler.scheduler import Scheduler
from workloadmgr.apscheduler.jobstores.sqlalchemy_store import SQLAlchemyJobStore
from sqlalchemy import create_engine

from novaclient import client
from workloadmgr import utils
from workloadmgr.workloads import rpcapi as workloads_rpcapi
from workloadmgr.scheduler import rpcapi as scheduler_rpcapi
from workloadmgr.db import base
from workloadmgr import exception as wlm_exceptions
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import jsonutils
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.image import glance
from workloadmgr import context
from workloadmgr.workflows import vmtasks
from workloadmgr.vault import vault
from workloadmgr.openstack.common import timeutils
from workloadmgr import auditlog
from workloadmgr import autolog
from workloadmgr.db.sqlalchemy import models

workload_lock = threading.Lock()

FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)
AUDITLOG = auditlog.getAuditLogger()

#do not decorate this function with autolog
def _snapshot_create_callback(*args, **kwargs):
    arg_str = autolog.format_args(args, kwargs)
    LOG.info(_("_snapshot_create_callback Enter - " + arg_str))
    
    from workloadmgr.workloads import API
    workloadmgrapi = API()
 
    workload_id = kwargs['workload_id']
    user_id = kwargs['user_id']
    project_id = kwargs['project_id']
    tenantcontext = nova._get_tenant_context(user_id, project_id)
    
    workload = workloadmgrapi.workload_get(tenantcontext, workload_id)

    #TODO: Make sure workload is in a created state
    if workload['status'] == 'error':
        LOG.info(_("Workload %(display_name)s is in error state. Cannot schedule snapshot operation") % workload)
        LOG.info(_("_snapshot_create_callback Exit"))
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
        LOG.info(_("Workload %(display_name)s is not in available state. Cannot schedule snapshot operation") % workload)
        LOG.info(_("_snapshot_create_callback Exit"))
        return

    # determine if the workload need to be full snapshot or incremental
    # the last full snapshot
    # if the last full snapshot is over policy based number of days, do a full backup
    snapshots = workloadmgrapi.db.snapshot_get_all_by_project_workload(tenantcontext,
                                                                       project_id, workload_id)
    jobscheduler = workload['jobschedule']

    snapshot_type = "incremental"
    if int(jobscheduler['fullbackup_interval']) > 0:
        # check full backup policy here
        num_of_incr_in_current_chain = 0
        for snap in snapshots:
            if snap.snapshot_type == 'full':
                break;
            else:
                num_of_incr_in_current_chain = num_of_incr_in_current_chain + 1
                
        if num_of_incr_in_current_chain >= int(jobscheduler['fullbackup_interval']):
           snapshot_type = "full"

        if snapshots.__len__ == 0:
           snapshot_type = 'full'

    try:
        snapshot = workloadmgrapi.workload_snapshot(tenantcontext, workload_id, snapshot_type, "jobscheduler", None)

        # Wait for snapshot to complete
        while True:
            snapshot_details = workloadmgrapi.snapshot_get(tenantcontext, snapshot['id'])
            if snapshot_details['status'].lower() == "available" or snapshot_details['status'].lower() == "error":
                break
            time.sleep(30)
    except Exception as ex:
        LOG.exception(_("Error creating a snapshot for workload %d") % workload_id)
        pass
    LOG.info(_("_snapshot_create_callback Exit"))

class API(base.Base):
    """API for interacting with the Workload Manager."""

    ## This singleton implementation is not thread safe
    ## REVISIT: should the singleton be threadsafe

    __single = None # the one, true Singleton
    
    @autolog.log_method(logger=Logger)
    def __new__(classtype, *args, **kwargs):
        # Check to see if a __single exists already for this class
        # Compare class types instead of just looking for None so
        # that subclasses will create their own __single objects
        if classtype != type(classtype.__single):
            classtype.__single = object.__new__(classtype, *args, **kwargs)
        return classtype.__single
    
    @autolog.log_method(logger=Logger)
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
    
    @autolog.log_method(logger=Logger)    
    def workload_type_get(self, context, workload_type_id):
        workload_type = self.db.workload_type_get(context, workload_type_id)
        workload_type_dict = dict(workload_type.iteritems())
        metadata = {}
        for kvpair in workload_type.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_type_dict['metadata'] = metadata        
        return workload_type_dict
    
    @autolog.log_method(logger=Logger)
    def workload_type_show(self, context, workload_type_id):
        workload_type = self.db.workload_type_get(context, workload_type_id)
        workload_type_dict = dict(workload_type.iteritems())
        metadata = {}
        for kvpair in workload_type.metadata:
            metadata.setdefault(kvpair['key'], kvpair['value'])
        workload_type_dict['metadata'] = metadata
        return workload_type_dict
    
    @autolog.log_method(logger=Logger)
    def workload_type_get_all(self, context, search_opts={}):
        workload_types = self.db.workload_types_get(context)
        return workload_types
    
    @autolog.log_method(logger=Logger)
    def workload_type_create(self, context, id, name, description, is_public, metadata):
        """
        Create a workload_type. No RPC call is made
        """
        AUDITLOG.log(context,'WorkloadType Create Requested', None)
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'id': id,
                   'display_name': name,
                   'display_description': description,
                   'is_public' : is_public,
                   'status': 'available',
                   'metadata': metadata,}

        workload_type = self.db.workload_type_create(context, options)
        AUDITLOG.log(context,'WorkloadType Created', workload_type)
        return workload_type
    
    @autolog.log_method(logger=Logger)
    def workload_type_delete(self, context, workload_type_id):
        """
        Delete a workload_type. No RPC call is made
        """
        workload_type = self.workload_type_get(context, workload_type_id)
        AUDITLOG.log(context,'WorkloadType Delete Requested', workload_type)
        if workload_type['status'] not in ['available', 'error']:
            msg = _("WorkloadType status must be 'available' or 'error'")
            raise wlm_exceptions.InvalidState(reason=msg)

        #TODO(giri): check if this workload_type is referenced by other workloads
                    
        self.db.workload_type_delete(context, workload_type_id)
        AUDITLOG.log(context,'WorkloadType Deleted', workload_type)
    
    @autolog.log_method(logger=Logger)   
    def workload_type_discover_instances(self, context, workload_type_id, metadata):
        """
        Discover Instances of a workload_type. RPC call is made
        """
        if not metadata:
            msg = _('metadata field is null. Pass valid metadata to discover the workload')
            raise wlm_exceptions.Invalid(reason=msg)
        try:
            return self.workloads_rpcapi.workload_type_discover_instances(context,
                                                                      socket.gethostname(),
                                                                      workload_type_id,
                                                                      metadata) 
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 
   
    @autolog.log_method(logger=Logger)
    def workload_type_topology(self, context, workload_type_id, metadata):
        """
        Topology  of a workload_type. RPC call is made
        """
        if not metadata:
            msg = _('metadata field is null. Pass valid metadata to discover the workload')
            raise wlm_exceptions.Invalid(reason=msg)

        try:
            return self.workloads_rpcapi.workload_type_topology(context,
                                                            socket.gethostname(),
                                                            workload_type_id,
                                                            metadata) 
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 

    @autolog.log_method(logger=Logger)
    def workload_get(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        
        workload_dict['storage_usage'] = {'usage': 0, 
                                          'full': {'snap_count': 0, 'usage': 0}, 
                                          'incremental': {'snap_count': 0, 'usage': 0}
                                          }
        for workload_snapshot in self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id, read_deleted='yes'):
            if workload_snapshot.data_deleted == False:
                if workload_snapshot.snapshot_type == 'incremental':
                    workload_dict['storage_usage']['incremental']['snap_count'] = workload_dict['storage_usage']['incremental']['snap_count'] + 1
                    workload_dict['storage_usage']['incremental']['usage'] = workload_dict['storage_usage']['incremental']['usage'] + workload_snapshot.size
                else:
                    workload_dict['storage_usage']['full']['snap_count'] = workload_dict['storage_usage']['full']['snap_count'] + 1
                    workload_dict['storage_usage']['full']['usage'] = workload_dict['storage_usage']['full']['usage'] + workload_snapshot.size
        workload_dict['storage_usage']['usage'] =  utils.sizeof_fmt(workload_dict['storage_usage']['full']['usage'] + workload_dict['storage_usage']['incremental']['usage'])
        workload_dict['storage_usage']['full']['usage'] = utils.sizeof_fmt(workload_dict['storage_usage']['full']['usage'])

        workload_dict['storage_usage']['incremental']['usage'] = utils.sizeof_fmt(workload_dict['storage_usage']['incremental']['usage'])
 
        workload_vms = []
        for workload_vm_obj in self.db.workload_vms_get(context, workload.id):
            workload_vm = {'id': workload_vm_obj.vm_id, 'name':workload_vm_obj.vm_name}
            metadata = {}
            for kvpair in workload_vm_obj.metadata:
                metadata.setdefault(kvpair['key'], kvpair['value'])
            workload_vm['metadata'] = metadata
            workload_vms.append(workload_vm)              
        workload_dict['instances'] = workload_vms
        
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
    
    @autolog.log_method(logger=Logger)
    def workload_show(self, context, workload_id):
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())

        workload_dict['storage_usage'] = {'usage': 0, 
                                          'full': {'snap_count': 0, 'usage': 0}, 
                                          'incremental': {'snap_count': 0, 'usage': 0}
                                         }
       
        for workload_snapshot in self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id, read_deleted='yes'):
            if workload_snapshot.data_deleted == False:
                if workload_snapshot.snapshot_type == 'incremental':
                    workload_dict['storage_usage']['incremental']['snap_count'] = workload_dict['storage_usage']['incremental']['snap_count'] + 1
                    workload_dict['storage_usage']['incremental']['usage'] = workload_dict['storage_usage']['incremental']['usage'] + workload_snapshot.size
                else:
                    workload_dict['storage_usage']['full']['snap_count'] = workload_dict['storage_usage']['full']['snap_count'] + 1
                    workload_dict['storage_usage']['full']['usage'] = workload_dict['storage_usage']['full']['usage'] + workload_snapshot.size
        workload_dict['storage_usage']['usage'] =  utils.sizeof_fmt(workload_dict['storage_usage']['full']['usage'] + workload_dict['storage_usage']['incremental']['usage'])
        workload_dict['storage_usage']['full']['usage'] = utils.sizeof_fmt(workload_dict['storage_usage']['full']['usage'])

        workload_dict['storage_usage']['incremental']['usage'] = utils.sizeof_fmt(workload_dict['storage_usage']['incremental']['usage'])
                
        workload_vms = []
        for workload_vm_obj in self.db.workload_vms_get(context, workload.id):
            workload_vm = {'id': workload_vm_obj.vm_id, 'name':workload_vm_obj.vm_name}
            metadata = {}
            for kvpair in workload_vm_obj.metadata:
                metadata.setdefault(kvpair['key'], kvpair['value'])
            workload_vm['metadata'] = metadata
            workload_vms.append(workload_vm)              
        workload_dict['instances'] = workload_vms
        
        metadata = {}
        metadata_type = self.db.workload_type_get(context, workload.workload_type_id).metadata
        for kvpair in workload.metadata:
            mtype = None
            for mtype in metadata_type:
                try: 
                    if mtype['key'] == kvpair['key'] and json.loads(mtype.value)['type'] == 'password':
                        break
                except:
                    pass

            try:
                if mtype['key'] == kvpair['key'] and json.loads(mtype.value)['type'] == 'password':
                    metadata.setdefault(kvpair['key'], "**********")
                else:
                    metadata.setdefault(kvpair['key'], kvpair['value'])
            except:
                metadata.setdefault(kvpair['key'], kvpair['value'])
                pass

        workload_dict['metadata'] = metadata
        
        workload_dict['jobschedule'] = pickle.loads(str(workload.jobschedule))
        workload_dict['jobschedule']['enabled'] = False 

        # find the job object based on workload_id
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                workload_dict['jobschedule']['enabled'] = True
                timedelta = job.compute_next_run_time(datetime.now()) - datetime.now()
                workload_dict['jobschedule']['nextrun'] = timedelta.total_seconds()
                break

                
        return workload_dict
    
    @autolog.log_method(logger=Logger)
    def workload_get_all(self, context, search_opts={}):
        workloads = self.db.workload_get_all(context)
        return workloads
    
    @autolog.log_method(logger=Logger)
    def workload_create(self, context, name, description, workload_type_id,
                        source_platform, instances, jobschedule, metadata,
                        availability_zone=None):
        """
        Make the RPC call to create a workload.
        """
        try:
            AUDITLOG.log(context,'Workload Create Requested', None)
            compute_service = nova.API(production=True)
            instances_with_name = compute_service.get_servers(context,admin=True)

            #TODO(giri): optimize this lookup
            for instance in instances:
                for instance_with_name in instances_with_name:
                    if instance['instance-id'] == instance_with_name.id:
                        instance['instance-name'] = instance_with_name.name
                        if instance_with_name.metadata:
                            instance['metadata'] = instance_with_name.metadata
                            if 'imported_from_vcenter' in instance_with_name.metadata and \
                                instances_with_name[0].metadata['imported_from_vcenter'] == 'True':
                                source_platform = "vmware"
        
            workload_type_id_valid = False
            workload_types = self.workload_type_get_all(context)            
            for workload_type in workload_types:
                if workload_type_id == workload_type.id:
                    workload_type_id_valid = True
                    break 
            if workload_type_id_valid == False:
                msg = _('Invalid workload type')
                raise wlm_exceptions.Invalid(reason=msg)                

            if not 'hostnames' in metadata:
                metadata['hostnames'] = json.dumps([])

            if not 'preferredgroup' in metadata:
                metadata['preferredgroup'] = json.dumps([])

            options = {'user_id': context.user_id,
                       'project_id': context.project_id,
                       'display_name': name,
                       'display_description': description,
                       'status': 'creating',
                       'source_platform': source_platform,
                       'workload_type_id': workload_type_id,
                       'metadata' : metadata,
                       'jobschedule': pickle.dumps(jobschedule, 0),
                       'host': socket.gethostname(), }
            workload = self.db.workload_create(context, options)
            for instance in instances:
                values = {'workload_id': workload.id,
                          'vm_id': instance['instance-id'],
                          'vm_name': instance['instance-name'],
                          'status': 'available',
                          'metadata': instance.get('metadata', {})}
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
            try:
                self.workload_add_scheduler_job(jobschedule, workload)
            except Exception as ex:
                LOG.exception(ex)    
                
            AUDITLOG.log(context, "Workload Created", workload)        
            return workload
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))
    
    @autolog.log_method(logger=Logger)
    def workload_add_scheduler_job(self, jobschedule, workload):
        if jobschedule and len(jobschedule): 
            if 'enabled' in jobschedule and jobschedule['enabled']:                                       
                self._scheduler.add_workloadmgr_job(_snapshot_create_callback, 
                                                    jobschedule,
                                                    jobstore='jobscheduler_store', 
                                                    kwargs={'workload_id':workload.id,  
                                                            'user_id': workload.user_id, 
                                                            'project_id':workload.project_id})

    @autolog.log_method(logger=Logger)
    def workload_modify(self, context, workload_id, workload):
        """
        Make the RPC call to modify a workload.
        """
        AUDITLOG.log(context,'Workload Modify Requested', None)
        
        purge_metadata = False
        options = {}
        if 'name' in workload and workload['name']:
            options['display_name'] = workload['name']
        if 'description' in workload and workload['description']:
            options['display_description'] = workload['description']  
        #if 'workload_type_id' in workload:
        #    options['workload_type_id'] = workload['workload_type_id']                
        if 'metadata' in workload and workload['metadata']:
            purge_metadata = True
            options['metadata'] = workload['metadata']     
        if 'jobschedule' in workload and workload['jobschedule']:
            options['jobschedule'] = pickle.dumps(workload['jobschedule'], 0)    
        if  'instances' in workload and workload['instances']:
            for vm in self.db.workload_vms_get(context, workload_id):
                self.db.workload_vms_delete(context, vm.vm_id, workload_id) 
            #TODO(giri): optimize this lookup
            compute_service = nova.API(production=True)
            instances_with_name = compute_service.get_servers(context,admin=True)               
            instances = workload['instances']
            for instance in instances:
                for instance_with_name in instances_with_name:
                    if instance['instance-id'] == instance_with_name.id:
                        instance['instance-name'] = instance_with_name.name  
                        instance['metadata'] = instance_with_name.metadata
            for instance in instances:
                values = {'workload_id': workload_id,
                          'vm_id': instance['instance-id'],
                          'metadata': instance['metadata'],
                          'vm_name': instance['instance-name']}
                vm = self.db.workload_vms_create(context, values)                                       

        workload_obj = self.db.workload_update(context, workload_id, options, purge_metadata)
            
        AUDITLOG.log(context,'Workload Modified', workload_obj)
            
    @autolog.log_method(logger=Logger)
    def workload_delete(self, context, workload_id):
        """
        Delete a workload. No RPC call is made
        """
        try:
            workload = self.workload_get(context, workload_id)
            AUDITLOG.log(context,'Workload Delete Requested', workload)
            if workload['status'] not in ['available', 'error']:
                msg = _("Workload status must be 'available' or 'error'")
                raise wlm_exceptions.InvalidState(reason=msg)
            
            workloads = self.db.workload_get_all(context)
            for workload in workloads:
                if workload.deleted:
                    continue
                workload_type = self.db.workload_type_get(context, workload.workload_type_id)
                if (workload_type.display_name == 'Composite'):
                    for kvpair in workload.metadata:
                        if kvpair['key'] == 'workloadgraph':
                            graph = json.loads(kvpair['value'])
                            for flow in graph['children']:
                                for member in flow['children']:
                                    if 'type' in member:
                                        if member['data']['id'] == workload_id:
                                            msg = _('Operation not allowed since this workload is a member of a composite workflow')
                                            raise wlm_exceptions.InvalidState(reason=msg)              
    
            snapshots = self.db.snapshot_get_all_by_project_workload(context, context.project_id, workload_id)
            if len(snapshots) > 0:
                msg = _('This workload contains snapshots. Please delete all snapshots and try again..')
                raise wlm_exceptions.InvalidState(reason=msg)
                        
            # First unschedule the job
            jobs = self._scheduler.get_jobs()
            for job in jobs:
                if job.kwargs['workload_id'] == workload_id:
                    self._scheduler.unschedule_job(job)
                    break
    
            self.workloads_rpcapi.workload_delete(context, workload['host'], workload_id)
            AUDITLOG.log(context,'Workload Deleted', workload)
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))         
    
    @autolog.log_method(logger=Logger)    
    def import_workloads(self, context):
        AUDITLOG.log(context,'Import Workloads Requested', None)
        try:
            workloads = []
            import_workload_module = None
            for workload_url in vault.get_workloads(context):
                try:
                    workload_values = json.loads(vault.get_object(workload_url['workload_url'] + '/workload_db'))
                except Exception as ex:
                    LOG.exception(ex)
                    continue                    
                """
                try:
                    jobs = self._scheduler.get_jobs()
                    for job in jobs:
                        if job.kwargs['workload_id'] == workload_values['id']:
                            self._scheduler._remove_job(job, 'alias', self._jobstore)
                    self.db.purge_workload(context, workload_values['id'])
                except Exception as ex:
                    LOG.exception(ex)
                """
                try:            
                    import_workload_module = importlib.import_module('workloadmgr.db.imports.import_workload_' +  workload_values['version'].replace('.', '_'))
                    import_workload_method = getattr(import_workload_module, 'import_workload')
                    workload = import_workload_method(context, workload_url, models.DB_VERSION)
                    workloads.append(workload)
                except Exception as ex:
                    LOG.exception(ex)
            if not import_workload_module:
                import_workload_module = importlib.import_module('workloadmgr.db.imports.import_workload_1_0_125')
            import_settings_method = getattr(import_workload_module, 'import_settings')
            import_settings_method(context, models.DB_VERSION)
        except Exception as ex:
            LOG.exception(ex)
        finally:
            vault.purge_staging_area(context)                
        AUDITLOG.log(context,'Import Workloads Completed', None)
        return workloads
    
    @autolog.log_method(logger=Logger)
    def get_nodes(self, context):
        nodes = []
        try:
            for node_record in self.db.service_get_all_by_topic(context, topic='workloadmgr-workloads'):
                try:
                    ipaddress = ''
                    ip_addresses = node_record.ip_addresses.split(';')
                    if len(node_record.ip_addresses) > 0 and len(node_record.ip_addresses[0]) > 0:
                        ipaddress = ip_addresses[0]
                    nodes.append({'node':node_record.host, 
                                  'version':node_record.version, 
                                  'ipaddress': ipaddress})
                except Exception as ex:
                    LOG.exception(ex)                      
        except Exception as ex:
            LOG.exception(ex)
        return dict(nodes=nodes)

    @autolog.log_method(logger=Logger)
    def remove_node(self, context, ip):
        try:
            for node_record in self.db.service_get_all_by_topic(context, topic='workloadmgr-workloads'):
                try:
                    ipaddress = ''
                    ip_addresses = node_record.ip_addresses.split(';')
                    if len(node_record.ip_addresses) > 0 and len(node_record.ip_addresses[0]) > 0:
                        ipaddress = ip_addresses[0]
                    if any([ipaddress == ip , node_record.host == ip]) and socket.gethostname() != node_record.host:
                       self.db.service_delete(context, int(node_record.id))

                except Exception as ex:
                    LOG.exception(ex)
        except Exception as ex:
            LOG.exception(ex)
    
    @autolog.log_method(logger=Logger)
    def get_storage_usage(self, context):
        total_capacity, total_utilization = vault.get_total_capacity(context)
        storage_usage = {'total': 0, 'full': 0, 'incremental': 0, 'total_capacity': utils.sizeof_fmt(total_capacity), 'total_utilization': utils.sizeof_fmt(total_utilization)}
        try:
            for workload in self.db.workload_get_all(context, read_deleted='yes'):
                for workload_snapshot in self.db.snapshot_get_all_by_workload(context, workload.id, read_deleted='yes'):
                    if workload_snapshot.data_deleted == False:
                        if workload_snapshot.snapshot_type == 'incremental':
                            storage_usage['incremental'] = storage_usage['incremental'] + workload_snapshot.size
                        else:
                            storage_usage['full'] = storage_usage['full'] + workload_snapshot.size
            storage_usage['total'] =  utils.sizeof_fmt(storage_usage['full'] + storage_usage['incremental'])
            storage_usage['full'] = utils.sizeof_fmt(storage_usage['full'])
            storage_usage['incremental'] = utils.sizeof_fmt(storage_usage['incremental'])
        except Exception as ex:
            LOG.exception(ex)
        return storage_usage
    
    @autolog.log_method(logger=Logger)
    def get_recentactivities(self, context, time_in_minutes):
        recentactivites = []
        now = timeutils.utcnow()
        time_offset = datetime.now() - datetime.utcnow()
        try:
            for workload in self.db.workload_get_all(context, read_deleted='yes'):
                if workload.deleted:
                    if now - workload.deleted_at < timedelta(minutes=time_in_minutes):
                        activity_description = 'Workload ' + workload.display_name + ' deleted'
                        recentactivity = {'activity_type': 'delete',
                                          'activity_time': workload.deleted_at,
                                          'activity_result': workload.status,
                                          'activity_description': activity_description,
                                          'object_type': 'workload',
                                          'object_name': workload.display_name,
                                          'object_id': workload.id,
                                          }
                        recentactivites.append(recentactivity)
                        continue
                elif now - workload.created_at < timedelta(minutes=time_in_minutes):
                    if workload.status == 'error':
                        activity_description = 'Workload ' + workload.display_name + ' failed'
                    else:
                        activity_description = 'Workload ' + workload.display_name + ' created'
                    recentactivity = {'activity_type': 'create',
                                      'activity_time': workload.created_at,
                                      'activity_result': workload.status,
                                      'activity_description': activity_description,
                                      'object_type': 'workload',
                                      'object_name': workload.display_name,
                                      'object_id': workload.id,
                                      }
                    recentactivites.append(recentactivity)
                    continue
            
            for snapshot in self.db.snapshot_get_all(context, read_deleted='yes'):
                if snapshot.deleted:
                    if now - snapshot.deleted_at < timedelta(minutes=time_in_minutes):
                        workload = self.db.workload_get(context, snapshot.workload_id)
                        activity_description =  "Snapshot '%s' of Workload '%s' deleted" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name)
                        recentactivity = {'activity_type': 'delete',
                                          'activity_time': snapshot.deleted_at,
                                          'activity_result': snapshot.status,
                                          'activity_description': activity_description,
                                          'object_type': 'snapshot',
                                          'object_name': snapshot.display_name,
                                          'object_id': snapshot.id,
                                          }
                        recentactivites.append(recentactivity)
                        continue
                elif now - snapshot.created_at < timedelta(minutes=time_in_minutes):
                    workload = self.db.workload_get(context, snapshot.workload_id)
                    if snapshot.status == 'error':
                        activity_description =  "Snapshot '%s' of Workload '%s' failed" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name)                     
                    elif snapshot.status == 'available':
                        activity_description =  "Snapshot '%s' of Workload '%s' created" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name) 
                    else:
                        activity_description =  "Snapshot '%s' of Workload '%s' is in progress" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name)                                                                  
                    recentactivity = {'activity_type': 'create',
                                      'activity_time': snapshot.created_at,
                                      'activity_result': snapshot.status,
                                      'activity_description': activity_description,
                                      'object_type': 'snapshot',
                                      'object_name': snapshot.display_name,
                                      'object_id': snapshot.id,
                                      }
                    recentactivites.append(recentactivity)
                    continue

            for restore in self.db.restore_get_all(context, read_deleted='yes'):
                if restore.deleted:
                    if now - restore.deleted_at < timedelta(minutes=time_in_minutes):
                        snapshot = self.db.snapshot_get(context, restore.snapshot_id)
                        workload = self.db.workload_get(context, snapshot.workload_id)
                        
                        activity_description =  "Restore of Snapshot '%s' of Workload '%s' deleted" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name)                  
                        recentactivity = {'activity_type': 'delete',
                                         'activity_time': restore.deleted_at,
                                         'activity_result': restore.status,
                                         'activity_description': activity_description,
                                         'object_type': 'restore',
                                         'object_name': restore.display_name,
                                         'object_id': restore.id,
                                         }
                        recentactivites.append(recentactivity)
                        continue
                elif now - restore.created_at < timedelta(minutes=time_in_minutes):
                    snapshot = self.db.snapshot_get(context, restore.snapshot_id)
                    workload = self.db.workload_get(context, snapshot.workload_id)
                    if restore.status == 'error':
                        activity_description =  "Restore of Snapshot '%s' of Workload '%s' failed" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name)      
                    elif restore.status == 'available':
                        activity_description =  "Restore of Snapshot '%s' of Workload '%s' completed" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name)   
                    else:
                        activity_description =  "Restore of Snapshot '%s' of Workload '%s' is in progress" %\
                                                ((snapshot.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p"), 
                                                 workload.display_name)   
                          
                    recentactivity = {'activity_type': 'create',
                                      'activity_time': restore.created_at,
                                      'activity_result': restore.status,
                                      'activity_description': activity_description,
                                      'object_type': 'restore',
                                      'object_name': restore.display_name,
                                      'object_id': restore.id,
                                      }
                    recentactivites.append(recentactivity)
                    continue
                
                
        except Exception as ex:
            LOG.exception(ex)
        return dict(recentactivites=recentactivites)    
    
    @autolog.log_method(logger=Logger)
    def get_auditlog(self, context, time_in_minutes, time_from, time_to):
        auditlog = []
        try:
            auditlog = AUDITLOG.get_records(time_in_minutes, time_from, time_to)
        except Exception as ex:
            LOG.exception(ex)
        return dict(auditlog=auditlog)
    
    @autolog.log_method(logger=Logger)
    def workload_get_workflow(self, context, workload_id):
        """
        Get the workflow of the workload. RPC call is made
        """
        try:
            return self.workloads_rpcapi.workload_get_workflow_details(context,
                                                                   socket.gethostname(),
                                                                   workload_id)    
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 

    @autolog.log_method(logger=Logger)
    def workload_get_topology(self, context, workload_id):
        """
        Get the topology of the workload. RPC call is made
        """
        try:
            return self.workloads_rpcapi.workload_get_topology(context,
                                                           socket.gethostname(),
                                                           workload_id)   
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 

    @autolog.log_method(logger=Logger)
    def workload_discover_instances(self, context, workload_id):
        """
        Discover Instances of a workload_type. RPC call is made
        """
        try:
            return self.workloads_rpcapi.workload_discover_instances(context,
                                                                 socket.gethostname(),
                                                                 workload_id)
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 
                     
    @autolog.log_method(logger=Logger)
    def _is_workload_paused(self, context, workload_id): 
        workload = self.workload_get(context, workload_id)
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                return False
        return True
               
    @autolog.log_method(logger=Logger)
    def workload_pause(self, context, workload_id):
        """
        Pause workload job schedule. No RPC call is made
        """
        workload = self.workload_get(context, workload_id)
        AUDITLOG.log(context,'Workload Pause Requested', workload)
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                self._scheduler.unschedule_job(job)
                break
        AUDITLOG.log(context,'Workload Paused', workload)
            

    @autolog.log_method(logger=Logger)
    def workload_resume(self, context, workload_id):
        workload = self.workload_get(context, workload_id)
        AUDITLOG.log(context,'Workload Resume Requested', workload)
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                msg = _('Workload job scheduler is not paused')
                raise wlm_exceptions.InvalidState(reason=msg)
        jobschedule = workload['jobschedule']
        if len(jobschedule) >= 5:
            self._scheduler.add_workloadmgr_job(_snapshot_create_callback, 
                                                jobschedule,
                                                jobstore='jobscheduler_store', 
                                                kwargs={'workload_id':workload_id,  
                                                        'user_id': workload['user_id'],
                                                        'project_id':workload['project_id']})
            AUDITLOG.log(context,'Workload Resumed', workload)

    @autolog.log_method(logger=Logger)
    def workload_unlock(self, context, workload_id):
        workload = self.workload_get(context, workload_id)
        AUDITLOG.log(context,'Workload Unlock Requested', workload)
        if not workload['deleted']:
            self.db.workload_update(context, workload_id, {'status': 'available'})         
        AUDITLOG.log(context,'Workload Unlocked', workload)

    @autolog.log_method(logger=Logger)
    def workload_snapshot(self, context, workload_id, snapshot_type, name, description):
        """
        Make the RPC call to snapshot a workload.
        """
        try:
            workload = self.workload_get(context, workload_id)

            AUDITLOG.log(context,'Workload Snapshot Requested', workload)
        
            workloads = self.db.workload_get_all(context)
            for workload in workloads:
                if workload.deleted:
                    continue
                workload_type = self.db.workload_type_get(context, workload.workload_type_id)
                if (workload_type.display_name == 'Composite'):
                    for kvpair in workload.metadata:
                        if kvpair['key'] == 'workloadgraph':
                            graph = json.loads(kvpair['value'])
                            for flow in graph['children']:
                                for member in flow['children']:
                                    if 'type' in member:
                                        if member['data']['id'] == workload_id:
                                            msg = _('Operation not allowed since this workload is a member of a composite workflow')
                                            raise wlm_exceptions.InvalidState(reason=msg)                                    

            try:
                workload_lock.acquire()
                workload = self.workload_get(context, workload_id)
                if workload['status'].lower() != 'available':
                    msg = _("Workload must be in the 'available' state to take a snapshot")
                    raise wlm_exceptions.InvalidState(reason=msg)
                self.db.workload_update(context, workload_id, {'status': 'locked'})
            finally:
                workload_lock.release()                    

            metadata = {}
            metadata.setdefault('cancel_requested','0')
 
            options = {'user_id': context.user_id,
                       'project_id': context.project_id,
                       'workload_id': workload_id,
                       'snapshot_type': snapshot_type,
                       'display_name': name,
                       'display_description': description,
                       'host':'',                   
                       'status': 'creating',
                       'metadata': metadata, }
            snapshot = self.db.snapshot_create(context, options)

            self.db.snapshot_update(context, 
                                    snapshot.id, 
                                    {'progress_percent': 0, 
                                     'progress_msg': 'Snapshot operation is scheduled',
                                     'status': 'executing'
                                    })
            self.scheduler_rpcapi.workload_snapshot(context, FLAGS.scheduler_topic, snapshot['id'])
            return snapshot
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 

    @autolog.log_method(logger=Logger)
    def snapshot_get(self, context, snapshot_id):
        rv = self.db.snapshot_get(context, snapshot_id)
        snapshot_details  = dict(rv.iteritems())
        snapshot_vms = []
        try:
            for snapshot_vm_obj in self.db.snapshot_vms_get(context, snapshot_id):
                snapshot_vm = {'id': snapshot_vm_obj.vm_id, 
                               'name':snapshot_vm_obj.vm_name,
                               'status':snapshot_vm_obj.status,}
                metadata = {}
                for kvpair in snapshot_vm_obj.metadata:
                    metadata.setdefault(kvpair['key'], kvpair['value'])
                snapshot_vm['metadata'] = metadata
                snapshot_vms.append(snapshot_vm)              
        except Exception as ex:
            pass
        snapshot_details.setdefault('instances', snapshot_vms)    
        return snapshot_details

    #@autolog.log_method(logger=Logger, log_args=False, log_retval=False)
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
       
        snapshot_vms = []
        try:
            for snapshot_vm_obj in self.db.snapshot_vms_get(context, snapshot_id):
                snapshot_vm = {'id': snapshot_vm_obj.vm_id, 
                               'name':snapshot_vm_obj.vm_name,
                               'status':snapshot_vm_obj.status,
                               }
                metadata = {}
                for kvpair in snapshot_vm_obj.metadata:
                    metadata.setdefault(kvpair['key'], kvpair['value'])
                snapshot_vm['metadata'] = metadata
                vdisks = snapshot_vm['metadata'].get('vdisks', '[]')
                vdisks = json.loads(vdisks)                
                snapshot_vm['nics'] = []
                snapshot_vm_resources = self.db.snapshot_vm_resources_get(context, snapshot_vm_obj.vm_id, snapshot_id)
                snapshot_vm_common_resources = self.db.snapshot_vm_resources_get(context, snapshot_id, snapshot_id)                
                for snapshot_vm_resource in snapshot_vm_resources:                
                    """ flavor """
                    if snapshot_vm_resource.resource_type == 'flavor': 
                        vm_flavor = snapshot_vm_resource
                        snapshot_vm['flavor'] = {'vcpus' : self.db.get_metadata_value(vm_flavor.metadata, 'vcpus'),
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
                        snapshot_vm['nics'].append(nic)
                    """ vdisks """
                    if snapshot_vm_resource.resource_type == 'disk':
                        label = self.db.get_metadata_value(snapshot_vm_resource.metadata,'label')
                        for vdisk in vdisks:
                            if vdisk['label'] == label:
                                vdisk['restore_size'] = snapshot_vm_resource.restore_size
                                break
                snapshot_vm['metadata']['vdisks'] = json.dumps(vdisks)
                snapshot_vms.append(snapshot_vm)              

        except Exception as ex:
            LOG.exception(ex)

        snapshot_details['instances'] = snapshot_vms    
        return snapshot_details
    
    @autolog.log_method(logger=Logger)
    def snapshot_get_all(self, context, workload_id=None):
        snapshots = self.db.snapshot_get_all(context, workload_id)
        return snapshots
    
    @autolog.log_method(logger=Logger)
    def snapshot_delete(self, context, snapshot_id):
        """
        Delete a workload snapshot. No RPC call required
        """
        try:
            snapshot = self.snapshot_get(context, snapshot_id)
            AUDITLOG.log(context,'Snapshot Delete Requested', snapshot)
            
            if snapshot['status'] not in ['available', 'error', 'cancelled']:
                msg = _("Snapshot status must be 'available' or 'error' or 'cancelled'")
                raise wlm_exceptions.InvalidState(reason=msg)
            
            try:
                workload_lock.acquire()
                workload = self.workload_get(context, snapshot['workload_id'])
                if workload['status'].lower() != 'available':
                    msg = _("Workload must be in the 'available' state to delete a snapshot")
                    raise wlm_exceptions.InvalidState(reason=msg)
                self.db.workload_update(context, snapshot['workload_id'], {'status': 'locked'})
            finally:
                workload_lock.release()                    
            

            restores = self.db.restore_get_all_by_project_snapshot(context, context.project_id, snapshot_id)
            for restore in restores:
                if restore.restore_type == 'test':
                    msg = _('This workload snapshot contains testbubbles')
                    raise wlm_exceptions.InvalidState(reason=msg)      

            status_messages = {'message': 'Snapshot delete operation starting'} 
            options = {
                       'display_name': "Snapshot Delete",
                       'display_description': "Snapshot delete for snapshot id %s" % snapshot_id,
                       'status': "starting",
                       'status_messages':  status_messages,
                      }

            task = self.db.task_create(context, options)
 
            self.workloads_rpcapi.snapshot_delete(context, workload['host'], snapshot_id, task.id)
            AUDITLOG.log(context,'Snapshot Deleted', snapshot)

            return task.id
            
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 
        
    @autolog.log_method(logger=Logger)
    def snapshot_restore(self, context, snapshot_id, test, name, description, options):
        """
        Make the RPC call to restore a snapshot.
        """
        try:
            snapshot = self.snapshot_get(context, snapshot_id)
            AUDITLOG.log(context,'Snapshot Restore Requested', snapshot)
            workload = self.workload_get(context, snapshot['workload_id'])
            if snapshot['status'] != 'available':
                msg = _('Snapshot status must be available')
                raise wlm_exceptions.InvalidState(reason=msg)
        
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
                       'host':'',                   
                       'status': 'restoring',}
            restore = self.db.restore_create(context, values)

            self.db.restore_update(context, 
                                    restore.id, 
                                    {'progress_percent': 0, 
                                     'progress_msg': 'Restore operation is scheduled',
                                     'status': 'restoring'
                                    })
            self.workloads_rpcapi.snapshot_restore(context, workload['host'], restore['id'])
            AUDITLOG.log(context,'Workload(' + workload['display_name'] + ') ' + 'Snapshot Restored', restore)
            return restore
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 
    
    @autolog.log_method(logger=Logger)
    def snapshot_cancel(self, context, snapshot_id):
        """
        Make the RPC call to cancel snapshot 
        """
        try:
            snapshot = self.db.snapshot_get(context, snapshot_id)
            if snapshot.status in ['available','cancelled','error']:
               return

            metadata = {}
            metadata.setdefault('cancel_requested','1')
            self.db.snapshot_update(context,
                                    snapshot_id,
                                    {
                                     'metadata': metadata,
                                     'status': 'cancelling'
                                    })

            #AUDITLOG.log(context,'Snapshot Cancel Requested', snapshot_id)

            return True

        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))


    @autolog.log_method(logger=Logger)
    def snapshot_mount(self, context, snapshot_id):
        """
        Make the RPC call to Mount the snapshot.
        """
        try:
            snapshot = self.snapshot_get(context, snapshot_id)
            if not snapshot:
                msg = _('Invalid snapshot id')
                raise wlm_exceptions.Invalid(reason=msg)

            AUDITLOG.log(context,'Snapshot Mount Requested', snapshot)
            workload = self.workload_get(context, snapshot['workload_id'])
            if snapshot['status'] != 'available':
                msg = _('Snapshot status must be available')
                raise wlm_exceptions.InvalidState(reason=msg)
            mounturl = self.workloads_rpcapi.snapshot_mount(context, workload['host'], snapshot_id)
                        
            AUDITLOG.log(context,'Workload(' + workload['display_name'] + ') ' + 'Snapshot Mounted', snapshot)
            return mounturl
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 
        
    @autolog.log_method(logger=Logger)
    def snapshot_dismount(self, context, snapshot_id):
        """
        Make the RPC call to Dismount the snapshot.
        """
        try:
            snapshot = self.snapshot_get(context, snapshot_id)
            if not snapshot:
                msg = _('Invalid snapshot id')
                raise wlm_exceptions.Invalid(reason=msg)
            AUDITLOG.log(context,'Snapshot Dismount Requested', snapshot)
            workload = self.workload_get(context, snapshot['workload_id'])
            if snapshot['status'] != 'mounted':
                msg = _('Snapshot status must be mounted')
                raise wlm_exceptions.InvalidState(reason=msg)
            self.workloads_rpcapi.snapshot_dismount(context, workload['host'], snapshot_id)
            AUDITLOG.log(context,'Workload(' + workload['display_name'] + ') ' + 'Snapshot Dismounted', snapshot)
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))         

    @autolog.log_method(logger=Logger)
    def restore_get(self, context, restore_id):
        rv = self.db.restore_get(context, restore_id)
        restore_details  = dict(rv.iteritems())
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id, read_deleted="yes")
        restore_details.setdefault('workload_id', snapshot.workload_id)
        
        restore_details['snapshot_details'] = dict(snapshot.iteritems())
                
        instances = []
        try:
            vms = self.db.restored_vms_get(context, restore_id)
            for vm in vms:
                restored_vm = {'id': vm.vm_id, 
                               'name':vm.vm_name,
                               'time_taken' : vm.time_taken,
                               'status':vm.status,}
                metadata = {}
                for kvpair in vm.metadata:
                    metadata.setdefault(kvpair['key'], kvpair['value'])
                restored_vm['metadata'] = metadata                
                instances.append(restored_vm)
        except Exception as ex:
            pass
        restore_details.setdefault('instances', instances)    
        return restore_details

    #@autolog.log_method(logger=Logger, log_args=False, log_retval=False)
    def restore_show(self, context, restore_id):
        rv = self.db.restore_show(context, restore_id)
        restore_details  = dict(rv.iteritems())
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id, read_deleted="yes")
        restore_details.setdefault('workload_id', snapshot.workload_id)
        
        restore_details['snapshot_details'] = dict(snapshot.iteritems())
        instances = []
        try:
            vms = self.db.restored_vms_get(context, restore_id)
            for vm in vms:
                restored_vm = {'id': vm.vm_id, 
                               'name':vm.vm_name,
                               'status':vm.status,}
                metadata = {}
                for kvpair in vm.metadata:
                    metadata.setdefault(kvpair['key'], kvpair['value'])
                restored_vm['metadata'] = metadata                
                instances.append(restored_vm)
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
    
    @autolog.log_method(logger=Logger)
    def restore_get_all(self, context, snapshot_id=None):
        restores = self.db.restore_get_all(context, snapshot_id)
        return restores
    
    @autolog.log_method(logger=Logger)
    def restore_delete(self, context, restore_id):
        """
        Delete a workload restore. RPC call may be required
        """
        restore_details = self.restore_show(context, restore_id)
        AUDITLOG.log(context,'Restore Delete Requested', restore_details)
        
        if restore_details['target_platform'] == 'vmware':
            self.db.restore_delete(context, restore_id)
            AUDITLOG.log(context,'Restore Deleted', restore_details)
            return
            
        
        if restore_details['status'] not in ['available', 'error', 'cancelled']:
            msg = _("Status of the requested resource status must be 'available' or 'error' or 'cancelled'")
            raise wlm_exceptions.InvalidState(reason=msg)

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
        AUDITLOG.log(context,'Restore Deleted', restore_details)
       
    @autolog.log_method(logger=Logger)
    def restore_cancel(self, context, restore_id):
        """
        Make the RPC call to cancel restore
        """
        try:
            restore = self.db.restore_get(context, restore_id)
            if restore.status in ['available','cancelled','error']:
               return

            metadata = {}
            metadata.setdefault('cancel_requested','1')

            self.db.restore_update(context,
                                    restore_id,
                                    {
                                     'metadata': metadata,
                                     'status': 'cancelling'
                                    })

            #AUDITLOG.log(context,'Restore Cancel Requested', restore_id)

            return True

        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))
   
  
    @autolog.log_method(logger=Logger)
    def settings_create(self, context, settings):
        created_settings = []
        try:
            for setting in settings:
                created_settings.append(self.db.setting_create(context, setting))
        except Exception as ex:
            LOG.exception(ex)
        return created_settings 
    
    @autolog.log_method(logger=Logger)
    def settings_update(self, context, settings):
        updated_settings = []
        try:
            for setting in settings:
                updated_settings.append(self.db.setting_update(context, setting['name'], setting))
        except Exception as ex:
            LOG.exception(ex)
        return updated_settings
    
    @autolog.log_method(logger=Logger)
    def setting_delete(self, context, name):
        self.db.setting_delete(context,name)
                
    @autolog.log_method(logger=Logger)
    def setting_get(self, context, name, get_hidden = False):
        try:
            return self.db.setting_get(context, name, get_hidden = get_hidden)
        except Exception as ex:
            LOG.exception(ex)
        return None
        
    @autolog.log_method(logger=Logger)
    def settings_get(self, context, get_hidden = False):
        settings = []
        try:
            return self.db.setting_get_all(context, get_hidden = get_hidden)
        except Exception as ex:
            LOG.exception(ex)
        return settings 

    @autolog.log_method(logger=Logger)
    def task_show(self, context, task_id):

        task = self.db.task_get(context, task_id)
        task_dict = dict(task.iteritems())
        return task_dict  

      
