# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

import socket
import json
from operator import itemgetter
import cPickle as pickle

from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import workloads as workloadAPI
from workloadmgr.vault import vault
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova

LOG = logging.getLogger(__name__)

<<<<<<< HEAD
def _adjust_values(cntx, new_version, values, upgrade):
=======

def _adjust_values(cntx, new_version, values):
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
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
        settings = json.loads(vault.get_object('/settings_db'))
        for setting_values in settings:
            try:
                if 'key' in setting_values:
                    setting_values['name'] = setting_values['key']
<<<<<<< HEAD
                setting_values = _adjust_values(cntx, new_version, setting_values, upgrade)
                db.setting_create(cntx, setting_values)  
=======
                setting_values = _adjust_values(cntx, new_version,
                                                setting_values)
                db.setting_create(cntx, setting_values)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
            except Exception as ex:
                LOG.exception(ex)
    except Exception as ex:
        LOG.exception(ex)


def import_workload(cntx, workload_url, new_version, upgrade=True):
    """ Import workload and snapshot records from vault
    Versions Supported: 1.0.177
    """
    db = WorkloadMgrDB().db
    workload_values = json.loads(vault.get_object(
        workload_url['workload_url'] + '/workload_db'))
    if upgrade is True:
        tenantcontext = nova._get_tenant_context(
            workload_values['user_id'], workload_values['project_id'])
    else:
        tenantcontext = cntx

<<<<<<< HEAD
    
    workload_values = _adjust_values(tenantcontext, new_version, workload_values, upgrade)
=======
    workload_values = _adjust_values(tenantcontext, new_version,
                                     workload_values)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
    if workload_values['status'] == 'locked':
        workload_values['status'] = 'available'
    workload = db.workload_create(tenantcontext, workload_values)
    if len(workload_values['jobschedule']):
        workload_api = workloadAPI.API()
        workload_api.workload_add_scheduler_job(pickle.loads(
            str(workload_values['jobschedule'])), workload)

    workload_vms = json.loads(vault.get_object(
        workload_url['workload_url'] + '/workload_vms_db'))
    for workload_vm_values in workload_vms:
<<<<<<< HEAD
        workload_vm_values = _adjust_values(tenantcontext, new_version, workload_vm_values, upgrade)
=======
        workload_vm_values = _adjust_values(tenantcontext, new_version,
                                            workload_vm_values)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
        db.workload_vms_create(tenantcontext, workload_vm_values)

    snapshot_values_list = []
    for snapshot_url in workload_url['snapshot_urls']:
        try:
            snapshot_values = json.loads(vault.get_object(
                snapshot_url + '/snapshot_db'))
            snapshot_values['snapshot_url'] = snapshot_url
            snapshot_values_list.append(snapshot_values)
        except Exception as ex:
            LOG.exception(ex)
    snapshot_values_list_sorted = sorted(snapshot_values_list,
                                         key=itemgetter('created_at'))

    for snapshot_values in snapshot_values_list_sorted:
<<<<<<< HEAD
        snapshot_values = _adjust_values(tenantcontext, new_version, snapshot_values, upgrade)
=======
        snapshot_values = _adjust_values(tenantcontext, new_version,
                                         snapshot_values)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
        snapshot = db.snapshot_create(tenantcontext, snapshot_values)
        try:
            snapshot_vms = json.loads(vault.get_object(
                snapshot_values['snapshot_url'] + '/snapshot_vms_db'))
            for snapshot_vm_values in snapshot_vms:
<<<<<<< HEAD
                snapshot_vm_values = _adjust_values(tenantcontext, new_version, snapshot_vm_values, upgrade)
=======
                snapshot_vm_values = _adjust_values(tenantcontext,
                                                    new_version,
                                                    snapshot_vm_values)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
                db.snapshot_vm_create(tenantcontext, snapshot_vm_values)
            snapshot_vm_resources = json.loads(vault.get_object(
                snapshot_values['snapshot_url'] + '/resources_db'))
            for snapshot_vm_resource_values in snapshot_vm_resources:
<<<<<<< HEAD
                snapshot_vm_resource_values = _adjust_values(tenantcontext, new_version, snapshot_vm_resource_values, upgrade)
                db.snapshot_vm_resource_create(tenantcontext, snapshot_vm_resource_values)
                
=======
                snapshot_vm_resource_values = _adjust_values(
                    tenantcontext, new_version, snapshot_vm_resource_values)
                db.snapshot_vm_resource_create(tenantcontext,
                                               snapshot_vm_resource_values)

>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
            resources = db.snapshot_resources_get(tenantcontext, snapshot.id)
            for res in resources:
                vm_res_id = '/vm_res_id_%s' % (res['id'])
                for meta in res.metadata:
                    if meta.key == "label":
                        vm_res_id = '/vm_res_id_%s_%s' % \
                                    (res['id'], meta.value)
                        break
                if res.resource_type == "network" or \
                   res.resource_type == "subnet" or \
                   res.resource_type == "router" or \
                   res.resource_type == "nic":
                    path = "workload_" + snapshot['workload_id'] + \
                           "/snapshot_" + snapshot['id'] + \
                           "/network" + vm_res_id +\
                           "/network_db"
<<<<<<< HEAD
                    vm_network_resource_snaps = json.loads(vault.get_object(path))
                    for vm_network_resource_snap_vaules in vm_network_resource_snaps:
                        vm_network_resource_snap_vaules = _adjust_values(tenantcontext, new_version, vm_network_resource_snap_vaules, upgrade)
                        db.vm_network_resource_snap_create(tenantcontext, vm_network_resource_snap_vaules)
=======
                    vm_network_resource_snaps = json.loads(vault.get_object(
                        path))
                    for vm_network_resource_snap_vaules in \
                        vm_network_resource_snaps:  # nopep8
                        vm_network_resource_snap_vaules = _adjust_values(
                            tenantcontext, new_version,
                            vm_network_resource_snap_vaules)
                        db.vm_network_resource_snap_create(
                            tenantcontext, vm_network_resource_snap_vaules)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa

                elif res.resource_type == "disk":
                    path = "workload_" + snapshot['workload_id'] + \
                           "/snapshot_" + snapshot['id'] + \
<<<<<<< HEAD
                           "/vm_id_" + res.vm_id + vm_res_id.replace(' ','') + \
                           "/disk_db"
                    vm_disk_resource_snaps = json.loads(vault.get_object(path))
                    vm_disk_resource_snaps_sorted = sorted(vm_disk_resource_snaps, key=itemgetter('created_at'))
                    for vm_disk_resource_snap_vaules in vm_disk_resource_snaps_sorted:
                        vm_disk_resource_snap_vaules = _adjust_values(tenantcontext, new_version, vm_disk_resource_snap_vaules, upgrade)
                        db.vm_disk_resource_snap_create(tenantcontext, vm_disk_resource_snap_vaules)
=======
                           "/vm_id_" + res.vm_id + \
                           vm_res_id.replace(' ', '') + "/disk_db"
                    vm_disk_resource_snaps = json.loads(
                        vault.get_object(path))
                    vm_disk_resource_snaps_sorted = sorted(
                        vm_disk_resource_snaps, key=itemgetter('created_at'))
                    for vm_disk_resource_snap_vaules in \
                        vm_disk_resource_snaps_sorted:  # nopep8
                        vm_disk_resource_snap_vaules = _adjust_values(
                            tenantcontext, new_version,
                            vm_disk_resource_snap_vaules)
                        db.vm_disk_resource_snap_create(
                            tenantcontext, vm_disk_resource_snap_vaules)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
                elif res.resource_type == "securty_group":
                    path = "workload_" + snapshot['workload_id'] + \
                           "/snapshot_" + snapshot['id'] + \
                           "/securty_group" + vm_res_id +\
                           "/security_group_db"
<<<<<<< HEAD
                    vm_security_group_rule_snaps= json.loads(vault.get_object(path))
                    for vm_security_group_rule_snap_vaules in vm_security_group_rule_snaps:
                        vm_security_group_rule_snap_vaules = _adjust_values(tenantcontext, new_version, vm_security_group_rule_snap_vaules, upgrade)
                        db.vm_security_group_rule_snap_create(tenantcontext, vm_security_group_rule_snap_vaules)            
=======
                    vm_security_group_rule_snaps = json.loads(
                        vault.get_object(path))
                    for vm_security_group_rule_snap_vaules in \
                        vm_security_group_rule_snaps:  # nopep8
                        vm_security_group_rule_snap_vaules = _adjust_values(
                            tenantcontext, new_version,
                            vm_security_group_rule_snap_vaules)
                        db.vm_security_group_rule_snap_create(
                            tenantcontext, vm_security_group_rule_snap_vaules)
>>>>>>> e866dafb7a9542f4b6483fea05ce64d19cc131fa
        except Exception as ex:
            LOG.exception(ex)
            db.snapshot_update(tenantcontext, snapshot.id, {'status': 'error'})
    return workload
