# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

import socket
import json
import os
import uuid
from operator import itemgetter
import cPickle as pickle

from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import workloads as workloadAPI
from workloadmgr.vault import vault
from workloadmgr import exception
from workloadmgr.openstack.common import log as logging
from workloadmgr.workloads import workload_utils
from workloadmgr.common import context as wlm_context
from workloadmgr.common import clients
from workloadmgr.db.sqlalchemy import models
from workloadmgr.db.sqlalchemy.session import get_session

LOG = logging.getLogger(__name__)
DBSession = get_session()

# Directory to store database files for all json files.
db_temp_dir = '/tmp/triliodata_imports/'
workloads = []

import_map = [
    {'file': 'workload_db',
     'model_class': 'Workloads',
     'metadata_model_class': 'WorkloadMetadata',
     'getter_method' : 'workload_get',
     'getter_method_params' : ['id']
     },
    {'file': 'workload_vms_db',
     'model_class': 'WorkloadVMs',
     'metadata_model_class': 'WorkloadVMMetadata',
     'getter_method' : 'workload_vm_get',
     'getter_method_params' : ['id']
     },
    {'file': 'snapshot_db',
     'model_class': 'Snapshots',
     'metadata_model_class': 'SnapshotMetadata',
     'getter_method' : 'snapshot_get',
     'getter_method_params' : ['id']
     },
    {'file': 'snapshot_vms_db',
     'model_class': 'SnapshotVMs',
     'metadata_model_class': 'SnapshotVMMetadata',
     'getter_method' : 'snapshot_vm_get',
     'getter_method_params' : ['vm_id', 'snapshot_id']
     },
    {'file': 'resources_db',
     'model_class': 'SnapshotVMResources',
     'metadata_model_class': 'SnapshotVMResourceMetadata',
     'getter_method' : 'snapshot_vm_resource_get',
     'getter_method_params' : ['id']
     },
    {'file': 'disk_db',
     'model_class': 'VMDiskResourceSnaps',
     'metadata_model_class': 'VMDiskResourceSnapMetadata',
     'getter_method' : 'vm_disk_resource_snaps_get',
     'getter_method_params' : ['snapshot_vm_resource_id']
     },
    {'file': 'network_db',
     'model_class': 'VMNetworkResourceSnaps',
     'metadata_model_class': 'VMNetworkResourceSnapMetadata',
     'getter_method' : 'vm_network_resource_snaps_get',
     'getter_method_params' : ['vm_network_resource_snap_id']
     },
    {'file': 'security_db',
     'model_class': 'VMSecurityGroupRuleSnaps',
     'metadata_model_class': 'VMSecurityGroupRuleSnapMetadata',
     'getter_method' : 'vm_security_group_rule_snaps_get',
     'getter_method_params' : ['vm_security_group_snap_id']
     }
]


def import_resources(tenantcontext, resource_map, new_version, upgrade):
    '''
    create list of dictionary object for each resource and
    dump it into the database.
    '''

    resources_list = [] #Contains list of json objects need to insert
    resources_list_update = [] #Contains list of json objects need to update
    resources_metadata_list = []
    resources_metadata_list_update = []
 
    file = resource_map['file']
    model_class =  resource_map['model_class']
    metadata_model_class =  resource_map['metadata_model_class']
    getter_method =  resource_map['getter_method']
    getter_method_params =  resource_map['getter_method_params']

    db = WorkloadMgrDB().db
    get_resource_method = getattr(db, getter_method)

    def update_resource_list(cntxt, resource):
        '''
        Update resource list with resource objects need to
        insert/update in database.
        '''
        # if resource is workload then check the status of workload and
        # set it to available.
        if file == 'workload_db':
            if resources['status'] == 'locked':
               resources['status'] = 'available'

        try:
            # Check if resource already in the database then update.
            param_list = tuple([resource[param] for param in getter_method_params])
            if get_resource_method(tenantcontext, *param_list):
               for resource_metadata in resource.pop('metadata'):
                   resources_metadata_list_update.append(resource_metadata)
               _adjust_values(tenantcontext, new_version, resource, upgrade)
               resources_list_update.append(resource)
            else:
                raise Exception
        except Exception:
            #If resource not found then create new entry in database
            for resource_metadata in resource.pop('metadata'):
                resources_metadata_list.append(resource_metadata)
            _adjust_values(tenantcontext, new_version, resource, upgrade)
            resources_list.append(resource)

    try:
        #Load file for resource containing all objects neeed to import
        resources_db_list = pickle.load(open(db_temp_dir + file, "rb"))

        for resources in resources_db_list:
            if isinstance(resources, list):
                for resource in resources:
                    update_resource_list(tenantcontext, resource)
            else:
                update_resource_list(tenantcontext,resources)

        # Dump list of objects into the database.
        DBSession.bulk_update_mappings(eval('models.%s' % (model_class)), resources_list_update)
        DBSession.commit()
        DBSession.bulk_update_mappings(eval('models.%s' % (metadata_model_class)), resources_metadata_list_update)
        DBSession.commit()

        DBSession.bulk_insert_mappings(eval('models.%s' % (model_class)), resources_list)
        DBSession.commit()
        DBSession.bulk_insert_mappings(eval('models.%s' % (metadata_model_class)), resources_metadata_list)
        DBSession.commit()

        # if workloads then check for job schedule, if it's there then update it.
        if file == 'workload_db':
            resources_list.extend(resources_list_update)
            for resource in resources_list:
                workload = models.Workloads()
                workload.update(resource)
                workloads.append(workload)
                if len(resources['jobschedule']):
                    workload_api = workloadAPI.API()
                    workload_api.workload_add_scheduler_job(pickle.loads(str(resources['jobschedule'])), workload)

    except Exception as ex:
        LOG.exception(ex)

#TODO: Need to remove workload_url and and backup_endpoint from parameters.
def import_workload(cntx, workload_url, new_version, backup_endpoint, upgrade=True):
    DBSession.autocommit = False
    del workloads[:]
    for resource_map in import_map:
        import_resources(cntx, resource_map, new_version, upgrade)
    DBSession.autocommit = True
    return workloads


def _adjust_values(cntx, new_version, values, upgrade):
    values['version'] = new_version
    if upgrade == False:
        values['user_id'] = cntx.user_id
        values['project_id'] = cntx.project_id
    if 'metadata' in values:
        metadata = {}
        for meta in values['metadata']:
            metadata[meta['key']] = meta['value']
        values['metadata'] = metadata  
    if 'host' in values: 
        values['host'] = socket.gethostname()
     
    return values


def import_settings(cntx, new_version, upgrade=True):
    try:
        db = WorkloadMgrDB().db
        backup_target = vault.get_settings_backup_target()
        settings = json.loads(backup_target.get_object('settings_db'))
        for setting_values in settings:
            try:
                if 'key' in setting_values:
                    setting_values['name'] = setting_values['key']
                setting_values = _adjust_values(cntx, new_version,
                                                setting_values, upgrade)
                db.setting_create(cntx, setting_values)  
            except Exception as ex:
                LOG.exception(ex)                      
    except Exception as ex:
        LOG.exception(ex)


def project_id_exists(context, project_id):
    """clients.initialise()
    client_plugin = clients.Clients(context)
    kclient = client_plugin.client("keystone")

    # TODO: Optimize it without reading project list os many times
    kclient.client_plugin = kclient"""
    projects = vault.get_project_list_for_import(context)
    for prj in projects: 
        if uuid.UUID(prj.id) == uuid.UUID(project_id):
            return True

    return False

'''
def import_workload(cntx, workload_url, new_version,
                    backup_endpoint, upgrade=True):
    """ Import workload and snapshot records from vault 
    Versions Supported: 1.0.177
    """
    db = WorkloadMgrDB().db
    backup_target = vault.get_backup_target(backup_endpoint)
    workload_values = json.loads(backup_target.get_object(
        os.path.join(workload_url['workload_url'], 'workload_db')))
    if upgrade == True:
        # make sure that cntx is admin
        # make sure tenant id exists on this openstack
        # create context object from tenant id and user id
        tenant_id = workload_values.get('tenant_id', None)
        tenant_id = workload_values.get('project_id', tenant_id)
        if project_id_exists(cntx, tenant_id):
            tenantcontext = wlm_context.RequestContext(
                                user_id=workload_values['user_id'],
                                project_id=tenant_id,
                                tenant_id=tenant_id)
        else:
            raise exception.InvalidRequest(
                "Workload %s tenant %s does not belong to this cloud" %
                (workload_values['id'], tenant_id))
    else:
        tenantcontext = cntx

    workload_values = _adjust_values(tenantcontext, new_version,
                                     workload_values, upgrade)
    workload_metadata = workload_values['metadata']

    if workload_values['status'] == 'locked':
        workload_values['status'] = 'available'

    try:
        workload = db.workload_get(tenantcontext, workload_values['id'])
        # If the workload already exists, update the values from the nfs media
        workload_id = workload_values.pop('id')
        workload = db.workload_update(tenantcontext, workload_id, workload_values)
    except exception.WorkloadNotFound as ex:
        # workload is not found in the database
        workload = db.workload_create(tenantcontext, workload_values)

    if len(workload_values['jobschedule']): 
        workload_api = workloadAPI.API()
        #TODO: look at the job scheduler
        workload_api.workload_add_scheduler_job(pickle.loads(str(workload_values['jobschedule'])), workload)                                       
                
    workload_vms = json.loads(backup_target.get_object(
        os.path.join(workload_url['workload_url'], 'workload_vms_db')))
    for workload_vm_values in workload_vms:
        workload_vm_values = _adjust_values(tenantcontext, new_version,
                                            workload_vm_values, upgrade)
        if db.workload_vm_get(tenantcontext, workload_vm_values['id']):
            workload_vm_id = workload_vm_values.pop('id')
            db.workload_vms_update(tenantcontext, workload_vm_id,
                                   workload_vm_values)
        else:
            db.workload_vms_create(tenantcontext, workload_vm_values)

    snapshot_values_list = []
    for snapshot_url in workload_url['snapshot_urls']:
        try:
            snapshot_values = json.loads(backup_target.get_object(
                os.path.join(snapshot_url, 'snapshot_db')))
            snapshot_values['snapshot_url'] = snapshot_url
            snapshot_values_list.append(snapshot_values)
        except Exception as ex:
            LOG.exception(ex)

    snapshot_values_list_sorted = sorted(snapshot_values_list,
                                         key=itemgetter('created_at'))
    for snap in snapshot_values_list_sorted:
        if snap['snapshot_type'] == 'full':
            workload_backup_media_size = snap['size']
            break

    update_media = False
    if 'backup_media_target' not in workload_metadata:
        jobschedule = pickle.loads(str(workload_values['jobschedule']))
        if jobschedule['retention_policy_type'] == 'Number of Snapshots to Keep':
            incrs = jobschedule['retention_policy_value']
        else:
            jobsperday = int(jobschedule['interval'].split("hr")[0])
            incrs = jobschedule['retention_policy_value'] * jobsperday

        if jobschedule['fullbackup_interval'] == '-1':
            fulls = 1
        else:
            fulls = incrs/jobschedule['fullbackup_interval']
            incrs = incrs - fulls

        workload_approx_backup_size = \
            (fulls * workload_backup_media_size * vault.CONF.workload_full_backup_factor +
            incrs * workload_backup_media_size * vault.CONF.workload_incr_backup_factor) / 100

        workload_metadata['backup_media_target'] = backup_endpoint
        workload_metadata['workload_approx_backup_size'] = workload_approx_backup_size
        
        db.workload_update(tenantcontext, 
                           workload.id,
                           {'metadata': workload_metadata})
        workload_utils.upload_workload_db_entry(tenantcontext, workload.id)

    for snapshot_values in snapshot_values_list_sorted:
        snapshot_values = _adjust_values(tenantcontext, new_version, snapshot_values, upgrade)
        snapshot_id = snapshot_values.get('id', None)
        try:
            snapshot = db.snapshot_get(tenantcontext, snapshot_values['id'])
            snapshot_id = snapshot_values.pop('id')
            snapshot = db.snapshot_update(tenantcontext, snapshot_id, snapshot_values)
        except exception.SnapshotNotFound as ex:
            snapshot = db.snapshot_create(tenantcontext, snapshot_values)

        try:
            snapshot_vms = json.loads(backup_target.get_object(
                os.path.join(snapshot_values['snapshot_url'], 'snapshot_vms_db')))
            for snapshot_vm_values in snapshot_vms:
                snapshot_vm_values = _adjust_values(tenantcontext, new_version,
                                                    snapshot_vm_values, upgrade)
                snapshot_vm_id = snapshot_vm_values['id']
                if db.snapshot_vm_get(tenantcontext, snapshot_vm_id, snapshot_id):
                    snapshot_vm_id = snapshot_vm_values.pop('id')
                    db.snapshot_vm_update(tenantcontext, snapshot_vm_id,
                                          snapshot_id, snapshot_vm_values)
                else:
                    db.snapshot_vm_create(tenantcontext, snapshot_vm_values)

            snapshot_vm_resources = json.loads(backup_target.get_object(
                os.path.join(snapshot_values['snapshot_url'], 'resources_db')))
            for snapshot_vm_resource_values in snapshot_vm_resources:
                snapshot_vm_resource_values = _adjust_values(tenantcontext, new_version,
                                                             snapshot_vm_resource_values, upgrade)
                db.snapshot_vm_resource_create(tenantcontext, snapshot_vm_resource_values)

            resources = db.snapshot_resources_get(tenantcontext, snapshot.id)
            for res in resources:
                vm_res_id = 'vm_res_id_%s' % (res['id'])
                for meta in res.metadata:
                    if meta.key == "label":
                        vm_res_id = 'vm_res_id_%s_%s' % (res['id'], meta.value)
                        break
                if res.resource_type == "network" or \
                    res.resource_type == "subnet" or \
                    res.resource_type == "router" or \
                    res.resource_type == "nic":                
                    path = os.path.join("workload_" + snapshot['workload_id'],
                                        "snapshot_" + snapshot['id'],
                                        "network", vm_res_id,
                                        "network_db")
                    vm_network_resource_snaps = json.loads(backup_target.get_object(path))
                    for vm_network_resource_snap_values in vm_network_resource_snaps:
                        vm_network_resource_snap_values = _adjust_values(
                            tenantcontext, new_version,
                            vm_network_resource_snap_values, upgrade)
                        db.vm_network_resource_snap_create(tenantcontext,
                            vm_network_resource_snap_values)

                elif res.resource_type == "disk":
                    path = os.path.join("workload_" + snapshot['workload_id'],
                                        "snapshot_" + snapshot['id'],
                                        "vm_id_" + res.vm_id,
                                        vm_res_id.replace(' ',''),
                                        "disk_db")
                    vm_disk_resource_snaps = json.loads(backup_target.get_object(path))
                    vm_disk_resource_snaps_sorted = sorted(
                        vm_disk_resource_snaps, key=itemgetter('created_at'))
                    for vm_disk_resource_snap_values in vm_disk_resource_snaps_sorted:
                        vm_disk_resource_snap_values = _adjust_values(
                            tenantcontext, new_version, vm_disk_resource_snap_values, upgrade)

                        db.vm_disk_resource_snap_create(tenantcontext,
                                                        vm_disk_resource_snap_values)

                elif res.resource_type == "securty_group":
                    path = os.path.join("workload_" + snapshot['workload_id'],
                                        "snapshot_" + snapshot['id'],
                                        "securty_group",
                                        vm_res_id,
                                        "security_group_db")
                    vm_security_group_rule_snaps= json.loads(backup_target.get_object(path))
                    for vm_security_group_rule_snap_values in vm_security_group_rule_snaps:
                        vm_security_group_rule_snap_values = _adjust_values(
                            tenantcontext, new_version, vm_security_group_rule_snap_values, upgrade)
                        db.vm_security_group_rule_snap_create(
                            tenantcontext, vm_security_group_rule_snap_values)

        except Exception as ex:
            LOG.exception(ex)
            db.snapshot_update(tenantcontext,snapshot.id, {'status': 'import-error'})

    return workload
'''
