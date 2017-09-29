# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

import socket
import json
import os
import uuid
from operator import itemgetter
import cPickle as pickle
import shutil
import tempfile

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
from workloadmgr.common.workloadmgr_keystoneclient import KeystoneClient

LOG = logging.getLogger(__name__)
DBSession = get_session()

# Directory to store database files for all json files.
workloads = []
workload_backup_endpoint = {}
workload_backup_media_size = {}
vault_backend = None

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
    {'file': 'security_group_db',
     'model_class': 'VMSecurityGroupRuleSnaps',
     'metadata_model_class': 'VMSecurityGroupRuleSnapMetadata',
     'getter_method' : 'vm_security_group_rule_snaps_get',
     'getter_method_params' : ['vm_security_group_snap_id']
     },
     {'file': 'config_workload_db',
     'model_class': 'ConfigWorkloads',
     'metadata_model_class': 'ConfigWorkloadMetadata',
     'getter_method' : 'config_workload_get',
     'getter_method_params' : ['id']
     },
     {'file': 'config_backup_db',
     'model_class': 'ConfigBackups',
     'metadata_model_class': 'ConfigBackupMetadata',
     'getter_method' : 'config_backup_get',
     'getter_method_params' : ['id']
     },]
        
def project_id_exists(cntx, project_id):
    """clients.initialise()
    client_plugin = clients.Clients(context)
    kclient = client_plugin.client("keystone")

    # TODO: Optimize it without reading project list os many times
    kclient.client_plugin = kclient"""
    keystone_client = KeystoneClient(cntx)
    projects = keystone_client.client.get_project_list_for_import(cntx)
    for prj in projects:
        if uuid.UUID(prj.id) == uuid.UUID(project_id):
            return True
    return False

def check_tenant(cntx, workload_path, upgrade):
    '''
    Check for given worlkoad tenant whether it exist with-in the cloud or not.
    '''
    try:
        workload_data = vault_backend.get_object(os.path.join(workload_path, 'workload_db'))
        if workload_data is not None and len(workload_data) > 0:
            workload_values = json.loads(workload_data)
            tenant_id = workload_values.get('tenant_id', None)
            tenant_id = workload_values.get('project_id', tenant_id)
            if project_id_exists(cntx, tenant_id):
                return True
            else:
                raise exception.InvalidRequest(
                      reason=("Workload %s tenant %s does not belong to this cloud" %
                             (workload_values['id'], tenant_id)))
    except Exception as ex:
           LOG.exception(ex)

def get_context(values):
    try:
        tenant_id = values.get('tenant_id', None)
        tenant_id = values.get('project_id', tenant_id)
        tenantcontext = wlm_context.RequestContext(
                user_id=values['user_id'],
                project_id=tenant_id,
                tenant_id=tenant_id)
        return tenantcontext
    except Exception as ex:
        LOG.exception(ex)

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
        (backup_target, path) = vault.get_settings_backup_target()
        settings = json.loads(backup_target.get_object(path))
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

def update_backup_media_target(file_path, backup_endpoint):
    try:
        file_data = vault_backend.get_object(file_path)
        if file_data is None or len(file_data) <= 0:
            return
        json_obj = json.loads(file_data)

        #This case is for config_workload
        if json_obj.get('backup_media_target', None) :
            if backup_endpoint != json_obj.get('backup_media_target'):
                json_obj['backup_media_target'] = backup_endpoint
        #Check for config_backup
        elif json_obj.get('vault_storage_path', None):
            vault_storage_path = json_obj.get('vault_storage_path')
            mount_path = vault.get_backup_target(backup_endpoint).mount_path
            if vault_storage_path.startswith(mount_path) is False:
                backup_path = vault_storage_path.split(vault.CONF.cloud_unique_id + "/")[1]
                json_obj['vault_storage_path'] = os.path.join(mount_path, vault.CONF.cloud_unique_id, backup_path)
        else:
            #Case for workload and snapshot
            metadata = json_obj.get('metadata', None)
            if metadata:
                for meta in metadata:
                    if meta['key'] == 'backup_media_target':
                        if backup_endpoint != meta['value']:
                            meta['value'] = backup_endpoint
                            break

            json_obj['metadata'] = metadata

        with open(file_path, 'w') as outfile:
            json.dump(json_obj, outfile)

    except Exception as ex:
        LOG.exception(ex)

def get_workload_url(context, workload_ids, upgrade):
    '''
    Iterate over all NFS backups mounted for list of workloads available.
    '''
    workload_url_iterate = []
    workload_ids_to_import = list(workload_ids)
    failed_workloads = []

    def add_config_workload(context, config_workload_path):
        try:
            #If config_workload is not in the database then only import it.
            db = WorkloadMgrDB().db
            config_workload = db.config_workload_get(context)
        except exception.ConfigWorkloadNotFound:
            workload_url_iterate.append(config_workload_path)
            #Updating backup media and adding config_workload for import
            config_workload_db = os.path.join(config_workload_path, "config_workload_db")
            if os.path.exists(config_workload_db):
                update_backup_media_target(config_workload_db, backup_endpoint)
            for item in os.listdir(config_workload_path):
                config_backup_db = os.path.join(config_workload_path, item, "config_backup_db")
                if os.path.exists(config_backup_db):
                    update_backup_media_target(config_backup_db, backup_endpoint)

    def add_workload(context, workload_id, workload, backup_endpoint, upgrade):
        #Before adding the workload check whether workload is valid or not
        if vault.validate_workload(workload) is False:
           failed_workloads.append(workload_id)
           LOG.error("Workload %s doesn't contains required database files," %workload_id)
           return

        #Update backup media target
        update_backup_media_target(os.path.join(workload, "workload_db"), backup_endpoint)
        for item in os.listdir(workload):
             snapshot_db = os.path.join(workload, item, "snapshot_db")
             if os.path.exists(snapshot_db):
                 update_backup_media_target(snapshot_db, backup_endpoint)

        # Check whether workload tenant exist in current cloud or not
        if check_tenant(context, workload, upgrade):
            # update workload_backend_endpoint map
            workload_backup_endpoint[workload_id] = backup_endpoint
            workload_url_iterate.append(workload)
        else:
            failed_workloads.append(workload_id)

    for backup_endpoint in vault.CONF.vault_storage_nfs_export.split(','):
        backup_target = None
        global vault_backend
        try:
            backup_target = vault.get_backup_target(backup_endpoint)
            if vault_backend is None:
               vault_backend = backup_target 

            #importing config backup only when user has not specified any workload id
            if len(workload_ids) == 0:
                config_workload_path = os.path.join(backup_target.mount_path,
                                   vault.CONF.cloud_unique_id, 'config_workload' )
                if os.path.exists(config_workload_path):
                    add_config_workload(context, config_workload_path)

            workload_url = backup_target.get_workloads(context)

            for workload in workload_url:
                workload_id = os.path.split(workload)[1].replace('workload_', '')

                if len(workload_ids) > 0:
                    #If workload found in given workload id's then add to iterate list
                    if workload_id in workload_ids_to_import:
                        workload_ids_to_import.remove(workload_id)
                        add_workload(context, workload_id, workload, backup_endpoint, upgrade)
                else:
                    add_workload(context, workload_id, workload, backup_endpoint, upgrade)

        except Exception as ex:
            LOG.exception(ex)

        finally:
            pass

    if len(workload_ids_to_import) > 0:
        failed_workloads.extend(workload_ids_to_import)

    return (workload_url_iterate, failed_workloads)

def update_workload_metadata(workload_values):
    '''
    Update workload values with "backup_media_target"
    and "workload_approx_backup_size".
    '''
    try:
        workload_metadata = workload_values['metadata']
        if 'backup_media_target' not in workload_metadata:
            jobschedule = pickle.loads(str(workload_values['jobschedule']))
            if jobschedule['retention_policy_type'] == 'Number of Snapshots to Keep':
                incrs = int(jobschedule['retention_policy_value'])
            else:
                jobsperday = int(jobschedule['interval'].split("hr")[0])
                incrs = int(jobschedule['retention_policy_value']) * jobsperday

            if int(jobschedule['fullbackup_interval']) == -1:
                fulls = 1
            elif int(jobschedule['fullbackup_interval']) == 0:
                fulls = incrs
                incrs = 0
            else:
                fulls = incrs / int(jobschedule['fullbackup_interval'])
                incrs = incrs - fulls

            if workload_backup_media_size.get(workload_values['id'], None) is None:
                workload_backup_media_size[workload_values['id']] = 1024 * 1024 * 1024
            workload_approx_backup_size = \
                (fulls * workload_backup_media_size[workload_values['id']] * vault.CONF.workload_full_backup_factor +
                 incrs * workload_backup_media_size[
                     workload_values['id']] * vault.CONF.workload_incr_backup_factor) / 100

            workload_values['metadata'][0]['backup_media_target'] = workload_backup_endpoint[ workload_values['id'] ]
            workload_values['metadata'][0]['workload_approx_backup_size'] = workload_approx_backup_size

        return workload_values
    except Exception as ex:
        LOG.exception(ex)

def get_json_files(context, workload_ids, db_dir, upgrade):

    # Map to store all path of all JSON files for a  resource
    db_files_map = {
        'workload_db': [],
        'workload_vms_db': [],
        'snapshot_db': [],
        'snapshot_vms_db': [],
        'resources_db': [],
        'network_db': [],
        'disk_db': [],
        'security_group_db': [],
        'config_workload_db': [],
        'config_backup_db': [],
    }

    try:
        workload_url_iterate, failed_workloads = get_workload_url(context, workload_ids, upgrade)

        if len(failed_workloads) == len(workload_url_iterate) == 0:
           raise exception.WorkloadsNotFound()

        if len(workload_ids) > 0 and len(failed_workloads) == len(workload_ids):
           return failed_workloads

        # Create list of all files related to a common resource
        #TODO:Find alternate for os.walk
        for workload_path in workload_url_iterate:
            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("config_workload_db"):
                        db_files_map['config_workload_db'].append(os.path.join(path, name))
                    elif name.endswith("config_backup_db"):
                        db_files_map['config_backup_db'].append(os.path.join(path, name))
                    elif name.endswith("workload_db"):
                        db_files_map['workload_db'].append(os.path.join(path, name))
                    elif name.endswith("workload_vms_db"):
                        db_files_map['workload_vms_db'].append(os.path.join(path, name))
                    elif name.endswith("snapshot_db"):
                        db_files_map['snapshot_db'].append(os.path.join(path, name))
                    elif name.endswith("snapshot_vms_db"):
                        db_files_map['snapshot_vms_db'].append(os.path.join(path, name))
                    elif name.endswith("resources_db"):
                        db_files_map['resources_db'].append(os.path.join(path, name))
                    elif name.endswith("network_db"):
                        db_files_map['network_db'].append(os.path.join(path, name))
                    elif name.endswith("disk_db"):
                        db_files_map['disk_db'].append(os.path.join(path, name))
                    elif name.endswith("security_group_db"):
                        db_files_map['security_group_db'].append(os.path.join(path, name))

        # Creating a map for each workload with workload_backup_media_size.
        for snap in db_files_map['snapshot_db']:
            file_data = vault_backend.get_object(snap)
            if file_data is not None and len(file_data) > 0:
                snapshot_json = json.loads(file_data)
                if snapshot_json['snapshot_type'] == 'full':
                    workload_backup_media_size[snapshot_json['workload_id']] = snapshot_json['size']

        # Iterate over each file for a resource in all NFS mounts
        # and create a single db file for that.
        for db, files in db_files_map.iteritems():
            db_json = []

            for file_name in files:
                file_data = vault_backend.get_object(file_name)
                if file_data is not None and len(file_data) > 0:
                    json_obj = json.loads(file_data)

                    if db == 'workload_db':
                        # In case of workload updating each object with
                        # "workload_backup_media_size" and "backup_media_target"
                        json_obj = update_workload_metadata(json_obj)
                    db_json.append(json_obj)

                pickle.dump(db_json, open(os.path.join(db_dir, db), 'wb'))
        return failed_workloads
    except Exception as ex:
        LOG.exception(ex)
        raise ex

def import_resources(tenantcontext, resource_map, new_version, db_dir, upgrade):
    '''
    create list of dictionary object for each resource and
    dump it into the database.
    '''

    resources_list = [] #Contains list of json objects need to insert
    #resources_list_update = [] #Contains list of json objects need to update
    resources_metadata_list = []
    #resources_metadata_list_update = []
 
    file_name = resource_map['file']
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
        if file_name in ['workload_db', 'config_workload_db']:
            if resource['status'] == 'locked':
               resource['status'] = 'available'

        if file_name in ['snapshot_db', 'config_backup_db'] :
            if resource['status'] != 'available':
               resource['status'] = 'error'
               resource['error_msg'] = 'Upload was not completed successfully.'

        
        try:
            # Check if resource already in the database then update.
            param_list = tuple([resource[param] for param in getter_method_params])
            if get_resource_method(tenantcontext, *param_list):
               pass
               #TODO: Uncomment the code for updating existing resources 
               #for resource_metadata in resource.pop('metadata'):
               #    resources_metadata_list_update.append(resource_metadata)
               #resource = _adjust_values(tenantcontext, new_version, resource, upgrade)
               #resources_list_update.append(resource)
            else:
                raise  exception.NotFound()
        except Exception:
            #If resource not found then create new entry in database
            for resource_metadata in resource.pop('metadata'):
                resources_metadata_list.append(resource_metadata)
            resource = _adjust_values(tenantcontext, new_version, resource, upgrade)
            resources_list.append(resource)

    try:
        #Load file for resource containing all objects neeed to import
        resources_db_list = pickle.load(open(os.path.join(db_dir, file_name), 'rb'))

        for resources in resources_db_list:
            if resources is None:
                continue
            if isinstance(resources, list):
                for resource in resources:
                    #In case if workoad/snapshod updating object values
                    #with their respective tenant id and user id using context
                    if file_name in ['workload_db', 'snapshot_db']:
                        tenantcontext = get_context(resource)
                    update_resource_list(tenantcontext, resource)
            else:
                if file_name in ['workload_db', 'snapshot_db']:
                    tenantcontext = get_context(resources)
                update_resource_list(tenantcontext,resources)

        #TODO: Uncomment the code for updating existing resources
        #DBSession.bulk_update_mappings(eval('models.%s' % (model_class)), resources_list_update)
        #DBSession.commit()
        #BSession.bulk_update_mappings(eval('models.%s' % (metadata_model_class)), resources_metadata_list_update)
        #BSession.commit()

        # Dump list of objects into the database.        
        DBSession.bulk_insert_mappings(eval('models.%s' % (model_class)), resources_list)
        DBSession.commit()
        DBSession.bulk_insert_mappings(eval('models.%s' % (metadata_model_class)), resources_metadata_list)
        DBSession.commit()

        # if workloads/config_workload then check for job schedule, if it's there then update it.
        if file_name in ['workload_db', 'config_workload_db']:
            for resource in resources_list:
                if file_name == 'workload_db':
                    workload = models.Workloads()
                    workload.update(resource)
                    workloads.append(workload)
                else:
                    workload = models.ConfigWorkloads()
                    workload.update(resource)

                # Check if job schedule is enable then add scheduler.
                if len(resource['jobschedule']) and \
                                pickle.loads(str(resource['jobschedule']))['enabled'] == True:
                    workload_api = workloadAPI.API()
                    workload_api.workload_add_scheduler_job(tenantcontext, pickle.loads(str(resource['jobschedule'])), workload,
                                                            is_config_backup=(file_name=='config_workload_db'))

    except Exception as ex:
        LOG.exception(ex)

def import_workload(cntx, workload_ids, new_version, upgrade=True):
    '''
    Read all json files for all workloads from all available NFS mounts
    and perform bulk insert in the database.
    '''
    try:
        # Create temporary folder to store JSON files.
        db_dir = tempfile.mkdtemp()

        del workloads[:]
        DBSession.autocommit = False
        failed_workloads = get_json_files(cntx, workload_ids, db_dir, upgrade)
        for resource_map in import_map:
            import_resources(cntx, resource_map, new_version, db_dir, upgrade)
        DBSession.autocommit = True
        return {'workloads':{'imported_workloads': workloads, 'failed_workloads': failed_workloads}}
    except Exception as ex:
        LOG.exception(ex)
        raise ex
    finally:
        #Remove temporary folder
        if os.path.exists(db_dir):
           shutil.rmtree(db_dir, ignore_errors=True)


