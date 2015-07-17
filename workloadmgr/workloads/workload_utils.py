from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog
from workloadmgr import settings
from workloadmgr.vault import vault
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.openstack.common import jsonutils

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

db = WorkloadMgrDB().db

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
    path = vault.get_vault_local_directory() + "/settings_db"
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
        vault.snapshot_delete({'workload_id': snapshot_with_data.workload_id, 'workload_name': workload_obj.display_name, 'snapshot_id': snapshot_with_data.id})
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
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(context, snapshot_vm_resource.id)
        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
            vm_disk_resource_snap = db.vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            snapshot_vm_resource = db.snapshot_vm_resource_get(context, vm_disk_resource_snap.snapshot_vm_resource_id)
        else:
            snapshot_vm_resource = None
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
