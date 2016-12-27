# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to the  workloadmgr service.
"""
import base64
import cPickle as pickle
import importlib
import json
import os
import socket
import threading
import time
import uuid
import zlib

from M2Crypto import DSA

from eventlet import greenthread

from datetime import datetime
from datetime import timedelta
from hashlib import sha1
from distutils import version
from sqlalchemy import create_engine

from operator import itemgetter, attrgetter

from oslo_config import cfg

from workloadmgr.common import clients
from workloadmgr.common import context as wlm_context
from workloadmgr.common import workloadmgr_keystoneclient
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import jsonutils

from workloadmgr.apscheduler.scheduler import Scheduler
from workloadmgr.apscheduler.jobstores.sqlalchemy_store import SQLAlchemyJobStore

from workloadmgr import utils
from workloadmgr.workloads import rpcapi as workloads_rpcapi
from workloadmgr.scheduler import rpcapi as scheduler_rpcapi
from workloadmgr.db import base
from workloadmgr import exception as wlm_exceptions
from workloadmgr import flags
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.image import glance
from workloadmgr import context
from workloadmgr.workflows import vmtasks
from workloadmgr.vault import vault
from workloadmgr.openstack.common import timeutils
from workloadmgr.workloads import workload_utils
from workloadmgr import auditlog
from workloadmgr import autolog
from workloadmgr import policy
from workloadmgr.db.sqlalchemy import models

workload_lock = threading.Lock()

FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)
AUDITLOG = auditlog.getAuditLogger()


#do not decorate this function with autolog
def _snapshot_create_callback(*args, **kwargs):
    try:
        arg_str = autolog.format_args(args, kwargs)
        LOG.info(_("_snapshot_create_callback Enter - " + arg_str))
    
        from workloadmgr.workloads import API
        workloadmgrapi = API()
 
        workload_id = kwargs['workload_id']
        user_id = kwargs['user_id']
        project_id = kwargs['project_id']
        tenantcontext = nova._get_tenant_context(kwargs)
    
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

        # 
        # if fullbackup_interval is -1, never take full backups
        # if fullbackup_interval is 0, always take full backups
        # if fullbackup_interval is +ve follow the interval
        #
        jobscheduler['fullbackup_interval'] = \
                       'fullbackup_interval' in jobscheduler and \
                       jobscheduler['fullbackup_interval'] or "-1"

        snapshot_type = "incremental"
        if int(jobscheduler['fullbackup_interval']) == 0:
            snapshot_type = "full"
        elif int(jobscheduler['fullbackup_interval']) < 0:
            snapshot_type = "incremental"
        elif int(jobscheduler['fullbackup_interval']) > 0:
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

        snapshot = workloadmgrapi.workload_snapshot(tenantcontext, workload_id, snapshot_type, "jobscheduler", None)
    except Exception as ex:
        LOG.exception(_("Error creating a snapshot for workload %s") % workload_id)

    LOG.info(_("_snapshot_create_callback Exit"))


def create_trust(func):
   def trust_create_wrapper(*args, **kwargs):
       # Clean up trust if the role is changed
       try:
           context = args[1]
           trusts = args[0].trust_list(context)
           for t in trusts:
               for meta in t.metadata:
                   if meta.key == "role_name":
                       if meta.value != vault.CONF.trustee_role:
                           args[0].trust_delete(context, t.name)

           # create new trust if the trust is not created
           if not args[0].trust_list(context):
               args[0].trust_create(context, vault.CONF.trustee_role)
       except Exception as ex:
           LOG.exception(ex)
           LOG.error(_("trust is not enabled. Falling back to old mechanism"))

       return func(*args, **kwargs)
   return trust_create_wrapper



def upload_settings(func):
   def upload_settings_wrapper(*args, **kwargs):
       # Clean up trust if the role is changed
       context = args[1]

       ret_val = func(*args, **kwargs)
       workload_utils.upload_settings_db_entry(context)
       return ret_val
   return upload_settings_wrapper


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, workload)
    """
    @functools.wraps(func)
    def wrapped(self, context, target_obj, *args, **kwargs):
        check_policy(context, func.__name__, target_obj)
        return func(self, context, target_obj, *args, **kwargs)

    return wrapped


def check_policy(context, action, target_obj=None):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }

    _action = 'workload:%s' % action
    policy.enforce(context, _action, target)


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

        super(API, self).__init__(db_driver)

        if not hasattr(self, "_scheduler"):
            self._scheduler = Scheduler()
            self._scheduler.add_jobstore(self._jobstore, 'jobscheduler_store')

            context = wlm_context.get_admin_context()
            self.workload_ensure_global_job_scheduler(context)

    
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
        AUDITLOG.log(context,'WorkloadType \'' + name + '\' Create Requested', None)
        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'id': id,
                   'display_name': name,
                   'display_description': description,
                   'is_public' : is_public,
                   'status': 'available',
                   'metadata': metadata,}

        workload_type = self.db.workload_type_create(context, options)
        AUDITLOG.log(context,'WorkloadType \'' + name + '\' Create Submitted', workload_type)
        return workload_type
    
    @autolog.log_method(logger=Logger)
    def workload_type_delete(self, context, workload_type_id):
        """
        Delete a workload_type. No RPC call is made
        """
        workload_type = self.workload_type_get(context, workload_type_id)
        AUDITLOG.log(context,'WorkloadType \'' + workload_type['display_name'] + '\' Delete Requested', workload_type)
        if workload_type['status'] not in ['available', 'error']:
            msg = _("WorkloadType status must be 'available' or 'error'")
            raise wlm_exceptions.InvalidState(reason=msg)

        #TODO(giri): check if this workload_type is referenced by other workloads
                    
        self.db.workload_type_delete(context, workload_type_id)
        AUDITLOG.log(context,'WorkloadType \'' + workload_type['display_name'] + '\' Delete Submitted', workload_type)
    
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
        kwargs = {}
        if context.is_admin is False:
            kwargs['project_only'] = 'yes'
        workload = self.db.workload_get(context, workload_id)
        workload_dict = dict(workload.iteritems())
        
        workload_dict['storage_usage'] = {'usage': 0, 
                                          'full': {'snap_count': 0, 'usage': 0}, 
                                          'incremental': {'snap_count': 0, 'usage': 0}
                                          }
        for workload_snapshot in self.db.snapshot_get_all_by_workload(context, workload_id, **kwargs):
            if workload_snapshot.data_deleted == False:
                if workload_snapshot.snapshot_type == 'incremental':
                    workload_dict['storage_usage']['incremental']['snap_count'] = workload_dict['storage_usage']['incremental']['snap_count'] + 1
                    workload_dict['storage_usage']['incremental']['usage'] = workload_dict['storage_usage']['incremental']['usage'] + workload_snapshot.size
                else:
                    workload_dict['storage_usage']['full']['snap_count'] = workload_dict['storage_usage']['full']['snap_count'] + 1
                    workload_dict['storage_usage']['full']['usage'] = workload_dict['storage_usage']['full']['usage'] + workload_snapshot.size
        workload_dict['storage_usage']['usage'] =  workload_dict['storage_usage']['full']['usage'] + workload_dict['storage_usage']['incremental']['usage']

 
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
        metadata['backup_media_target'] = metadata.get("backup_media_target", "NA")
        if context.is_admin is False:
            metadata.get("backup_media_target", None) and \
            metadata.pop("backup_media_target")
        workload_dict['metadata'] = metadata        
        
        workload_dict['jobschedule'] = pickle.loads(str(workload.jobschedule))
        workload_dict['jobschedule']['enabled'] = False
        workload_dict['jobschedule']['global_jobscheduler'] = self._scheduler.running
        # find the job object based on workload_id
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            if job.kwargs['workload_id'] == workload_id:
                workload_dict['jobschedule']['enabled'] = True
                break

        return workload_dict
    
    @autolog.log_method(logger=Logger)
    def workload_show(self, context, workload_id):
        kwargs = {}
        if context.is_admin is False:
            kwargs['project_only'] = 'yes'
        workload = self.db.workload_get(context, workload_id, **kwargs)
        workload_dict = dict(workload.iteritems())

        workload_dict['storage_usage'] = {'usage': 0, 
                                          'full': {'snap_count': 0, 'usage': 0}, 
                                          'incremental': {'snap_count': 0, 'usage': 0}
                                         }
       
        for workload_snapshot in self.db.snapshot_get_all_by_workload(context, workload_id, **kwargs):
            if workload_snapshot is None:
               msg = _("Not found any snapshots or operation not allowed")
               wlm_exceptions.ErrorOccurred(reason=msg)

            if workload_snapshot.data_deleted == False:
                if workload_snapshot.snapshot_type == 'incremental':
                    workload_dict['storage_usage']['incremental']['snap_count'] = workload_dict['storage_usage']['incremental']['snap_count'] + 1
                    workload_dict['storage_usage']['incremental']['usage'] = workload_dict['storage_usage']['incremental']['usage'] + workload_snapshot.size
                else:
                    workload_dict['storage_usage']['full']['snap_count'] = workload_dict['storage_usage']['full']['snap_count'] + 1
                    workload_dict['storage_usage']['full']['usage'] = workload_dict['storage_usage']['full']['usage'] + workload_snapshot.size
        workload_dict['storage_usage']['usage'] =  workload_dict['storage_usage']['full']['usage'] + workload_dict['storage_usage']['incremental']['usage']
                
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

        metadata['backup_media_target'] = metadata.get("backup_media_target", "NA")
        if context.is_admin is False:
            metadata.get("backup_media_target", None) and \
            metadata.pop("backup_media_target")
        workload_dict['metadata'] = metadata
        workload_dict['jobschedule'] = pickle.loads(str(workload.jobschedule))
        workload_dict['jobschedule']['enabled'] = False 
        workload_dict['jobschedule']['global_jobscheduler'] = self._scheduler.running
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
        workloads = self.db.workload_get_all(context,**search_opts)
        return workloads

    @autolog.log_method(logger=Logger)
    @create_trust
    def workload_create(self, context, name, description, workload_type_id,
                        source_platform, instances, jobschedule, metadata,
                        availability_zone=None):
        """
        Make the RPC call to create a workload.
        """
        try:
            AUDITLOG.log(context,'Workload \'' + name + '\' Create Requested', None)
            compute_service = nova.API(production=True)
            instances_with_name = compute_service.get_servers(context)
            instance_ids = map(lambda x: x.id, instances_with_name)
            workload = None
            #TODO(giri): optimize this lookup

            if len(instances) == 0:
                raise wlm_exceptions.InvalidRequest(reason="No instances found in the workload create request")

            for instance in instances:
                #Check whether given instance id exist or not.
                if not instance_ids or instance['instance-id'] not in instance_ids:
                   raise wlm_exceptions.InstanceNotFound(instance_id=instance['instance-id'])
                for instance_with_name in instances_with_name:
                    if instance_with_name.tenant_id != context.project_id:
                        msg = _('Invalid instance as '+instance_with_name.name+' is not associated with your current tenant')
                        raise wlm_exceptions.Invalid(reason=msg)
                    if instance['instance-id'] == instance_with_name.id:
                        vm_found = self.db.workload_vm_get_by_id(context, instance_with_name.id)
                        if isinstance(vm_found, list):
                            if len(vm_found) > 0:
                               msg = _('Invalid instance as '+instance_with_name.name+' already attached with other workload')
                               raise wlm_exceptions.Invalid(reason=msg)
                        else:
                              msg = _('Error processing instance'+instance_with_name.name)
                              raise wlm_exceptions.Invalid(reason=msg)
                        instance['instance-name'] = instance_with_name.name
                        if instance_with_name.metadata:
                            instance['metadata'] = instance_with_name.metadata
                            if 'imported_from_vcenter' in instance_with_name.metadata and \
                                instances_with_name[0].metadata['imported_from_vcenter'] == 'True':
                                source_platform = "vmware"
                        break
        
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
            #                              'retention_policy_type': 'Number of Snapshots to Keep',
            #                              'retention_policy_value': '30'}
            try:
                self.workload_add_scheduler_job(jobschedule, workload, context)
            except Exception as ex:
                LOG.exception(ex)    
                
            AUDITLOG.log(context, 'Workload \'' + workload['display_name'] + '\' Create Submitted', workload)        
            return workload
        except Exception as ex:
            LOG.exception(ex)
            if workload:
               self.db.workload_update(context, workload['id'],
                                      {'status': 'error',
                                       'error_msg': str(ex.message)})
            raise
    
    @autolog.log_method(logger=Logger)
    def workload_add_scheduler_job(self, jobschedule, workload, context=context):
        if jobschedule and len(jobschedule): 
            if 'enabled' in jobschedule and jobschedule['enabled']:                                       
                if hasattr(context, 'user_domain_id'):
                   if context.user_domain_id is None:
                      user_domain_id = 'default'
                   else:
                        user_domain_id = context.user_domain_id
                elif hasattr(context, 'user_domain'):
                     if context.user_domain is None:
                        user_domain_id = 'default'
                     else:
                          user_domain_id = context.user_domain
                else:
                     user_domain_id = 'default'
                self._scheduler.add_workloadmgr_job(_snapshot_create_callback, 
                                                    jobschedule,
                                                    jobstore='jobscheduler_store', 
                                                    kwargs={'workload_id':workload.id,  
                                                            'user_id': workload.user_id, 
                                                            'project_id':workload.project_id,
                                                            'user_domain_id':user_domain_id,
                                                            'user':context.user,
                                                            'tenant':context.tenant})

    @autolog.log_method(logger=Logger)
    def workload_modify(self, context, workload_id, workload):
        """
        Make the RPC call to modify a workload.
        """
        workloadobj = self.workload_get(context, workload_id)
        AUDITLOG.log(context,'Workload \'' + workloadobj['display_name'] + '\' Modify Requested', None)
   
        purge_metadata = False
        options = {}

        if 'name' in workload and workload['name']:
            options['display_name'] = workload['name']

        if 'description' in workload and workload['description']:
            options['display_description'] = workload['description']  

        if 'metadata' in workload and workload['metadata']:
            purge_metadata = True
            options['metadata'] = workload['metadata']     

        if 'jobschedule' in workload and workload['jobschedule'] and self._scheduler.running:
            options['jobschedule'] = pickle.dumps(workload['jobschedule'], 0)    

        if  'instances' in workload and workload['instances']:

            compute_service = nova.API(production=True)
            instances = workload['instances']
            instances_with_name = compute_service.get_servers(context)
            for instance in instances:
                if not isinstance(instance, dict) or\
                   not 'instance-id' in instance:

                    msg = _("Workload definition key 'instances' must be a dictionary "
                            "with 'instance-id' key")
                    raise wlm_exceptions.Invalid(reason=msg)
        
                found = False
                for existing_instance in instances_with_name:
                    if existing_instance.tenant_id != context.project_id:
                        msg = _('Invalid instance as '+existing_instance.name+' is not associated with your current tenant')
                        raise wlm_exceptions.Invalid(reason=msg)
                    if instance['instance-id'] == existing_instance.id:
                        vm_found = self.db.workload_vm_get_by_id(context, existing_instance.id)
                        if isinstance(vm_found, list):
                            if len(vm_found) > 0 and \
                                vm_found[0].workload_id != workload_id:
                               msg = _("Invalid instance as " + \
                                        existing_instance.name+\
                                       " already part of workload '%s'" % 
                                       (vm_found[0].workload_id))
                               raise wlm_exceptions.Invalid(reason=msg)
                        else:
                              msg = _('Error processing instance'+existing_instance.name)
                              raise wlm_exceptions.Invalid(reason=msg)

                        instance['instance-name'] = existing_instance.name  
                        instance['metadata'] = existing_instance.metadata
                        found = True
                        break

                if not found:
                    msg = _("Workload definition contains instance id that cannot be "
                            "found in the cloud")
                    raise wlm_exceptions.Invalid(reason=msg)

            for vm in self.db.workload_vms_get(context, workload_id):
                compute_service.delete_meta(context, vm.vm_id,
                                      ['workload_id', 'workload_name'])
                self.db.workload_vms_delete(context, vm.vm_id, workload_id) 

            for instance in instances:
                values = {'workload_id': workload_id,
                          'vm_id': instance['instance-id'],
                          'metadata': instance['metadata'],
                          'status': 'available',
                          'vm_name': instance['instance-name']}
                vm = self.db.workload_vms_create(context, values)
                compute_service.set_meta_item(context, vm.vm_id, 'workload_id', workload_id)
                compute_service.set_meta_item(context, vm.vm_id,
                                        'workload_name', workloadobj['display_name'] )

        workload_obj = self.db.workload_update(context, workload_id, options, purge_metadata)

        workload_utils.upload_workload_db_entry(context, workload_id)
            
        AUDITLOG.log(context,'Workload \'' + workload_obj['display_name'] + '\' Modify Submitted', workload_obj)
            
    @autolog.log_method(logger=Logger)
    def workload_delete(self, context, workload_id):
        """
        Delete a workload. No RPC call is made
        """
        try:
            workload = self.workload_get(context, workload_id)
            display_name = workload['display_name']
            AUDITLOG.log(context,'Workload \'' + display_name + '\' Delete Requested', workload)
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
            self.db.workload_update(context, workload_id, {'status': 'deleting'}) 
            self.workloads_rpcapi.workload_delete(context, workload['host'], workload_id)
            AUDITLOG.log(context,'Workload \'' + display_name + '\' Delete Submitted', workload)
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))         

    @autolog.log_method(logger=Logger)
    def workload_reset(self, context, workload_id):
        """
        Reset a workload. When a workload is reset, any overlay files that were
        created as part of the snapshot operation are commited back to original
        files
        """
        try:
            workload = self.workload_get(context, workload_id)
            display_name = workload['display_name']
            AUDITLOG.log(context,'Workload \'' + display_name + '\' Reset Requested', workload)
            if workload['status'] not in ['available', 'resetting']:
                msg = _("Workload status must be 'available'")
                raise wlm_exceptions.InvalidState(reason=msg)

            self.db.workload_update(context, workload_id, {'status': 'resetting'})
            self.workloads_rpcapi.workload_reset(context, workload['host'], workload_id)
            AUDITLOG.log(context,'Workload \'' + display_name + '\' Reset Submitted', workload)
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))         
   
    @autolog.log_method(logger=Logger)
    def get_import_workloads_list(self, context):
        AUDITLOG.log(context,'Get Import Workloads List Requested', None)
        if context.is_admin == False:
            raise wlm_exceptions.AdminRequired()

        workloads = []
        for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
            vault.get_backup_target(backup_endpoint)
        for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
            backup_target = None
            try:
                backup_target = vault.get_backup_target(backup_endpoint)
                for workload_url in backup_target.get_workloads(context):
                    try:
                        workload_values = json.loads(backup_target.get_object(
                            os.path.join(workload_url, 'workload_db')))
                        workloads.append(workload_values)

                    except Exception as ex:
                        LOG.exception(ex)
                        continue
            except Exception as ex:
                LOG.exception(ex)
            finally:
                backup_target.purge_staging_area(context)

        AUDITLOG.log(context,'Get Import Workloads List Completed', None)
        return workloads
   
    @autolog.log_method(logger=Logger)    
    def import_workloads(self, context, workload_ids, upgrade):

        AUDITLOG.log(context,'Import Workloads Requested', None)        
        if context.is_admin is not True and upgrade is True:
            raise wlm_exceptions.AdminRequired()

        try:
            workloads = []
            # call get_backup_target that makes sure all shares are mounted
            for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
                vault.get_backup_target(backup_endpoint)

            module_name = 'workloadmgr.db.imports.import_workload_' +\
                           models.DB_VERSION.replace('.', '_')
            import_workload_module = importlib.import_module(module_name)
            import_settings_method = getattr(import_workload_module,
                                             'import_settings')
            import_settings_method(context, models.DB_VERSION)

            #TODO:Need to make this call to a single import module instead of 
            #looking for new import module for each new build.
            import_workload_module = importlib.import_module(
                  'workloadmgr.db.imports.import_workload_' +
                   models.DB_VERSION.replace('.', '_'))
            import_workload_method = getattr(import_workload_module, 'import_workload')

            workloads = import_workload_method(context, workload_ids,
                                               models.DB_VERSION,
                                               upgrade)
        except Exception as ex:
            LOG.exception(ex)

        AUDITLOG.log(context,'Import Workloads Completed', None)
        return workloads


    @autolog.log_method(logger=Logger)
    def get_nodes(self, context):
        nodes = []
        try:
            for node_record in self.db.service_get_all_by_topic(context, topic='workloadmgr-workloads'):
                try:
                    status = 'Up'
                    if not utils.service_is_up(node_record) or node_record['disabled']:
                       status = 'Down'
                    ipaddress = ''
                    ip_addresses = node_record.ip_addresses.split(';')
                    if len(node_record.ip_addresses) > 0 and len(node_record.ip_addresses[0]) > 0:
                        ipaddress = ip_addresses[0]
                    is_controller = False
                    if socket.gethostname() == node_record.host:
                       is_controller = True
                    nodes.append({'node':node_record.host, 
                                  'id': node_record.id,
                                  'version':node_record.version, 
                                  'ipaddress': ipaddress,
                                  'is_controller': is_controller,
                                  'status': status})
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
            raise ex

    @autolog.log_method(logger=Logger)
    def get_contego_status(self, context, host=None, ip=None):
        try:   
            compute_service = nova.API(production=True)           
            compute_contego_records = compute_service.contego_service_status(context, host, ip)            
            return compute_contego_records
        except Exception as ex:
            LOG.exception(ex)
            raise ex      
            
    @autolog.log_method(logger=Logger)
    def add_node(self, context, ip):
        try:
            for node_record in self.db.service_get_all_by_topic(context, topic='workloadmgr-workloads'):
                try:
                    ipaddress = ''
                    ip_addresses = node_record.ip_addresses.split(';')
                    if len(node_record.ip_addresses) > 0 and len(node_record.ip_addresses[0]) > 0:
                        ipaddress = ip_addresses[0]
                    if socket.gethostname() == node_record.host:
                       controller_ip = ipaddress
                    if any([ipaddress == ip , node_record.host == ip]):
                       msg = _("Other node with same ip addresss exists")
                       raise wlm_exceptions.ErrorOccurred(reason=msg)
                except Exception as ex:
                    LOG.exception(ex)
                    raise ex
            import subprocess           
            file_name = context.user_id+'.txt'
            command = ['sudo', 'curl', '-k', '--cookie-jar', file_name, '--data', "username=admin&password=password", "https://"+ip+"/login"];
            try:
                res = subprocess.check_output(command)
            except Exception as ex:
                   msg = _("Error resolving "+ip)
                   raise wlm_exceptions.ErrorOccurred(reason=msg)                    
            subprocess.call(command, shell=False)                      
            config_inputs = {}
            for setting in self.db.setting_get_all_by_project(context, "Configurator"):
                config_inputs[setting.name] = setting.value
            if not config_inputs:
               msg = _("No configurations found")
               raise wlm_exceptions.ErrorOccurred(reason=msg)                 
            command = ['sudo', 'curl', '-k', '--cookie', file_name, '--data', "refresh=1&from=api&tvault-primary-node="+controller_ip+"&nodetype=additional", "https://"+ip+"/configure_vmware"];
            subprocess.call(command, shell=False)
            urls = ['configure_host','authenticate_with_vcenter','authenticate_with_swift','register_service','configure_api','configure_scheduler','configure_service','start_api','start_scheduler','start_service','register_workloadtypes','workloads_import','discover_vcenter','ntp_setup']
            if len(config_inputs['swift_auth_url']) == 0:
               urls.remove('authenticate_with_swift')
            if config_inputs['import_workloads'] == 'off':
               urls.remove('workloads_import') 
            if config_inputs['ntp_enabled'] == 'off':
               urls.remove('ntp_setup') 
            for url in urls:
                command = ['sudo', 'curl', '-k', '--cookie', file_name,  "https://"+ip+"/"+url];
                res = subprocess.check_output(command)          
                if res != '{"status": "Success"}' and url != 'ntp_setup':
                   command = ['sudo', 'rm', '-rf', file_name];
                   subprocess.call(command, shell=False)         
                   msg = _(res) 
                   raise wlm_exceptions.ErrorOccurred(reason=msg) 
            command = ['sudo', 'rm', '-rf', file_name];
            subprocess.call(command, shell=False)

        except Exception as ex:
            LOG.exception(ex)
            raise ex
 
    @autolog.log_method(logger=Logger)
    def get_storage_usage(self, context):

        if context.is_admin is False:
            raise wlm_exceptions.AdminRequired()

        storages_usage = {}
        total_usage = 0
        nfsstats = vault.get_capacities_utilizations(context)
        for nfsshare in vault.CONF.vault_storage_nfs_export.split(','):
            stat = nfsstats[nfsshare]

            total_capacity = stat['total_capacity']
            total_utilization = stat['total_utilization']
            nfsstatus = stat['nfsstatus']

            storages_usage[nfsshare]  = {'storage_type': vault.CONF.vault_storage_type,
                                         'nfs_share(s)': [
                                          {
                                            "nfsshare": nfsshare,
                                            "status":  "Online" if nfsstatus else "Offline",
                                            "capacity": utils.sizeof_fmt(total_capacity),
                                            "utilization": utils.sizeof_fmt(total_utilization),
                                          },
                                         ],
                                         'total': 0,
                                         'full': 0,
                                         'incremental': 0,
                                         'total_capacity': total_capacity,
                                         'total_utilization': total_utilization,
                                         'total_capacity_humanized':
                                             utils.sizeof_fmt(total_capacity),
                                         'total_utilization_humanized' :
                                             utils.sizeof_fmt(total_utilization),
                                         'available_capacity_humanized':
                                             utils.sizeof_fmt(float(total_capacity)
                                                              - float(total_utilization)),
                                         'total_utilization_percent'   :
                                             round(((float(total_utilization)
                                                     / float(total_capacity)) * 100), 2),
                                        }
        storage_usage = {'storage_usage': storages_usage.values(), 'count_dict':{}} 
        full = 0
        incr = 0
        total = 0
        full_size = 0
        incr_size = 0 
        kwargs = {"get_all":True}
        for snapshot in self.db.snapshot_get_all(context, **kwargs):
            if snapshot.snapshot_type == 'full':
               full = full + 1
               full_size = full_size + float(snapshot.size)
            elif snapshot.snapshot_type == 'incremental':
                 incr = incr + 1
                 incr_size = incr_size + float(snapshot.size)
            total = total + 1    

        if (full + incr) > 0:
           full_total_count_percent = \
               round(((float(full) / float((full  + incr))) * 100), 2)
           storage_usage['count_dict']['full_total_count_percent'] = \
                str(full_total_count_percent)
           storage_usage['count_dict']['full_total_count'] = str(full)
           storage_usage['count_dict']['incr_total_count'] = str(incr)

        storage_usage['count_dict']['full'] = full_size
        storage_usage['count_dict']['incremental'] = incr_size
        storage_usage['count_dict']['total'] = full_size + incr_size
        if float(total_usage) > 0:
           storage_usage['count_dict']['full_snaps_utilization'] = \
               round(((float(full_size) / float(total_usage)) * 100), 2)
           storage_usage['count_dict']['incremental_snaps_utilization'] = \
               round(((float(incr) / float(total_usage)) * 100), 2)
        else:
             storage_usage['count_dict']['full_snaps_utilization'] = '0'
             storage_usage['count_dict']['incremental_snaps_utilization'] = '0'
        return storage_usage
    
    @autolog.log_method(logger=Logger)
    def get_recentactivities(self, context, time_in_minutes):
        recentactivites = []
        now = timeutils.utcnow()
        time_offset = datetime.now() - datetime.utcnow()
        try:
            for workload in self.db.workload_get_all(
                        context,
                        read_deleted = 'yes',
                        dashboard_item = 'activities',
                        time_in_minutes = time_in_minutes
                    ):
                recentactivity = { 'activity_type'       :'',
                                   'activity_time'       :'',
                                   'activity_description':'',
                                   'activity_result'     :workload.status,
                                   'object_type'         :'workload',
                                   'object_name'         :workload.display_name,
                                   'object_id'           :workload.id,
                                   'object_user_id'      :workload.user_id,
                                   'object_project_id'   :workload.project_id,
                                }
                description_suffix = \
                    "(Workload: '%s' - '%s')" % \
                        (workload.display_name,
                        (workload.created_at + time_offset).
                                            strftime("%m/%d/%Y %I:%M %p"))
                if workload.deleted:
                    recentactivity['activity_type'] = 'delete'
                    recentactivity['activity_time'] = workload.deleted_at
                    recentactivity['activity_description'] = \
                                "Workload deleted. " + description_suffix
                else:
                    recentactivity['activity_type'] = 'create'
                    recentactivity['activity_time'] = workload.created_at
                    if workload.status == 'error':
                        recentactivity['activity_description'] = \
                                "Workload failed. " + description_suffix
                    else:
                        recentactivity['activity_description'] = \
                                "Workload created. " + description_suffix
                recentactivites.append(recentactivity)

            for snapshot in self.db.snapshot_get_all(
                                    context,
                                    read_deleted = 'yes',
                                    dashboard_item = 'activities',
                                    time_in_minutes = time_in_minutes):
                recentactivity = { 'activity_type'       :'',
                                   'activity_time'       :'',
                                   'activity_description':'',
                                   'activity_result'     :snapshot.status,
                                   'object_type'         :'snapshot',
                                   'object_name'         :snapshot.display_name,
                                   'object_id'           :snapshot.id,
                                   'object_user_id'      :snapshot.user_id,
                                   'object_project_id'   :snapshot.project_id,
                               }
                description_suffix = \
                    "(Snapshot: '%s' - '%s', Workload: '%s' - '%s')" % \
                        (snapshot.display_name,
                         (snapshot.created_at + time_offset). \
                                            strftime("%m/%d/%Y %I:%M %p"),
                         snapshot.workload_name,
                         (snapshot.workload_created_at + time_offset). \
                                            strftime("%m/%d/%Y %I:%M %p") )
                if snapshot.deleted:
                    recentactivity['activity_type'] = 'delete'
                    recentactivity['activity_time'] = snapshot.deleted_at
                    recentactivity['activity_description'] = \
                                "Snapshot deleted. " + description_suffix
                else:
                    recentactivity['activity_type'] = 'create'
                    recentactivity['activity_time'] = snapshot.created_at
                    if snapshot.status == 'error':
                        recentactivity['activity_description'] = \
                                "Snapshot failed. " + description_suffix
                    elif snapshot.status == 'available':
                        recentactivity['activity_description'] = \
                                "Snapshot created. " + description_suffix
                    elif snapshot.status == 'cancelled':
                        recentactivity['activity_type'] = 'cancel'
                        recentactivity['activity_description'] = \
                                "Snapshot cancelled. " + description_suffix
                    else:
                        recentactivity['activity_description'] = \
                                "Snapshot is in progress. " + description_suffix
                recentactivites.append(recentactivity)

            for restore in self.db.restore_get_all(
                                context,
                                read_deleted = 'yes',
                                dashboard_item = 'activities',
                                time_in_minutes = time_in_minutes):
                recentactivity = { 'activity_type'       :'',
                                   'activity_time'       :'',
                                   'activity_description':'',
                                   'activity_result'     :restore.status,
                                   'object_type'         :'restore',
                                   'object_name'         :restore.display_name,
                                   'object_id'           :restore.id,
                                   'object_user_id'      :restore.user_id,
                                   'object_project_id'   :restore.project_id,
                                   }
                description_suffix = \
                    "(Restore: '%s' - '%s', Snapshot: '%s' - '%s', Workload: '%s' - '%s')" % \
                        (restore.display_name,
                         (restore.created_at + time_offset). \
                                            strftime("%m/%d/%Y %I:%M %p"),
                         restore.snapshot_name,
                         (restore.snapshot_created_at + time_offset). \
                                            strftime("%m/%d/%Y %I:%M %p"),
                         restore.workload_name,
                         (restore.workload_created_at + time_offset). \
                                            strftime("%m/%d/%Y %I:%M %p") )
                if restore.deleted:
                    recentactivity['activity_type'] = 'delete'
                    recentactivity['activity_time'] = snapshot.deleted_at
                    recentactivity['activity_description'] = \
                                "Restore deleted. "  + description_suffix
                else:
                    recentactivity['activity_type'] = 'create'
                    recentactivity['activity_time'] = restore.created_at
                    if restore.status == 'error':
                        recentactivity['activity_description'] = \
                                "Restore failed. " + description_suffix
                    elif restore.status == 'available':
                        recentactivity['activity_description'] = \
                                "Restore completed. " + description_suffix
                    elif restore.status == 'cancelled':
                        recentactivity['activity_type'] = 'cancel'
                        recentactivity['activity_description'] = \
                                "Restore Cancelled. " + description_suffix
                    else:
                        recentactivity['activity_description'] = \
                                "Restore is in progress. " + description_suffix
                recentactivites.append(recentactivity)

            recentactivites = sorted(recentactivites,
                                    key = itemgetter('activity_time'),
                                    reverse = True)
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
        if self._scheduler.running is True:
           workload = self.workload_get(context, workload_id)
           AUDITLOG.log(context,'Workload \'' + workload['display_name'] + '\' Pause Requested', workload)
           jobs = self._scheduler.get_jobs()
           for job in jobs:
               if job.kwargs['workload_id'] == workload_id:
                  self._scheduler.unschedule_job(job)
                  break
           AUDITLOG.log(context,'Workload \'' + workload['display_name'] + '\' Pause Submitted', workload)
            

    @autolog.log_method(logger=Logger)
    def workload_resume(self, context, workload_id):
        if self._scheduler.running is True:
           workload = self.db.workload_get(context, workload_id)
           AUDITLOG.log(context,'Workload \'' + workload['display_name'] + '\' Resume Requested', workload)
           jobs = self._scheduler.get_jobs()
           for job in jobs:
               if job.kwargs['workload_id'] == workload_id:
                  msg = _('Workload job scheduler is not paused')
                  raise wlm_exceptions.InvalidState(reason=msg)
           jobschedule = pickle.loads(str(workload['jobschedule']))
           if len(jobschedule) >= 1:
              self.workload_add_scheduler_job(jobschedule, workload, context)
           AUDITLOG.log(context,'Workload \'' + workload['display_name'] + '\' Resume Submitted', workload)

    @autolog.log_method(logger=Logger)
    def workload_unlock(self, context, workload_id):
        workload = self.workload_get(context, workload_id)
        display_name = workload['display_name']
        AUDITLOG.log(context,'Workload \'' + display_name + '\' Unlock Requested', workload)
        if not workload['deleted']:
            self.db.workload_update(context, workload_id, {'status': 'available'})         
        AUDITLOG.log(context,'Workload \'' + display_name + '\' Unlock Submitted', workload)

    @autolog.log_method(logger=Logger)
    @upload_settings
    def workload_disable_global_job_scheduler(self, context):

        if context.is_admin is False:
            raise wlm_exceptions.AdminRequired()

        if self._scheduler.running is False:
            # scheduler is already stopped. Nothing to do
            return

        self._scheduler.shutdown()

        setting = {u'category': "job_scheduler",
                   u'name': "global-job-scheduler",
                   u'description': "Controls job scheduler status",
                   u'value': False,
                   u'user_id': context.user_id,
                   u'is_public': False,
                   u'is_hidden': True,
                   u'metadata': {},
                   u'type': "job-scheduler-setting",}

        try:
            try:
                self.db.setting_get(context, setting['name'])
                self.db.setting_update(context, setting['name'], setting)
            except wlm_exceptions.SettingNotFound:
                self.db.setting_create(context, setting)

        except Exception as ex:
            LOG.exception(ex)
            raise Exception("Cannot disable job scheduler globally")

    @autolog.log_method(logger=Logger)
    @upload_settings
    def workload_enable_global_job_scheduler(self, context):

        if context.is_admin is False:
            raise wlm_exceptions.AdminRequired()

        if self._scheduler.running is True:
            # scheduler is already running. Nothing to do
            return

        self._scheduler = Scheduler()
        self._scheduler.add_jobstore(self._jobstore, 'jobscheduler_store')
        self._scheduler.start()
        setting = {u'category': "job_scheduler",
                   u'name': "global-job-scheduler",
                   u'description': "Controls job scheduler status",
                   u'value': True,
                   u'user_id': context.user_id,
                   u'is_public': False,
                   u'is_hidden': True,
                   u'metadata': {},
                   u'type': "job-scheduler-setting",}
        try:
            try:
                self.db.setting_get(context, setting['name'])
                self.db.setting_update(context, setting['name'], setting)
            except wlm_exceptions.SettingNotFound:
                self.db.setting_create(context, setting)

        except Exception as ex:
            LOG.exception(ex)
            raise Exception("Cannot enable job scheduler globally")

    @autolog.log_method(logger=Logger)
    def workload_get_global_job_scheduler(self, context):
        return self._scheduler.running

    @autolog.log_method(logger=Logger)
    def workload_ensure_global_job_scheduler(self, context):

        if context.is_admin is False:
            raise wlm_exceptions.AdminRequired()

        try:
            global_scheduler = [sch for sch in self.db.setting_get_all(context) if sch['name'] == 'global-job-scheduler']
            if len(global_scheduler) == 0 or global_scheduler[0]['value'] == '1':
                self._scheduler.start()
            else:
                self._scheduler.shutdown()
        except wlm_exceptions.SettingNotFound:
            self._scheduler.start()
        except Exception as ex:
            LOG.exception(ex)

    @autolog.log_method(logger=Logger)
    @create_trust
    def workload_snapshot(self, context, workload_id, snapshot_type, name, description):

        """
        Make the RPC call to snapshot a workload.
        """
        try:
            workload = self.workload_get(context, workload_id)
            snapshot_display_name = ''
            if name and len(name) > 0:
                snapshot_display_name = '\'' + name + '\''
            else:
                snapshot_display_name = '\'' + 'Undefined' + '\''
            AUDITLOG.log(context,'Workload \'' + workload['display_name'] + '\' ' + snapshot_type + ' Snapshot ' + snapshot_display_name + ' Create Requested', workload)
        
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
            snapshot_display_name = snapshot['display_name']
            if snapshot_display_name ==  'User-Initiated' or snapshot_display_name == 'jobscheduler':
                local_time = self.get_local_time(context, snapshot['created_at']) 
                snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'
            AUDITLOG.log(context,'Workload \'' + workload['display_name'] +\
                         '\' ' + snapshot['snapshot_type'] + ' Snapshot \'' +\
                         snapshot_display_name + '\' Create Submitted', workload)

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
        rv = self.db.snapshot_get(context, snapshot_id, project_only='yes')
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
                         
        rv = self.db.snapshot_show(context, snapshot_id, project_only='yes')
        if rv is None:
           msg = _("Not found snapshot or operation not allowed")
           wlm_exceptions.ErrorOccurred(reason=msg)

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
                snapshot_vm['nics'] = []
                snapshot_vm['vdisks'] = []
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
                    """ security group """
                    if snapshot_vm_resource.resource_type == 'security_group':
                        snapshot_vm['security_group'] = {'name' : self.db.get_metadata_value(snapshot_vm_resource.metadata, 'name'),
                                                         'security_group_type' : self.db.get_metadata_value(snapshot_vm_resource.metadata, 'security_group_type'),
                                                        }
                    """ nics """
                    if snapshot_vm_resource.resource_type == 'nic':
                        vm_nic_snapshot = self.db.vm_network_resource_snap_get(context, snapshot_vm_resource.id)
                        nic_data = pickle.loads(str(vm_nic_snapshot.pickle))
                        nic = {'mac_address': nic_data['mac_address'],
                               'ip_address': nic_data['ip_address'],}
                        nic['network'] = {'id': self.db.get_metadata_value(vm_nic_snapshot.metadata, 'network_id'),
                                          'name': self.db.get_metadata_value(vm_nic_snapshot.metadata, 'network_name'),
                                          'cidr':nic_data.get('cidr', None),
                                          'network_type':nic_data['network_type']}
                        
                        pit_id = _get_pit_resource_id(vm_nic_snapshot.metadata, 'subnet_id')                        
                        if pit_id:
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
                        vdisk = {
                           'label': self.db.get_metadata_value(snapshot_vm_resource.metadata,'label'),
                           'resource_id': snapshot_vm_resource.id,
                           'restore_size': snapshot_vm_resource.restore_size,
                           'vm_id': snapshot_vm_resource.vm_id
                        }
                        if self.db.get_metadata_value(snapshot_vm_resource.metadata,'image_id'):
                           vdisk['image_id'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'image_id')
                           vdisk['image_name'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'image_name')
                           vdisk['hw_qemu_guest_agent'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'hw_qemu_guest_agent')
                        else:
                           vdisk['volume_id'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'volume_id')
                           vdisk['volume_name'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'volume_name')
                           vdisk['volume_size'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'volume_size')
                           vdisk['volume_type'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'volume_type')
                           vdisk['volume_mountpoint'] = self.db.get_metadata_value(snapshot_vm_resource.metadata,'volume_mountpoint')

                        snapshot_vm['vdisks'].append(vdisk)
                snapshot_vms.append(snapshot_vm)

        except Exception as ex:
            LOG.exception(ex)

        snapshot_details['instances'] = snapshot_vms    
        return snapshot_details
    
    @autolog.log_method(logger=Logger)
    def snapshot_get_all(self, context, search_opts={}):
        snapshots = self.db.snapshot_get_all(context, **search_opts)
        return snapshots

    @autolog.log_method(logger=Logger)
    def snapshot_delete(self, context, snapshot_id):
        """
        Delete a workload snapshot. No RPC call required
        """
        try:
            snapshot = self.snapshot_get(context, snapshot_id)
            workload = self.workload_get(context, snapshot['workload_id'])
            snapshot_display_name = snapshot['display_name']
            if snapshot_display_name == 'User-Initiated' or snapshot_display_name == 'jobscheduler':
                local_time = self.get_local_time(context, snapshot['created_at']) 
                snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'
            snapshot_snapshot_type = snapshot['snapshot_type']
            workload_display_name = workload['display_name']
            AUDITLOG.log(context,'Workload \'' + workload_display_name + '\' ' + snapshot_snapshot_type + ' Snapshot \'' + snapshot_display_name + '\' Delete Requested', snapshot)
            
            if snapshot['status'] not in ['available', 'error', 'cancelled']:
                msg = _("Snapshot status must be 'available' or 'error' or 'cancelled'")
                raise wlm_exceptions.InvalidState(reason=msg)
            
            try:
                workload_lock.acquire()
                if workload['status'].lower() != 'available' and workload['status'].lower() != 'locked_for_delete':
                    msg = _("Workload must be in the 'available' state to delete a snapshot")
                    raise wlm_exceptions.InvalidState(reason=msg)
                self.db.workload_update(context, snapshot['workload_id'], {'status': 'locked_for_delete'})
            finally:
                workload_lock.release()                    
            

            restores = self.db.restore_get_all_by_project_snapshot(context, context.project_id, snapshot_id)
            for restore in restores:
                if restore.restore_type == 'test':
                    msg = _('This workload snapshot contains testbubbles')
                    raise wlm_exceptions.InvalidState(reason=msg)      

            self.db.snapshot_update(context, snapshot_id, {'status': 'deleting'})

            status_messages = {'message': 'Snapshot delete operation starting'} 
            options = {
                       'display_name': "Snapshot Delete",
                       'display_description': "Snapshot delete for snapshot id %s" % snapshot_id,
                       'status': "starting",
                       'status_messages':  status_messages,
                      }

            task = self.db.task_create(context, options)
 
            self.workloads_rpcapi.snapshot_delete(context, workload['host'], snapshot_id, task.id)
            AUDITLOG.log(context,'Workload \'' + workload_display_name + '\' ' + snapshot_snapshot_type + ' Snapshot \'' + snapshot_display_name + '\' Delete Submitted', snapshot)

            return task.id
            
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {})) 
        
    @autolog.log_method(logger=Logger)
    @create_trust
    def snapshot_restore(self, context, snapshot_id, test, name, description, options):

        """
        Make the RPC call to restore a snapshot.
        """
        try:
            snapshot = self.snapshot_get(context, snapshot_id)
            workload = self.workload_get(context, snapshot['workload_id'])
            workload_display_name = workload['display_name']
            snapshot_display_name = snapshot['display_name']
            snapshot_snapshot_type = snapshot['snapshot_type']
            if snapshot_display_name == 'User-Initiated' or snapshot_display_name == 'jobscheduler':
                local_time = self.get_local_time(context, snapshot['created_at'])
                snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'
            restore_display_name = ''

            if not name or len(name) == 0:
                name = 'Undefined'
            restore_display_name = '\'' + name + '\''
            AUDITLOG.log(context,'Workload \'' + workload_display_name + '\' ' + \
                         snapshot_snapshot_type + ' Snapshot \'' + \
                         snapshot_display_name + '\' Restore \'' + \
                         restore_display_name + '\' Create Requested', snapshot)

            try:
                workload_lock.acquire()
                if workload['status'].lower() != 'available':
                    msg = _("Workload must be in the 'available' state to restore")
                    raise wlm_exceptions.InvalidState(reason=msg)
                self.db.workload_update(context, workload['id'], {'status': 'locked'})
            finally:
                workload_lock.release()
               
            if snapshot['status'] != 'available':
                msg = _('Snapshot status must be available')
                raise wlm_exceptions.InvalidState(reason=msg)
       
            self.db.snapshot_update(context, snapshot_id, {'status': 'restoring'})
 
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
            restore_display_name = restore['display_name']
            restore_restore_type = restore['restore_type']
            if restore_display_name == 'One Click Restore':
                local_time = self.get_local_time(context, restore['created_at']) 
                restore_display_name = local_time + ' (' + restore['display_name'] + ')'
            AUDITLOG.log(context,'Workload \'' + workload_display_name + '\' ' + \
                         snapshot_snapshot_type + ' Snapshot \'' + \
                         snapshot_display_name + '\' Restore \'' + \
                         restore_display_name + '\' Create Submitted', restore)
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
            workload = self.workload_get(context, snapshot['workload_id'])
            snapshot_display_name = snapshot['display_name']
            if snapshot_display_name == 'User-Initiated' or snapshot_display_name == 'jobscheduler':
                local_time = self.get_local_time(context, snapshot['created_at'])
                snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'
            AUDITLOG.log(context, 'Workload \'' + workload['display_name'] + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Cancel Requested', snapshot)
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
            AUDITLOG.log(context, 'Workload \'' + workload['display_name'] + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Cancel Submitted', snapshot)

            return True

        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))


    @autolog.log_method(logger=Logger)
    def snapshot_mount(self, context, snapshot_id, mount_vm_id):
        """
        Make the RPC call to Mount the snapshot.
        """
        compute_service = nova.API(production=True)
        try:
            snapshot = self.snapshot_get(context, snapshot_id)
            server = compute_service.get_server_by_id(context, mount_vm_id)
            flavor_id = server.flavor['id']
            fl=compute_service.get_flavor_by_id(context, flavor_id)
            if fl.ephemeral:
                error_msg = "Recovery manager instance cannot have ephemeral disk"
                raise Exception(error_msg)

            (image_service, image_id) = glance.get_remote_image_service(context, server.image['id'])
            metadata = image_service.show(context, server.image['id'])
            error_msg = "Recovery manager instance needs to be created with glance image property 'hw_qemu_guest_agent=yes'"
            if 'hw_qemu_guest_agent' in metadata['properties'].keys():
                if metadata['properties']['hw_qemu_guest_agent'] != 'yes':
                    raise Exception(error_msg)
            else:
                raise Exception(error_msg)

            if not snapshot:
                msg = _('Invalid snapshot id')
                raise wlm_exceptions.Invalid(reason=msg)

            workload = self.workload_get(context, snapshot['workload_id'])
            snapshots_all = self.db.snapshot_get_all(context)
            for snapshot_one in snapshots_all:
                if snapshot_one.status == 'mounted':
                   if workload['source_platform'] == 'openstack':
                      mounted_vm_id = self.db.get_metadata_value(snapshot_one.metadata, 'mount_vm_id')
                      if mounted_vm_id is not None:
                         if mount_vm_id == mounted_vm_id:
                             msg = _('snapshot %s already mounted with id:%s' % (snapshot_one.id, mount_vm_id))
                             raise wlm_exceptions.InvalidParameterValue(err=msg)
                      

            snapshot_display_name = snapshot['display_name']
            if snapshot_display_name == 'User-Initiated' or snapshot_display_name == 'jobscheduler':
               local_time = self.get_local_time(context, snapshot['created_at'])
               snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'
            AUDITLOG.log(context, 'Workload \'' + workload['display_name'] + '\' ' +
                         'Snapshot \'' + snapshot_display_name + '\' Mount Requested', snapshot)

            if snapshot['status'] != 'available':
                msg = _('Snapshot status must be available')
                raise wlm_exceptions.InvalidState(reason=msg)

            self.db.snapshot_update(context, snapshot_id, 
                                    { 'status': 'mounting' })
            self.workloads_rpcapi.snapshot_mount(context, workload['host'], snapshot_id, mount_vm_id)
                        
            AUDITLOG.log(context, 'Workload \'' + workload['display_name'] + '\' ' +
                         'Snapshot \'' + snapshot_display_name + '\' Mount Submitted', snapshot)
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

            mount_vm_id = self.db.get_metadata_value(snapshot['metadata'], 'mount_vm_id')
            if mount_vm_id == None:
                LOG.error(_("Could not find recovery manager vm id in the snapshot metadata"))
                raise wlm_exceptions.Invalid(reason=msg)

            workload = self.workload_get(context, snapshot['workload_id'])
            snapshot_display_name = snapshot['display_name']
            if snapshot_display_name == 'User-Initiated' or snapshot_display_name == 'jobscheduler':
                local_time = self.get_local_time(context, snapshot['created_at'])
                snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'

            AUDITLOG.log(context, 'Workload \'' + workload['display_name'] + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Dismount Requested', snapshot)

            if snapshot['status'] != 'mounted':
                msg = _('Snapshot status must be mounted')
                raise wlm_exceptions.InvalidState(reason=msg)

            self.workloads_rpcapi.snapshot_dismount(context, workload['host'], snapshot_id)
            AUDITLOG.log(context, 'Workload \'' + workload['display_name'] + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Dismount Submitted', snapshot)
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))         

    @autolog.log_method(logger=Logger)
    def mounted_list(self, context, workload_id):
        """
        Gets list of mounted snapshots
        """
        try:
            mounted_snapshots = []
            kwargs = {"workload_id":workload_id}
            snapshots = self.db.snapshot_get_all(context, **kwargs)
            if len(snapshots) == 0:
               msg = _("Not found any snapshots")
               wlm_exceptions.ErrorOccurred(reason=msg)               

            for snapshot in snapshots:
                if snapshot.status == 'mounted':
                   fspid = self.db.get_metadata_value(snapshot.metadata, 'fsmanagerpid')
                   mounturl = fspid = self.db.get_metadata_value(snapshot.metadata, 'mounturl')
                   #if (fspid and int(fspid) != -1) and (mounturl and len(mounturl) > 1):
                   mounted = {'snapshot_id': snapshot.id,
                              'snapshot_name': snapshot.display_name,
                              'workload_id': snapshot.workload_id,
                              'mounturl': mounturl,
                              'status':snapshot.status,
                             }
                   mounted_snapshots.append(mounted)
            return dict(mounted_snapshots=mounted_snapshots)
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))

    @autolog.log_method(logger=Logger)
    def restore_get(self, context, restore_id):
        rv = self.db.restore_get(context, restore_id)
        restore_details  = dict(rv.iteritems())
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id, read_deleted="yes", project_only='yes')
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
        
        snapshot = self.db.snapshot_get(context, rv.snapshot_id, read_deleted="yes", project_only='yes')
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
        Delete a workload restore.
        """
        restore_details = self.restore_show(context, restore_id)

        restore = self.db.restore_get(context, restore_id)
        snapshot = self.db.snapshot_get(context, restore['snapshot_id'])
        workload = self.workload_get(context, snapshot['workload_id'])
        restore_display_name = restore['display_name']
        if restore_display_name == 'One Click Restore':
            local_time = self.get_local_time(context, restore['created_at']) 
            restore_display_name = local_time + ' (' + restore['display_name'] + ')'
        snapshot_display_name = snapshot['display_name']
        if snapshot_display_name == 'User-Initiated' or snapshot_display_name == 'jobscheduler':
            local_time = self.get_local_time(context, snapshot['created_at'])
            snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'
        workload_display_name = workload['display_name']            
        AUDITLOG.log(context, 'Workload \'' + workload_display_name + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Restore \'' + restore_display_name + '\' Delete Requested', restore)

        if restore_details['target_platform'] == 'vmware':
            self.db.restore_delete(context, restore_id)
            AUDITLOG.log(context, 'Workload \'' + workload_display_name + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Restore \'' + restore_display_name + '\' Delete Submitted', restore)
            return
            
        
        if restore_details['status'] not in ['available', 'error', 'cancelled']:
            msg = _("Status of the requested resource status must be 'available' or 'error' or 'cancelled'")
            raise wlm_exceptions.InvalidState(reason=msg)

        """
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
        """

        self.db.restore_delete(context, restore_id)
        AUDITLOG.log(context, 'Workload \'' + workload_display_name + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Restore \'' + restore_display_name + '\' Delete Submitted', restore)
       
    @autolog.log_method(logger=Logger)
    def restore_cancel(self, context, restore_id):
        """
        Make the RPC call to cancel restore
        """
        try:
            restore = self.db.restore_get(context, restore_id)
            snapshot = self.db.snapshot_get(context, restore['snapshot_id'])
            workload = self.workload_get(context, snapshot['workload_id'])
            restore_display_name = restore['display_name']
            if restore_display_name == 'One Click Restore':
                local_time = self.get_local_time(context, restore['created_at']) 
                restore_display_name = local_time + ' (' + restore['display_name'] + ')'
            snapshot_display_name = snapshot['display_name']
            if snapshot_display_name == 'User-Initiated' or snapshot_display_name == 'jobscheduler':
                local_time = self.get_local_time(context, snapshot['created_at'])
                snapshot_display_name = local_time + ' (' + snapshot['display_name'] + ')'
            workload_display_name = workload['display_name']            
            AUDITLOG.log(context, 'Workload \'' + workload_display_name + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Restore \'' + restore_display_name + '\' Cancel Requested', restore)
            
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

            AUDITLOG.log(context, 'Workload \'' + workload_display_name + '\' ' + 'Snapshot \'' + snapshot_display_name + '\' Restore \'' + restore_display_name + '\' Cancel Submitted', restore)

            return True

        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))
   
  
    @autolog.log_method(logger=Logger)
    @upload_settings
    def settings_create(self, context, settings):
        created_settings = []
        try:
            for setting in settings:
                created_settings.append(self.db.setting_create(context, setting))
        except Exception as ex:
            LOG.exception(ex)
        return created_settings 
    
    @autolog.log_method(logger=Logger)
    @upload_settings
    def settings_update(self, context, settings):
        updated_settings = []
        try:
            for setting in settings:
                updated_settings.append(self.db.setting_update(context, setting['name'], setting))
        except Exception as ex:
            LOG.exception(ex)
        return updated_settings
    
    @autolog.log_method(logger=Logger)
    @upload_settings
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

    @autolog.log_method(logger=Logger)
    def tasks_get(self, context, status, page, size, time_in_minutes):
        tasks = self.db.task_get_all(context, status=status, page=page, size=size, time_in_minutes=time_in_minutes)
        return tasks

    
    @autolog.log_method(logger=Logger)
    def get_local_time(self, context, record_time):
        """
        Convert and return the date and time - from GMT to local time 
        """
        try:
            epoch = time.mktime(record_time.timetuple())
            offset = datetime.fromtimestamp (epoch) - datetime.utcfromtimestamp (epoch)
            local_time = datetime.strftime((record_time + offset), "%m/%d/%Y %I:%M %p") 
            return local_time
        except Exception as ex:
            LOG.exception(ex)
            raise wlm_exceptions.ErrorOccurred(reason = ex.message % (ex.kwargs if hasattr(ex, 'kwargs') else {}))

      
    @autolog.log_method(logger=Logger)
    @upload_settings
    def trust_create(self, context, role_name):

        # create trust
        cntx = wlm_context.RequestContext(
            trustor_user_id=context.user_id,
            auth_token=context.auth_token,
            tenant_id=context.project_id,
            roles=[role_name],
            is_admin=False)
        clients.initialise()
        keystoneclient = clients.Clients(cntx).client("keystone")
        trust_context = keystoneclient.create_trust_context()

        setting = {u'category': "identity",
                   u'name': "trust-%s" % str(uuid.uuid4()),
                   u'description': u'token id for user %s project %s' % \
                                   (context.user_id, context.project_id),
                   u'value': trust_context.trust_id,
                   u'user_id': context.user_id,
                   u'is_public': False,
                   u'is_hidden': True,
                   u'metadata': {'role_name': role_name},
                   u'type': "trust_id",}
        created_settings = []
        try:
            created_settings.append(self.db.setting_create(context, setting))
        except Exception as ex:
            LOG.exception(ex)

        return created_settings 


    @autolog.log_method(logger=Logger)
    @upload_settings
    def trust_delete(self, context, name):

        trust = self.db.setting_get(context, name)
        if trust.type != "trust_id":
            msg = _("No trust record by name %s" % name)
            raise wlm_exceptions.Invalid(reason=msg)

        try:
            cntx = wlm_context.RequestContext(
                trustor_user_id=context.user_id,
                auth_token=context.auth_token,
                tenant_id=context.project_id,
                is_admin=False)

            clients.initialise()
            keystoneclient = clients.Clients(cntx).client("keystone")
            keystoneclient.delete_trust(trust.value)
        except Exception as ex:
            pass

        self.db.setting_delete(context, name)


    @autolog.log_method(logger=Logger)
    def trust_list(self, context):

        settings =  self.db.setting_get_all_by_project(
                        context, context.project_id)

        trust = [t for t in settings if t.type == "trust_id" and \
                 t.user_id == context.user_id and \
                 t.project_id == context.project_id]
        return trust

    @autolog.log_method(logger=Logger)
    def trust_get(self, context, name):
        try:
            return self.db.setting_get(context, name)
        except Exception as ex:
            LOG.exception(ex)

        return None

    @autolog.log_method(logger=Logger)
    @upload_settings
    def license_create(self, context, license_text):

        def parse_license_text(licensetext,
                               public_key=vault.CONF.triliovault_public_key):
            dsa = DSA.load_pub_key(public_key)
            if not dsa.check_key():
                raise wlm_exceptions.InternalError(
                    "Invalid TrilioVault public key ",
                    "Cannot validate license")

            if not "License Key" in licensetext:
                raise wlm_exceptions.InvalidLicense(
                    message="Cannot find License Key in license key")

            try:
                licensekey = licensetext[licensetext.find("License Key") + len("License Key"):].lstrip().rstrip()
                license_pair_base64 = licensekey[0:licensekey.find('X02')]
                license_pair = base64.b64decode(license_pair_base64)
                ord_len = license_pair.find('\r')
                license_text_len = ord(license_pair[0:ord_len].decode('UTF-32BE'))
                license_text = license_pair[ord_len:license_text_len+ord_len]
                license_signature = license_pair[ord_len+license_text_len:]

                if dsa.verify_asn1(sha1(license_text).digest(), license_signature):
                    properties_text = zlib.decompress(license_text[5:])
                    license = {}
                    for line in properties_text.split('\n'):
                        if len(line.split("=")) != 2:
                            continue
                        license[line.split("=")[0].strip()] = line.split("=")[1].lstrip().rstrip()

                    return license
                else:
                    raise wlm_exceptions.InvalidLicense(
                        message="Cannot verify the license signature")
            except:
                raise wlm_exceptions.InvalidLicense(
                    message="Cannot verify the license signature")

        # create trust
        if context.is_admin is False:
            raise wlm_exceptions.AdminRequired()

        license_json = json.dumps(parse_license_text(license_text))
        setting = {u'category': "license",
                   u'name': "license-%s" % str(uuid.uuid4()),
                   u'description': u'TrilioVault License Key',
                   u'value': license_json,
                   u'user_id': context.user_id,
                   u'is_public': False,
                   u'is_hidden': True,
                   u'metadata': {},
                   u'type': "license_key",}
        created_license = []
        try:
            settings =  self.db.setting_get_all(context)
            created_license.append(self.db.setting_create(context, setting))

            for setting in settings:
                if setting.type == "license_key":
                    try:
                        self.db.setting_delete(context, setting.name)
                    except:
                        pass
        except Exception as ex:
            LOG.exception(ex)

        return json.loads(created_license[0].value)

    @autolog.log_method(logger=Logger)
    def license_list(self, context):

        if context.is_admin is False:
            raise wlm_exceptions.AdminRequired()

        settings =  self.db.setting_get_all(context)

        license = [t for t in settings if t.type == "license_key"]

        if len(license) == 0:
            raise Exception("No licenses added to TrilioVault")

        return json.loads(license[0].value)
