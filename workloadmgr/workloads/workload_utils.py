import os
import json

from oslo.config import cfg

from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog
from workloadmgr import flags
from workloadmgr import settings
from workloadmgr.vault import vault
from workloadmgr.compute import nova
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.openstack.common import jsonutils
from workloadmgr.openstack.common import timeutils
from workloadmgr import exception
from workloadmgr.common.workloadmgr_keystoneclient import KeystoneClientBase
import cPickle as pickle

workloads_manager_opts = [
    cfg.StrOpt('cloud_unique_id',
               default='test-cloud-id',
               help='cloud unique id.'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(workloads_manager_opts)

CONF = cfg.CONF

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

db = WorkloadMgrDB().db


def upload_settings_db_entry(cntx):
    # use context as none since we want settings of all users/tenants
    # TODO: implement settings persistance per user/tenant
    (backup_target, path) = vault.get_settings_backup_target()

    settings_db = db.setting_get_all(
        None, read_deleted='no', backup_settings=True)
    for setting in settings_db:
        if 'password' in setting.name.lower():
            setting.value = '******'
        for kvpair in setting.metadata:
            if 'Password' in kvpair['key'] or 'password' in kvpair['key']:
                kvpair['value'] = '******'

    settings_json = jsonutils.dumps(settings_db)
    settings_path = os.path.join(str(CONF.cloud_unique_id), "settings_db")
    db_settings = json.loads(settings_json)
    db_settings_keys = [setting['type'] for setting in db_settings]

    try:
        backend_settings = json.loads(backup_target.get_object(settings_path))
    except Exception as ex:
        backend_settings = []
    backend_settings_keys = [setting['type'] for setting in backend_settings]

    # If on the backend we have more settings than DB means we havn't
    # imported them yet, In that case appending DB settings with backend settings.
    if len(backend_settings) > len(db_settings) or len(list(set(db_settings_keys) - set(backend_settings_keys))):
        for setting in backend_settings:
            if setting['type'] in db_settings_keys:
                backend_settings.remove(setting)

        db_settings.extend(backend_settings)
    db_settings = json.dumps(db_settings)
    backup_target.put_object(settings_path, db_settings)


def upload_workload_db_entry(cntx, workload_id):
    upload_settings_db_entry(cntx)

    workload_db = db.workload_get(cntx, workload_id)
    backup_endpoint = db.get_metadata_value(workload_db.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)
    parent = backup_target.get_workload_path({'workload_id': workload_id})

    for kvpair in workload_db.metadata:
        if 'Password' in kvpair['key'] or 'password' in kvpair['key']:
            kvpair['value'] = '******'
    workload_json = jsonutils.dumps(workload_db)
    path = os.path.join(parent, "workload_db")
    backup_target.put_object(path, workload_json)

    workload_vms_db = db.workload_vms_get(cntx, workload_id)
    workload_vms_json = jsonutils.dumps(workload_vms_db)
    path = os.path.join(parent, "workload_vms_db")
    backup_target.put_object(path, workload_vms_json)


def upload_snapshot_db_entry(cntx, snapshot_id, snapshot_status=None):
    upload_settings_db_entry(cntx)

    snapshot = db.snapshot_get(cntx, snapshot_id, read_deleted='yes')
    if snapshot['data_deleted']:
        return

    workload_id = snapshot['workload_id']
    workload_db = db.workload_get(cntx, workload_id)
    backup_endpoint = db.get_metadata_value(workload_db.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)

    parent = backup_target.get_workload_path({'workload_id': workload_id})

    for kvpair in workload_db.metadata:
        if 'Password' in kvpair['key'] or 'password' in kvpair['key']:
            kvpair['value'] = '******'
    workload_json = jsonutils.dumps(workload_db)

    path = os.path.join(parent, "workload_db")
    backup_target.put_object(path, workload_json)

    workload_vms_db = db.workload_vms_get(cntx, snapshot['workload_id'])
    workload_vms_json = jsonutils.dumps(workload_vms_db)
    path = os.path.join(parent, "workload_vms_db")
    backup_target.put_object(path, workload_vms_json)

    snapshot_db = db.snapshot_get(cntx, snapshot['id'], read_deleted='yes')
    if snapshot_status:
        snapshot_db.status = snapshot_status
    snapshot_json = jsonutils.dumps(snapshot_db)
    parent = backup_target.get_snapshot_path({'workload_id': workload_id,
                                              'snapshot_id': snapshot['id']})
    path = os.path.join(parent, "snapshot_db")
    # Add to the vault
    backup_target.put_object(path, snapshot_json)

    snapvms = db.snapshot_vms_get(cntx, snapshot['id'])
    snapvms_json = jsonutils.dumps(snapvms)
    path = os.path.join(parent, "snapshot_vms_db")

    # Add to the vault
    backup_target.put_object(path, snapvms_json)

    resources = db.snapshot_resources_get(cntx, snapshot['id'])
    resources_json = jsonutils.dumps(resources)
    path = os.path.join(parent, "resources_db")
    backup_target.put_object(path, resources_json)

    for res in resources:
        res_json = jsonutils.dumps(res, sort_keys=True, indent=2)

        vm_res_id = 'vm_res_id_%s' % (res['id'])
        for meta in res.metadata:
            if meta.key == "label":
                vm_res_id = 'vm_res_id_%s_%s' % (res['id'], meta.value)
                break
        if res.resource_type == "network" or \
                res.resource_type == "subnet" or \
                res.resource_type == "router" or \
                res.resource_type == "nic":
            path = os.path.join(parent, "network", vm_res_id, "network_db")
            network = db.vm_network_resource_snaps_get(cntx, res.id)
            network_json = jsonutils.dumps(network)
            backup_target.put_object(path, network_json)
        elif res.resource_type == "disk":
            path = os.path.join(
                parent,
                "vm_id_" +
                res.vm_id,
                vm_res_id.replace(
                    ' ',
                    ''),
                "disk_db")
            disk = db.vm_disk_resource_snaps_get(cntx, res.id)
            disk_json = jsonutils.dumps(disk)
            backup_target.put_object(path, disk_json)
        elif res.resource_type == "security_group":
            path = os.path.join(
                parent,
                "security_group",
                vm_res_id,
                "security_group_db")
            security_group = db.vm_security_group_rule_snaps_get(cntx, res.id)
            security_group_json = jsonutils.dumps(security_group)
            backup_target.put_object(path, security_group_json)


def upload_config_workload_db_entry(cntx):
    try:
        config_workload_db = db.config_workload_get(cntx)
        backup_endpoint = config_workload_db['backup_media_target']
        backup_target = vault.get_backup_target(backup_endpoint)
        config_workload_storage_path = backup_target.get_config_workload_path()

        config_workload_json = jsonutils.dumps(config_workload_db)

        path = os.path.join(config_workload_storage_path, "config_workload_db")
        backup_target.put_object(path, config_workload_json)
    except Exception as ex:
        LOG.exception(ex)


def upload_config_backup_db_entry(cntx, backup_id):
    try:
        config_db = db.config_backup_get(cntx, backup_id)
        config_workload_db = db.config_workload_get(cntx)
        backup_endpoint = config_workload_db['backup_media_target']

        backup_target = vault.get_backup_target(backup_endpoint)
        parent = config_db['vault_storage_path']

        config_json = jsonutils.dumps(config_db)
        path = os.path.join(parent, "config_backup_db")
        backup_target.put_object(path, config_json)
    except Exception as ex:
        LOG.exception(ex)


@autolog.log_method(logger=Logger)
def _remove_data(context, snapshot_id):
    snapshot_with_data = db.snapshot_get(
        context, snapshot_id, read_deleted='yes')
    if snapshot_with_data.status != 'deleted':
        return
    if snapshot_with_data.data_deleted:
        return
    try:
        LOG.info(_('Deleting the data of snapshot %s of workload %s') %
                 (snapshot_with_data.id, snapshot_with_data.workload_id))
        workload_obj = db.workload_get(context, snapshot_with_data.workload_id)
        backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                'backup_media_target')

        backup_target = vault.get_backup_target(backup_endpoint)
        backup_target.snapshot_delete(context,
                                      {'workload_id': snapshot_with_data.workload_id,
                                       'workload_name': workload_obj.display_name,
                                       'snapshot_id': snapshot_with_data.id})
        db.snapshot_update(
            context, snapshot_with_data.id, {
                'data_deleted': True})
    except Exception as ex:
        LOG.exception(ex)


@autolog.log_method(logger=Logger)
def _snapshot_delete(context, snapshot_id, database_only=False):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    db.snapshot_delete(context, snapshot.id)

    child_snapshots = db.get_snapshot_children(context, snapshot_id)
    all_child_snapshots_deleted = True
    for child_snapshot_id in child_snapshots:
        try:
            child_snapshot = db.snapshot_get(
                context, child_snapshot_id, read_deleted='yes')
            if child_snapshot.status == 'error' or child_snapshot.status == 'deleted':
                continue
            all_child_snapshots_deleted = False
            break
        except Exception as ex:
            LOG.exception(ex)
    if all_child_snapshots_deleted and database_only is False:
        _remove_data(context, snapshot_id)
    if database_only is False:
        upload_snapshot_db_entry(context, snapshot_id)


@autolog.log_method(logger=Logger)
def snapshot_delete(context, snapshot_id, database_only=False):
    """
    Delete an existing snapshot
    """
    _snapshot_delete(context, snapshot_id, database_only)

    child_snapshots = db.get_snapshot_children(context, snapshot_id)
    for child_snapshot_id in child_snapshots:
        try:
            child_snapshot = db.snapshot_get(
                context, child_snapshot_id, read_deleted='yes')
            if child_snapshot.status == 'deleted' and child_snapshot.data_deleted == False:
                # now see if the data can be deleted
                _snapshot_delete(context, child_snapshot_id, database_only)
        except Exception as ex:
            LOG.exception(ex)

    parent_snapshots = db.get_snapshot_parents(context, snapshot_id)
    for parent_snapshot_id in parent_snapshots:
        try:
            parent_snapshot = db.snapshot_get(
                context, parent_snapshot_id, read_deleted='yes')
            if parent_snapshot.status == 'deleted' and parent_snapshot.data_deleted == False:
                # now see if the data can be deleted
                _snapshot_delete(context, parent_snapshot_id, database_only)
        except Exception as ex:
            LOG.exception(ex)


@autolog.log_method(logger=Logger)
def delete_if_chain(context, snapshot, snapshots_to_delete):
    try:
        snapshots_to_delete_ids = set()
        for snapshot_to_delete in snapshots_to_delete:
            snapshots_to_delete_ids.add(snapshot_to_delete.id)

        snapshot_obj = db.snapshot_type_time_size_update(
            context, snapshot['id'])
        workload_obj = db.workload_get(context, snapshot_obj.workload_id)
        snapshots_all = db.snapshot_get_all_by_project_workload(
            context, context.project_id, workload_obj.id, read_deleted='yes')

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


def download_snapshot_vm_from_object_store(
        context, restore_id, snapshot_id, snapshot_vm_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = db.workload_get(context, snapshot.workload_id)

    object_store_download_time = 0
    object_store_download_time += vault.download_snapshot_vm_from_object_store(
        context,
        {
            'restore_id': restore_id,
            'workload_id': snapshot.workload_id,
            'snapshot_id': snapshot.id,
            'snapshot_vm_id': snapshot_vm_id})

    parent_snapshots = db.get_snapshot_parents(context, snapshot_id)

    for parent_snapshot_id in parent_snapshots:
        parent_snapshot_vms = db.snapshot_vms_get(context, parent_snapshot_id)
        for parent_snapshot_vm in parent_snapshot_vms:
            if parent_snapshot_vm.vm_id == snapshot_vm_id:
                object_store_download_time += vault.download_snapshot_vm_from_object_store(
                    context,
                    {
                        'restore_id': restore_id,
                        'workload_id': snapshot.workload_id,
                        'workload_name': workload.display_name,
                        'snapshot_id': parent_snapshot_id,
                        'snapshot_vm_id': snapshot_vm_id})
    return object_store_download_time


def download_snapshot_vm_resource_from_object_store(
        context, restore_id, snapshot_id, snapshot_vm_resource_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = db.workload_get(context, snapshot.workload_id)
    snapshot_vm_resource = db.snapshot_vm_resource_get(
        context, snapshot_vm_resource_id)
    snapshot_vm = db.snapshot_vm_get(
        context, snapshot_vm_resource.vm_id, snapshot.id)

    object_store_download_time = 0
    while snapshot_vm_resource:
        object_store_download_time += vault.download_snapshot_vm_resource_from_object_store(
            context,
            {
                'restore_id': restore_id,
                'workload_id': snapshot.workload_id,
                'workload_name': workload.display_name,
                'snapshot_id': snapshot_vm_resource.snapshot_id,
                'snapshot_vm_id': snapshot_vm_resource.vm_id,
                'snapshot_vm_name': snapshot_vm.vm_name,
                'snapshot_vm_resource_id': snapshot_vm_resource.id,
                'snapshot_vm_resource_name': snapshot_vm_resource.resource_name})
        vm_disk_resource_snaps = db.vm_disk_resource_snaps_get(
            context, snapshot_vm_resource.id)
        for vm_disk_resource_snap in vm_disk_resource_snaps:
            if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
                vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(
                    context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                if vm_disk_resource_snap_backing.snapshot_vm_resource_id != snapshot_vm_resource.id:
                    snapshot_vm_resource = db.snapshot_vm_resource_get(
                        context, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                    break
            else:
                snapshot_vm_resource = None
                break
    return object_store_download_time


def purge_snapshot_vm_from_staging_area(context, snapshot_id, snapshot_vm_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = db.workload_get(context, snapshot.workload_id)
    backup_endpoint = db.get_metadata_value(workload.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)

    backup_target.purge_snapshot_vm_from_staging_area(
        context,
        {
            'workload_id': snapshot.workload_id,
            'snapshot_id': snapshot_id,
            'snapshot_vm_id': snapshot_vm_id})

    parent_snapshots = db.get_snapshot_parents(context, snapshot_id)

    for parent_snapshot_id in parent_snapshots:
        parent_snapshot_vms = db.snapshot_vms_get(context, parent_snapshot_id)
        for parent_snapshot_vm in parent_snapshot_vms:
            if parent_snapshot_vm.vm_id == snapshot_vm_id:
                backup_target.purge_snapshot_vm_from_staging_area(
                    context,
                    {
                        'workload_id': snapshot.workload_id,
                        'snapshot_id': parent_snapshot_id,
                        'snapshot_vm_id': snapshot_vm_id})


def purge_snapshot_vm_resource_from_staging_area(
        context, snapshot_id, snapshot_vm_resource_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = db.workload_get(context, snapshot.workload_id)
    backup_endpoint = db.get_metadata_value(workload.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)
    snapshot_vm_resource = db.snapshot_vm_resource_get(
        context, snapshot_vm_resource_id)
    snapshot_vm = db.snapshot_vm_get(
        context, snapshot_vm_resource.vm_id, snapshot.id)

    while snapshot_vm_resource:
        backup_target.purge_snapshot_vm_resource_from_staging_area(
            context,
            {
                'workload_id': snapshot.workload_id,
                'snapshot_id': snapshot_vm_resource.snapshot_id,
                'snapshot_vm_id': snapshot_vm_resource.vm_id,
                'snapshot_vm_name': snapshot_vm.vm_name,
                'snapshot_vm_resource_id': snapshot_vm_resource.id,
                'snapshot_vm_resource_name': snapshot_vm_resource.resource_name})
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(
            context, snapshot_vm_resource.id)
        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
            vm_disk_resource_snap = db.vm_disk_resource_snap_get(
                context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            snapshot_vm_resource = db.snapshot_vm_resource_get(
                context, vm_disk_resource_snap.snapshot_vm_resource_id)
        else:
            snapshot_vm_resource = None


def purge_restore_vm_from_staging_area(
        context, restore_id, snapshot_id, snapshot_vm_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = db.workload_get(context, snapshot.workload_id)
    backup_endpoint = db.get_metadata_value(workload.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)
    backup_target.purge_restore_vm_from_staging_area(
        context,
        {
            'restore_id': restore_id,
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


def purge_restore_vm_resource_from_staging_area(
        context, restore_id, snapshot_id, snapshot_vm_resource_id):
    snapshot = db.snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = db.workload_get(context, snapshot.workload_id)
    backup_endpoint = db.get_metadata_value(workload.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)
    snapshot_vm_resource = db.snapshot_vm_resource_get(
        context, snapshot_vm_resource_id)
    snapshot_vm = db.snapshot_vm_get(
        context, snapshot_vm_resource.vm_id, snapshot.id)

    while snapshot_vm_resource:
        backup_target.purge_restore_vm_resource_from_staging_area(
            context,
            {
                'restore_id': restore_id,
                'workload_id': snapshot.workload_id,
                'snapshot_id': snapshot_vm_resource.snapshot_id,
                'snapshot_vm_id': snapshot_vm_resource.vm_id,
                'snapshot_vm_name': snapshot_vm.vm_name,
                'snapshot_vm_resource_id': snapshot_vm_resource.id,
                'snapshot_vm_resource_name': snapshot_vm_resource.resource_name})
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(
            context, snapshot_vm_resource.id)
        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
            vm_disk_resource_snap = db.vm_disk_resource_snap_get(
                context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            snapshot_vm_resource = db.snapshot_vm_resource_get(
                context, vm_disk_resource_snap.snapshot_vm_resource_id)
        else:
            snapshot_vm_resource = None


def common_apply_retention_policy(cntx, instances, snapshot):

    def _delete_deleted_snap_chains(cntx, snapshot):
        try:
            snapshot_obj = db.snapshot_type_time_size_update(
                cntx, snapshot['id'])
            workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)

            backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                    'backup_media_target')
            backup_target = vault.get_backup_target(backup_endpoint)

            snapshots_all = db.snapshot_get_all_by_project_workload(
                cntx, cntx.project_id, workload_obj.id, read_deleted='yes')

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
                if deleted_chain:
                    deleted_snap_chains.append(snap_chain)

            for snap_chain in deleted_snap_chains:
                for snap in snap_chain:
                    if snap.deleted and snap.data_deleted == False:
                        LOG.info(
                            _('Deleting the data of snapshot %s %s %s of workload %s') %
                            (snap.display_name,
                             snap.id,
                             snap.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                             workload_obj.display_name))
                        db.snapshot_update(
                            cntx, snap.id, {
                                'data_deleted': True})
                        backup_target.snapshot_delete(cntx,
                                                      {'workload_id': snap.workload_id,
                                                       'workload_name': workload_obj.display_name,
                                                       'snapshot_id': snap.id})
        except Exception as ex:
            LOG.exception(ex)

    try:
        db.snapshot_update(
            cntx, snapshot['id'], {
                'progress_msg': 'Applying retention policy', 'status': 'executing'})
        _delete_deleted_snap_chains(cntx, snapshot)
        affected_snapshots = []
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                'backup_media_target')
        backup_target = vault.get_backup_target(backup_endpoint)

        retention_policy_type = pickle.loads(str(workload_obj.jobschedule))[
            'retention_policy_type']
        retention_policy_value = pickle.loads(str(workload_obj.jobschedule))[
            'retention_policy_value']
        snapshots_to_keep = {'number': -1, 'days': -1}
        if retention_policy_type == 'Number of Snapshots to Keep':
            snapshots_to_keep['number'] = int(retention_policy_value)
            if snapshots_to_keep['number'] <= 0:
                snapshots_to_keep['number'] = 1
        elif retention_policy_type == 'Number of days to retain Snapshots':
            snapshots_to_keep['days'] = int(retention_policy_value)
            if snapshots_to_keep['days'] <= 0:
                snapshots_to_keep['days'] = 1

        snapshots_all = db.snapshot_get_all_by_project_workload(
            cntx, cntx.project_id, workload_obj.id, read_deleted='yes')
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
                if (timeutils.utcnow() -
                        snap.created_at).days < snapshots_to_keep['days']:
                    retained_snap_count = retained_snap_count + 1
                else:
                    if snapshot_to_commit is None:
                        snapshot_to_commit = snapshots_valid[idx - 1]
                    snapshots_to_delete.add(snap)
            else:
                if retained_snap_count < snapshots_to_keep['number']:
                    if snap.status == 'deleted':
                        continue
                    else:
                        retained_snap_count = retained_snap_count + 1
                else:
                    if snapshot_to_commit is None:
                        snapshot_to_commit = snapshots_valid[idx - 1]
                    snapshots_to_delete.add(snap)

        if backup_target.commit_supported() == False:
            delete_if_chain(cntx, snapshot, snapshots_to_delete)
            return (snapshot_to_commit, snapshots_to_delete,
                    affected_snapshots, workload_obj, snapshot_obj, 0)

        return (snapshot_to_commit, snapshots_to_delete,
                affected_snapshots, workload_obj, snapshot_obj, 1)

    except Exception as ex:
        LOG.exception(ex)
        raise ex


def common_apply_retention_disk_check(
        cntx, snapshot_to_commit, snap, workload_obj):
    def _snapshot_disks_deleted(snap):
        try:
            all_disks_deleted = True
            some_disks_deleted = False
            snapshot_vm_resources = db.snapshot_resources_get(cntx, snap.id)
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type != 'disk':
                    continue
                if snapshot_vm_resource.snapshot_type == 'full' and \
                   snapshot_vm_resource.status != 'deleted' and all_disks_deleted:
                    db.snapshot_vm_resource_delete(
                        cntx, snapshot_vm_resource.id)
                    continue
                if snapshot_vm_resource.status != 'deleted':
                    all_disks_deleted = False
                else:
                    some_disks_deleted = True
            return all_disks_deleted, some_disks_deleted
        except exception.SnapshotVMResourcesNotFound as ex:
            LOG.exception(ex)
            return False, True

    db.snapshot_type_time_size_update(cntx, snapshot_to_commit.id)
    backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                            'backup_media_target')
    backup_target = vault.get_backup_target(backup_endpoint)

    all_disks_deleted, some_disks_deleted = _snapshot_disks_deleted(snap)
    if some_disks_deleted:
        db.snapshot_delete(cntx, snap.id)
    if all_disks_deleted:
        db.snapshot_delete(cntx, snap.id)
        db.snapshot_update(cntx, snap.id, {'data_deleted': True})
        try:
            LOG.info(
                _('Deleting the data of snapshot %s %s %s of workload %s') %
                (snap.display_name,
                 snap.id,
                 snap.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                 workload_obj.display_name))
            backup_target.snapshot_delete(cntx,
                                          {'workload_id': snap.workload_id,
                                           'workload_name': workload_obj.display_name,
                                           'snapshot_id': snap.id})
        except Exception as ex:
            LOG.exception(ex)


def common_apply_retention_snap_delete(cntx, snap, workload_obj):
    db.snapshot_delete(cntx, snap.id)
    backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                            'backup_media_target')
    backup_target = vault.get_backup_target(backup_endpoint)
    if not snap.data_deleted:
        db.snapshot_update(cntx, snap.id, {'data_deleted': True})
        try:
            LOG.info(
                _('Deleting the data of snapshot %s %s %s of workload %s') %
                (snap.display_name,
                 snap.id,
                 snap.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                 workload_obj.display_name))
            backup_target.snapshot_delete(cntx,
                                          {'workload_id': snap.workload_id,
                                           'workload_name': workload_obj.display_name,
                                           'snapshot_id': snap.id})
        except Exception as ex:
            LOG.exception(ex)


def common_apply_retention_db_backing_update(cntx, snapshot_vm_resource,
                                             vm_disk_resource_snap,
                                             vm_disk_resource_snap_backing,
                                             affected_snapshots):
    vm_disk_resource_snap_values = {
        'size': vm_disk_resource_snap_backing.size,
        'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing.vm_disk_resource_snap_backing_id}
    db.vm_disk_resource_snap_update(
        cntx,
        vm_disk_resource_snap.id,
        vm_disk_resource_snap_values)

    snapshot_vm_resource_backing = db.snapshot_vm_resource_get(
        cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
    snapshot_vm_resource_values = {
        'size': snapshot_vm_resource_backing.size,
        'snapshot_type': snapshot_vm_resource_backing.snapshot_type,
        'time_taken': snapshot_vm_resource_backing.time_taken}

    db.snapshot_vm_resource_update(
        cntx,
        snapshot_vm_resource.id,
        snapshot_vm_resource_values)
    db.vm_disk_resource_snap_delete(cntx, vm_disk_resource_snap_backing.id)
    db.snapshot_vm_resource_delete(
        cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
    snapshot_vm_resource_backing = db.snapshot_vm_resource_get(
        cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
    if snapshot_vm_resource_backing.snapshot_id not in affected_snapshots:
        affected_snapshots.append(snapshot_vm_resource_backing.snapshot_id)

    return affected_snapshots


@autolog.log_method(logger=Logger)
def _remove_config_backup_data(context, backup_id):
    try:
        LOG.info(_('Deleting the data of config backup %s ') % (backup_id))
        config_workload_obj = db.config_workload_get(context)
        backup_endpoint = config_workload_obj['backup_media_target']
        backup_target = vault.get_backup_target(backup_endpoint)
        backup_target.config_backup_delete(context, backup_id)
    except Exception as ex:
        LOG.exception(ex)


@autolog.log_method(logger=Logger)
def config_backup_delete(context, backup_id):
    """
    Delete an existing config backup
    """
    try:
        db.config_backup_delete(context, backup_id)
        _remove_config_backup_data(context, backup_id)
    except Exception as ex:
        LOG.exception(ex)


@autolog.log_method(logger=Logger)
def get_compute_host(context):
    try:
        # Look for contego node, which is up
        compute_nodes = get_compute_nodes(context, up_only=True)
        if len(compute_nodes) > 0:
            return compute_nodes[0].host
        else:
            message = "No compute node is up for validate database credentials."
            raise exception.ErrorOccurred(reason=message)
    except Exception as ex:
        raise ex


@autolog.log_method(logger=Logger)
def validate_database_creds(context, databases, trust_creds):
    try:
        host = get_compute_host(context)
        compute_service = nova.API(production=True)
        params = {'databases': databases,
                  'host': host, 'trust_creds': trust_creds}

        status = compute_service.validate_database_creds(context, params)
        if status['result'] != "success":
            message = "Please verify given database credentials."
            raise exception.ErrorOccurred(reason=message)
        else:
            return True
    except exception as ex:
        raise ex


@autolog.log_method(logger=Logger)
def validate_trusted_user_and_key(context, trust_creds):
    try:
        host = get_compute_host(context)
        compute_service = nova.API(production=True)
        params = {'host': host, 'trust_creds': trust_creds}

        status = compute_service.validate_trusted_user_and_key(context, params)
        if status['result'] != "success":
            message = "Please verify, given trusted user should have passwordless sudo access using given private key."
            raise exception.ErrorOccurred(reason=message)
        else:
            return True
    except Exception as ex:
        raise ex


@autolog.log_method(logger=Logger)
def get_controller_nodes(context):
    try:
        compute_service = nova.API(production=True)
        result = compute_service.get_controller_nodes(context)
        return result['controller_nodes']
    except exception as ex:
        raise ex


@autolog.log_method(logger=Logger)
def get_compute_nodes(context, host=None, up_only=False):
    try:
        contego_nodes = []
        nova_client = KeystoneClientBase(context).nova_client
        nova_services = nova_client.services.list(host=host)
        for nova_service in nova_services:
            if up_only is True:
                if nova_service.binary.find(
                        'contego') != -1 and nova_service.state == 'up':
                    contego_nodes.append(nova_service)
            else:
                if nova_service.binary.find('contego') != -1:
                    contego_nodes.append(nova_service)
        return contego_nodes
    except Exception as ex:
        raise ex

