from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog
from workloadmgr import settings
from workloadmgr.vault import vault
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.openstack.common import jsonutils
from workloadmgr.openstack.common import timeutils
from workloadmgr import exception
import cPickle as pickle

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

db = WorkloadMgrDB().db

def upload_workload_db_entry(cntx, workload_id):
    parent = vault.get_workload_path({'workload_id': workload_id})
    workload_db = db.workload_get(cntx, workload_id)
    for kvpair in workload_db.metadata:
        if 'Password' in kvpair['key'] or 'password' in kvpair['key']:
            kvpair['value'] = '******'
    workload_json = jsonutils.dumps(workload_db)
    path = parent + "/workload_db"
    vault.put_object(path, workload_json)

    workload_vms_db = db.workload_vms_get(cntx, workload_id)
    workload_vms_json = jsonutils.dumps(workload_vms_db)
    path = parent + "/workload_vms_db"
    vault.put_object(path, workload_vms_json)

def upload_snapshot_db_entry(cntx, snapshot_id, snapshot_status = None):
    db = WorkloadMgrDB().db
    
    settings_db = db.setting_get_all(cntx)
    for setting in settings_db:
        if 'password' in setting.name.lower():
            setting.value = '******'
        for kvpair in setting.metadata:
            if 'Password' in kvpair['key'] or 'password' in kvpair['key']:
                kvpair['value'] = '******'
    settings_jason = jsonutils.dumps(settings_db)            
    path = vault.get_vault_data_directory() + "/settings_db"
    vault.put_object(path, settings_jason)

    snapshot = db.snapshot_get(cntx, snapshot_id, read_deleted='yes')
    if snapshot['data_deleted']:
        return
    parent = vault.get_workload_path({'workload_id': snapshot['workload_id']})

    workload_db = db.workload_get(cntx, snapshot['workload_id'])
    for kvpair in workload_db.metadata:
        if 'Password' in kvpair['key'] or 'password' in kvpair['key']:
            kvpair['value'] = '******'
    workload_json = jsonutils.dumps(workload_db)
    path = parent + "/workload_db"
    vault.put_object(path, workload_json)

    workload_vms_db = db.workload_vms_get(cntx, snapshot['workload_id'])
    workload_vms_json = jsonutils.dumps(workload_vms_db)
    path = parent + "/workload_vms_db"
    vault.put_object(path, workload_vms_json)

    snapshot_db = db.snapshot_get(cntx, snapshot['id'], read_deleted='yes')
    if snapshot_status:
        snapshot_db.status = snapshot_status 
    snapshot_json = jsonutils.dumps(snapshot_db)
    parent = vault.get_snapshot_path({'workload_id': snapshot['workload_id'], 'snapshot_id': snapshot['id']})
    path = parent + "/snapshot_db"
    # Add to the vault
    vault.put_object(path, snapshot_json)

    snapvms = db.snapshot_vms_get(cntx, snapshot['id'])
    snapvms_json = jsonutils.dumps(snapvms)
    path = parent + "/snapshot_vms_db"
    # Add to the vault
    vault.put_object(path, snapvms_json)

    resources = db.snapshot_resources_get(cntx, snapshot['id'])
    resources_json = jsonutils.dumps(resources)
    path = parent + "/resources_db"
    vault.put_object(path, resources_json)
    
    for res in resources:
        res_json = jsonutils.dumps(res, sort_keys=True, indent=2)

        vm_res_id = '/vm_res_id_%s' % (res['id'])
        for meta in res.metadata:
            if meta.key == "label":
                vm_res_id = '/vm_res_id_%s_%s' % (res['id'], meta.value)
                break
        if res.resource_type == "network" or \
            res.resource_type == "subnet" or \
            res.resource_type == "router" or \
            res.resource_type == "nic":
            path = parent + "/network" + vm_res_id + "/network_db"
            network = db.vm_network_resource_snaps_get(cntx, res.id)
            network_json = jsonutils.dumps(network)
            vault.put_object(path, network_json)
        elif res.resource_type == "disk":
            path = parent + "/vm_id_" + res.vm_id + vm_res_id.replace(' ','') + "/disk_db"
            disk = db.vm_disk_resource_snaps_get(cntx, res.id)
            disk_json = jsonutils.dumps(disk)
            vault.put_object(path, disk_json)
        elif res.resource_type == "securty_group":
            path = parent + "/securty_group" + vm_res_id + "/security_group_db"
            security_group = db.vm_security_group_rule_snaps_get(cntx, res.id)
            security_group_json = jsonutils.dumps(security_group)
            vault.put_object(path, security_group_json)


@autolog.log_method(logger=Logger)
def _remove_data(context, snapshot_id):
    snapshot_with_data = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    if snapshot_with_data.status != 'deleted':
        return;        
    if snapshot_with_data.data_deleted == True:
        return;
    try:
        LOG.info(_('Deleting the data of snapshot %s of workload %s') % (snapshot_with_data.id, snapshot_with_data.workload_id))
        workload_obj = db.workload_get(context, snapshot_with_data.workload_id)                            
        vault.snapshot_delete(context, {'workload_id': snapshot_with_data.workload_id, 'workload_name': workload_obj.display_name, 'snapshot_id': snapshot_with_data.id})
        db.snapshot_update(context, snapshot_with_data.id, {'data_deleted':True})
    except Exception as ex:
        LOG.exception(ex)
                  
@autolog.log_method(logger=Logger)    
def _snapshot_delete(context, snapshot_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')    
    db.snapshot_delete(context, snapshot.id)
        
    child_snapshots = db.get_snapshot_children(context, snapshot_id)
    all_child_snapshots_deleted = True
    for child_snapshot_id in child_snapshots:
        try:
            child_snapshot = db.snapshot_get(context, child_snapshot_id, read_deleted='yes')
            if child_snapshot.status == 'error' or child_snapshot.status == 'deleted':
                continue
            all_child_snapshots_deleted = False
            break
        except Exception as ex:
            LOG.exception(ex)
    
    if all_child_snapshots_deleted:
        _remove_data(context, snapshot_id)
    upload_snapshot_db_entry(context, snapshot_id) 
        
@autolog.log_method(logger=Logger)
def snapshot_delete(context, snapshot_id):
    """
    Delete an existing snapshot
    """
    _snapshot_delete(context, snapshot_id)
    
    child_snapshots = db.get_snapshot_children(context, snapshot_id)            
    for child_snapshot_id in child_snapshots:
        try:
            child_snapshot = db.snapshot_get(context, child_snapshot_id, read_deleted='yes')
            if child_snapshot.status == 'deleted' and child_snapshot.data_deleted == False:
                # now see if the data can be deleted
                _snapshot_delete(context, child_snapshot_id)
        except Exception as ex:
            LOG.exception(ex)

    parent_snapshots = db.get_snapshot_parents(context, snapshot_id)
    for parent_snapshot_id in parent_snapshots:
        try:
            parent_snapshot = db.snapshot_get(context, parent_snapshot_id, read_deleted='yes')
            if parent_snapshot.status == 'deleted' and parent_snapshot.data_deleted == False:
                # now see if the data can be deleted
                _snapshot_delete(context, parent_snapshot_id)
        except Exception as ex:
            LOG.exception(ex)

@autolog.log_method(logger=Logger)    
def delete_if_chain(context, snapshot, snapshots_to_delete):
    try:
        snapshots_to_delete_ids = set()
        for snapshot_to_delete in snapshots_to_delete:
            snapshots_to_delete_ids.add(snapshot_to_delete.id)
            
        snapshot_obj = db.snapshot_type_time_size_update(context, snapshot['id'])
        workload_obj = db.workload_get(context, snapshot_obj.workload_id)            
        snapshots_all = db.snapshot_get_all_by_project_workload(context, context.project_id, workload_obj.id, read_deleted='yes')
        
        snap_chains = []
        snap_chain = set()
        snap_chains.append(snap_chain)
        for snap in reversed(snapshots_all):
            if snap.snapshot_type == 'full':
                snap_chain = set()
                snap_chains.append(snap_chain)
            snap_chain.add(snap.id)
                
        for snap_chain in snap_chains:
            if snap_chain.issubset(snapshots_to_delete_ids):
                for snap in snap_chain:
                    db.snapshot_delete(context, snap)
                for snap in snap_chain:
                    _remove_data(context, snap)                    
                    
    except Exception as ex:
        LOG.exception(ex)                            

def download_snapshot_vm_from_object_store(context, restore_id, snapshot_id, snapshot_vm_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = db.workload_get(context, snapshot.workload_id)
     
    object_store_download_time = 0 
    object_store_download_time += vault.download_snapshot_vm_from_object_store(context,
                                                {'restore_id' : restore_id,
                                                 'workload_id': snapshot.workload_id,
                                                 'snapshot_id': snapshot.id,
                                                 'snapshot_vm_id': snapshot_vm_id})
    
    parent_snapshots = db.get_snapshot_parents(context, snapshot_id)
   
    for parent_snapshot_id in parent_snapshots:
        parent_snapshot_vms = db.snapshot_vms_get(context, parent_snapshot_id) 
        for parent_snapshot_vm in parent_snapshot_vms:
            if  parent_snapshot_vm.vm_id == snapshot_vm_id:
                object_store_download_time += vault.download_snapshot_vm_from_object_store(context,
                                                            {'restore_id' : restore_id,
                                                             'workload_id': snapshot.workload_id,
                                                             'workload_name': workload.display_name,
                                                             'snapshot_id': parent_snapshot_id,
                                                             'snapshot_vm_id': snapshot_vm_id}) 
    return object_store_download_time   
                
def download_snapshot_vm_resource_from_object_store(context, restore_id, snapshot_id, snapshot_vm_resource_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes') 
    workload = db.workload_get(context, snapshot.workload_id)   
    snapshot_vm_resource = db.snapshot_vm_resource_get(context, snapshot_vm_resource_id)
    snapshot_vm = db.snapshot_vm_get(context, snapshot_vm_resource.vm_id, snapshot.id)    

    object_store_download_time = 0
    while snapshot_vm_resource:
        object_store_download_time += vault.download_snapshot_vm_resource_from_object_store(context,
                                                              {'restore_id' : restore_id,
                                                               'workload_id': snapshot.workload_id,
                                                               'workload_name': workload.display_name,
                                                               'snapshot_id': snapshot_vm_resource.snapshot_id,
                                                               'snapshot_vm_id': snapshot_vm_resource.vm_id,
                                                               'snapshot_vm_name': snapshot_vm.vm_name,
                                                               'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                               'snapshot_vm_resource_name': snapshot_vm_resource.resource_name})
        vm_disk_resource_snaps = db.vm_disk_resource_snaps_get(context, snapshot_vm_resource.id)
        for vm_disk_resource_snap in vm_disk_resource_snaps:
            if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
                vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                if vm_disk_resource_snap_backing.snapshot_vm_resource_id != snapshot_vm_resource.id:
                    snapshot_vm_resource = db.snapshot_vm_resource_get(context, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                    break
            else:
                snapshot_vm_resource = None
                break
    return object_store_download_time
    
def purge_snapshot_vm_from_staging_area(context, snapshot_id, snapshot_vm_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')

    vault.purge_snapshot_vm_from_staging_area(context, {'workload_id': snapshot.workload_id,
                                                        'snapshot_id': snapshot_id,
                                                        'snapshot_vm_id': snapshot_vm_id})
    
    parent_snapshots = db.get_snapshot_parents(context, snapshot_id)
   
    for parent_snapshot_id in parent_snapshots:
        parent_snapshot_vms = db.snapshot_vms_get(context, parent_snapshot_id) 
        for parent_snapshot_vm in parent_snapshot_vms:
            if  parent_snapshot_vm.vm_id == snapshot_vm_id:
                vault.purge_snapshot_vm_from_staging_area(context, {'workload_id': snapshot.workload_id,
                                                                    'snapshot_id': parent_snapshot_id,
                                                                    'snapshot_vm_id': snapshot_vm_id})                               
               
def purge_snapshot_vm_resource_from_staging_area(context, snapshot_id, snapshot_vm_resource_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')    
    snapshot_vm_resource = db.snapshot_vm_resource_get(context, snapshot_vm_resource_id)
    snapshot_vm = db.snapshot_vm_get(context, snapshot_vm_resource.vm_id, snapshot.id)    

    while snapshot_vm_resource:
        vault.purge_snapshot_vm_resource_from_staging_area(context,{'workload_id': snapshot.workload_id,
                                                                    'snapshot_id': snapshot_vm_resource.snapshot_id,
                                                                    'snapshot_vm_id': snapshot_vm_resource.vm_id,
                                                                    'snapshot_vm_name': snapshot_vm.vm_name,
                                                                    'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                                    'snapshot_vm_resource_name': snapshot_vm_resource.resource_name})
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(context, snapshot_vm_resource.id)
        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
            vm_disk_resource_snap = db.vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            snapshot_vm_resource = db.snapshot_vm_resource_get(context, vm_disk_resource_snap.snapshot_vm_resource_id)
        else:
            snapshot_vm_resource = None
            
def purge_restore_vm_from_staging_area(context, restore_id, snapshot_id, snapshot_vm_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    vault.purge_restore_vm_from_staging_area(context, { 'restore_id': restore_id,
                                                        'workload_id': snapshot.workload_id,
                                                        'snapshot_id': snapshot_id,
                                                        'snapshot_vm_id': snapshot_vm_id})
    """
    parent_snapshots = db.get_snapshot_parents(context, snapshot_id)
   
    for parent_snapshot_id in parent_snapshots:
        parent_snapshot_vms = db.snapshot_vms_get(context, parent_snapshot_id) 
        for parent_snapshot_vm in parent_snapshot_vms:
            if  parent_snapshot_vm.vm_id == snapshot_vm_id:
                vault.purge_restore_vm_from_staging_area(context, { 'restore_id': restore_id, 
                                                                    'workload_id': snapshot.workload_id,
                                                                    'snapshot_id': parent_snapshot_id,
                                                                    'snapshot_vm_id': snapshot_vm_id})
    """                               
               
def purge_restore_vm_resource_from_staging_area(context, restore_id, snapshot_id, snapshot_vm_resource_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')    
    snapshot_vm_resource = db.snapshot_vm_resource_get(context, snapshot_vm_resource_id)
    snapshot_vm = db.snapshot_vm_get(context, snapshot_vm_resource.vm_id, snapshot.id)    

    while snapshot_vm_resource:
        vault.purge_restore_vm_resource_from_staging_area(context,{ 'restore_id': restore_id,
                                                                    'workload_id': snapshot.workload_id,
                                                                    'snapshot_id': snapshot_vm_resource.snapshot_id,
                                                                    'snapshot_vm_id': snapshot_vm_resource.vm_id,
                                                                    'snapshot_vm_name': snapshot_vm.vm_name,
                                                                    'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                                    'snapshot_vm_resource_name': snapshot_vm_resource.resource_name})
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(context, snapshot_vm_resource.id)
        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
            vm_disk_resource_snap = db.vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            snapshot_vm_resource = db.snapshot_vm_resource_get(context, vm_disk_resource_snap.snapshot_vm_resource_id)
        else:
            snapshot_vm_resource = None

def common_apply_retention_policy(cntx, instances, snapshot): 
        
    def _delete_deleted_snap_chains(cntx, snapshot):
        try:
            snapshot_obj = db.snapshot_type_time_size_update(cntx, snapshot['id'])
            workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)            
            snapshots_all = db.snapshot_get_all_by_project_workload(cntx, cntx.project_id, workload_obj.id, read_deleted='yes')
                
            snap_chains = []
            snap_chain = []
            snap_chains.append(snap_chain)
            for snap in reversed(snapshots_all):
                if snap.snapshot_type == 'full':
                    snap_chain = []
                    snap_chains.append(snap_chain)
                    snap_chain.append(snap)
                        
            deleted_snap_chains = []        
            for snap_chain in snap_chains:
                deleted_chain = True
                for snap in snap_chain:
                    if snap.status != 'deleted':
                        deleted_chain = False
                        break
                if deleted_chain == True:
                    deleted_snap_chains.append(snap_chain)
                
            for snap_chain in deleted_snap_chains:
                for snap in snap_chain:
                    if snap.deleted == True and snap.data_deleted == False:
                        LOG.info(_('Deleting the data of snapshot %s %s %s of workload %s') % ( snap.display_name, 
                                                                                                snap.id,
                                                                                                snap.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                                                                                                workload_obj.display_name ))
                        db.snapshot_update(cntx, snap.id, {'data_deleted':True})
                        vault.snapshot_delete(cntx, {'workload_id': snap.workload_id, 'workload_name': workload_obj.display_name, 'snapshot_id': snap.id})
        except Exception as ex:
                LOG.exception(ex)
                
    try:
        db.snapshot_update(cntx, snapshot['id'],{'progress_msg': 'Applying retention policy','status': 'executing'})
        _delete_deleted_snap_chains(cntx, snapshot)
        affected_snapshots = []             
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)

        retention_policy_type = pickle.loads(str(workload_obj.jobschedule))['retention_policy_type']
        retention_policy_value = pickle.loads(str(workload_obj.jobschedule))['retention_policy_value']
        snapshots_to_keep = {'number': -1, 'days': -1 }
        if retention_policy_type == 'Number of Snapshots to Keep':
            snapshots_to_keep['number'] = int(retention_policy_value)
            if snapshots_to_keep['number'] <= 0:
                snapshots_to_keep['number'] = 1
        elif retention_policy_type == 'Number of days to retain Snapshots':    
            snapshots_to_keep['days'] = int(retention_policy_value)
            if snapshots_to_keep['days'] <= 0:
                snapshots_to_keep['days'] = 1            
        
        snapshots_all = db.snapshot_get_all_by_project_workload(cntx, cntx.project_id, workload_obj.id, read_deleted='yes')
        snapshots_valid = []
        snapshots_valid.append(snapshot_obj)
        for snap in snapshots_all:
            if snapshots_valid[0].id == snap.id:
                continue
            if snap.status == 'available':
                snapshots_valid.append(snap)
            elif snap.status == 'deleted' and snap.data_deleted == False:
                snapshots_valid.append(snap)
 
        snapshot_to_commit = None
        snapshots_to_delete = set()
        retained_snap_count = 0
        for idx, snap in enumerate(snapshots_valid):
            if snapshots_to_keep['number'] == -1:
                if (timeutils.utcnow() - snap.created_at).days <  snapshots_to_keep['days']:    
                    retained_snap_count = retained_snap_count + 1
                else:
                    if snapshot_to_commit == None:
                        snapshot_to_commit = snapshots_valid[idx-1]
                    snapshots_to_delete.add(snap)    
            else:
                if retained_snap_count < snapshots_to_keep['number']:
                    if snap.status == 'deleted':
                        continue                            
                    else:
                        retained_snap_count = retained_snap_count + 1
                else:
                    if snapshot_to_commit == None:
                        snapshot_to_commit = snapshots_valid[idx-1]
                    snapshots_to_delete.add(snap)
            
        if vault.commit_supported() == False:
            delete_if_chain(cntx, snapshot, snapshots_to_delete)
            return (snapshot_to_commit, snapshots_to_delete, affected_snapshots, workload_obj, snapshot_obj, 0)

        return (snapshot_to_commit, snapshots_to_delete, affected_snapshots, workload_obj, snapshot_obj, 1)

    except Exception as ex:
        LOG.exception(ex)
        raise ex       

def common_apply_retention_disk_check(cntx, snapshot_to_commit, snap, workload_obj):
    def _snapshot_disks_deleted(snap):
        try:
            all_disks_deleted = True
            some_disks_deleted = False
            snapshot_vm_resources = db.snapshot_resources_get(cntx, snap.id)
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type != 'disk':
                    continue
                if snapshot_vm_resource.status != 'deleted':
                    all_disks_deleted = False
                else:
                    some_disks_deleted = True
            return all_disks_deleted, some_disks_deleted 
        except exception.SnapshotVMResourcesNotFound as ex:
            LOG.exception(ex)
            return False,True

    db.snapshot_type_time_size_update(cntx, snapshot_to_commit.id)
    
    all_disks_deleted, some_disks_deleted = _snapshot_disks_deleted(snap)
    if some_disks_deleted:
        db.snapshot_delete(cntx, snap.id)
    if all_disks_deleted: 
        db.snapshot_delete(cntx, snap.id)
        db.snapshot_update(cntx, snap.id, {'data_deleted':True})
        try:
            LOG.info(_('Deleting the data of snapshot %s %s %s of workload %s') % ( snap.display_name, 
                                                                                    snap.id,
                                                                                    snap.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                                                                                    workload_obj.display_name ))                            
            vault.snapshot_delete(cntx, {'workload_id': snap.workload_id, 'workload_name': workload_obj.display_name, 'snapshot_id': snap.id})
        except Exception as ex:
            LOG.exception(ex)

def common_apply_retention_snap_delete(cntx, snap, workload_obj):
    db.snapshot_delete(cntx, snap.id)
    if snap.data_deleted == False:
        db.snapshot_update(cntx, snap.id, {'data_deleted':True})
        try:
            LOG.info(_('Deleting the data of snapshot %s %s %s of workload %s') % ( snap.display_name, 
                                                                                    snap.id,
                                                                                    snap.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                                                                                    workload_obj.display_name ))                            
            vault.snapshot_delete(cntx, {'workload_id': snap.workload_id, 'workload_name': workload_obj.display_name, 'snapshot_id': snap.id})
        except Exception as ex:
            LOG.exception(ex)   

def common_apply_retention_db_backing_update(cntx, snapshot_vm_resource, vm_disk_resource_snap, vm_disk_resource_snap_backing, affected_snapshots):
    vm_disk_resource_snap_values = {'size' : vm_disk_resource_snap_backing.size, 
                                    'vm_disk_resource_snap_backing_id' : vm_disk_resource_snap_backing.vm_disk_resource_snap_backing_id
                                   }
    db.vm_disk_resource_snap_update(cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
                            
    snapshot_vm_resource_backing = db.snapshot_vm_resource_get(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
    snapshot_vm_resource_values = {'size' : snapshot_vm_resource_backing.size, 
                                   'snapshot_type' : snapshot_vm_resource_backing.snapshot_type,
                                   'time_taken': snapshot_vm_resource_backing.time_taken}
                            
    db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, snapshot_vm_resource_values)
    db.vm_disk_resource_snap_delete(cntx, vm_disk_resource_snap_backing.id)
    db.snapshot_vm_resource_delete(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
    snapshot_vm_resource_backing = db.snapshot_vm_resource_get(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
    if snapshot_vm_resource_backing.snapshot_id not in affected_snapshots:
        affected_snapshots.append(snapshot_vm_resource_backing.snapshot_id)

    return affected_snapshots
