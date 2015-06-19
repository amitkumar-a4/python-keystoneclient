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


LOG = logging.getLogger(__name__)

def import_workload(cntx, workload_url, new_version):
    """ Import workload and snapshot records from vault 
    Versions Supported: 1.0.118
    """
    def _adjust_values(values):
        values['version'] = new_version
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
    
    db = WorkloadMgrDB().db
    
    workload_values = json.loads(vault.get_object(workload_url['workload_url'] + '/workload_db'))
    workload_values = _adjust_values(workload_values)
    if workload_values['status'] == 'locked':
        workload_values['status'] = 'available'
    workload = db.workload_create(cntx, workload_values)
    if len(workload_values['jobschedule']): 
        workload_api = workloadAPI.API()
        workload_api.workload_add_scheduler_job(pickle.loads(str(workload_values['jobschedule'])), workload)                                       
                
    workload_vms = json.loads(vault.get_object(workload_url['workload_url'] + '/workload_vms_db'))
    for workload_vm_values in workload_vms:
        workload_vm_values = _adjust_values(workload_vm_values)
        db.workload_vms_create(cntx, workload_vm_values)

    snapshot_values_list = []
    for snapshot_url in workload_url['snapshot_urls']:
        try:
            snapshot_values = json.loads(vault.get_object(snapshot_url + '/snapshot_db'))
            snapshot_values['snapshot_url'] = snapshot_url
            snapshot_values_list.append(snapshot_values)
        except Exception as ex:
            LOG.exception(ex)
    snapshot_values_list_sorted = sorted(snapshot_values_list, key=itemgetter('created_at'))
     
    for snapshot_values in snapshot_values_list_sorted:
        snapshot_values = _adjust_values(snapshot_values)
        snapshot = db.snapshot_create(cntx, snapshot_values)
        try:
            snapshot_vms = json.loads(vault.get_object(snapshot_values['snapshot_url'] + '/snapshot_vms_db'))
            for snapshot_vm_values in snapshot_vms:
                snapshot_vm_values = _adjust_values(snapshot_vm_values)
                db.snapshot_vm_create(cntx, snapshot_vm_values)
            snapshot_vm_resources = json.loads(vault.get_object(snapshot_values['snapshot_url'] + '/resources_db'))
            for snapshot_vm_resource_values in snapshot_vm_resources:
                snapshot_vm_resource_values = _adjust_values(snapshot_vm_resource_values)
                db.snapshot_vm_resource_create(cntx, snapshot_vm_resource_values)
                
            resources = db.snapshot_resources_get(cntx, snapshot.id)
            for res in resources:
                vm_res_id = '/vm_res_id_%s' % (res['id'])
                for meta in res.metadata:
                    if meta.key == "label":
                        vm_res_id = '/vm_res_id_%s_%s' % (res['id'], meta.value)
                        break
                if res.resource_type == "network" or \
                    res.resource_type == "subnet" or \
                    res.resource_type == "router" or \
                    res.resource_type == "nic":                
                    path = "workload_" + snapshot['workload_id'] + \
                           "/snapshot_" + snapshot['id'] + \
                           "/network" + vm_res_id +\
                           "/network_db"
                    vm_network_resource_snaps = json.loads(vault.get_object(path))
                    for vm_network_resource_snap_vaules in vm_network_resource_snaps:
                        vm_network_resource_snap_vaules = _adjust_values(vm_network_resource_snap_vaules)
                        db.vm_network_resource_snap_create(cntx, vm_network_resource_snap_vaules)

                elif res.resource_type == "disk":
                    path = "workload_" + snapshot['workload_id'] + \
                           "/snapshot_" + snapshot['id'] + \
                           "/vm_id_" + res.vm_id + vm_res_id.replace(' ','') + \
                           "/disk_db"
                    vm_disk_resource_snaps = json.loads(vault.get_object(path))
                    vm_disk_resource_snaps_sorted = sorted(vm_disk_resource_snaps, key=itemgetter('created_at'))
                    for vm_disk_resource_snap_vaules in vm_disk_resource_snaps_sorted:
                        vm_disk_resource_snap_vaules = _adjust_values(vm_disk_resource_snap_vaules)
                        db.vm_disk_resource_snap_create(cntx, vm_disk_resource_snap_vaules)
                elif res.resource_type == "securty_group":
                    path = "workload_" + snapshot['workload_id'] + \
                           "/snapshot_" + snapshot['id'] + \
                           "/securty_group" + vm_res_id +\
                           "/security_group_db"
                    vm_security_group_rule_snaps= json.loads(vault.get_object(path))
                    for vm_security_group_rule_snap_vaules in vm_security_group_rule_snaps:
                        vm_security_group_rule_snap_vaules = _adjust_values(vm_security_group_rule_snap_vaules)
                        db.vm_security_group_rule_snap_create(cntx, vm_security_group_rule_snap_vaules)            
        except Exception as ex:
            LOG.exception(ex)
            db.snapshot_update(cntx,snapshot.id,{'status': 'error'})
    return workload
    
    """
    workloads = vault_service.conn.get_account()
    for workload in workloads[1]:
        if not workload['name'].startswith("workload_"):
            continue
        container = vault_service.conn.get_container(workload['name'])
        wl = vault_service.conn.get_object(workload['name'], workload['name'] + "/workload_db")[1]
        workload_values = json.loads(wl)
        workload_values['created_at'] = timeutils.parse_isotime(workload_values['created_at'])
        workload_values['updated_at'] = timeutils.parse_isotime(workload_values['updated_at'])
        wl_meta = {}
        for meta in workload_values['metadata']:
            wl_meta[meta['key']] = meta['value']
        workload_values['metadata'] = wl_meta
        db.workload_create(cntx, workload_values)

        wl_vms = vault_service.conn.get_object(workload['name'],
                                               workload['name'] + "/workload_vms_db")[1]
        workload_vms_values = json.loads(wl_vms)
        for wl_vm in workload_vms_values:
            wl_vm['created_at'] = timeutils.parse_isotime(wl_vm['created_at'])
            vm_meta = {}
            for meta in wl_vm['metadata']:
                vm_meta[meta['key']] = meta['value']
            wl_vm['metadata'] = vm_meta
            db.workload_vms_create(cntx, wl_vm)
            
        # Two passes here, one for snapshot and then for snapshot_vms
        for snap in container[1]:
            if "snapshot_db" in snap['name']:
                snapshot = vault_service.conn.get_object(workload['name'], snap['name'])[1]
                snapshot_values = json.loads(snapshot)
                snapshot_values['created_at'] = timeutils.parse_isotime(snapshot_values['created_at'])
                if snapshot_values['updated_at']:
                    snapshot_values['updated_at'] = timeutils.parse_isotime(snapshot_values['updated_at'])
                db.snapshot_create(cntx, snapshot_values)
                snapshotdb = db.snapshot_get(cntx, snapshot_values['id'])
            elif "resources_db" in snap['name']:
                resources = vault_service.conn.get_object(workload['name'], snap['name'])[1]
                resource_values = json.loads(resources)
                for res in resource_values:
                    res['created_at'] = timeutils.parse_isotime(res['created_at'])
                    if res['updated_at']:
                        res['updated_at'] = timeutils.parse_isotime(res['updated_at'])
                    res_meta = {}
                    for meta in res['metadata']:
                        res_meta[meta['key']] = meta['value']
                    res['metadata'] = res_meta
                    snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, res)                                                
            elif "disk_db" in snap['name']:
                disks = vault_service.conn.get_object(workload['name'], snap['name'])[1]
                disk_values = json.loads(disks)
                for disk in disk_values:
                    disk['created_at'] = timeutils.parse_isotime(disk['created_at'])
                    if disk['updated_at']:
                        disk['updated_at'] = timeutils.parse_isotime(disk['updated_at'])
                    disk_meta = {}
                    for meta in disk['metadata']:
                        disk_meta[meta['key']] = meta['value']
                    disk['metadata'] = disk_meta
                    db.vm_disk_resource_snap_create(cntx, disk)
            elif "network_db" in snap['name']:
                networks = vault_service.conn.get_object(workload['name'], snap['name'])[1]
                network_values = json.loads(networks)
                for network in network_values:
                    network['created_at'] = timeutils.parse_isotime(network['created_at'])
                    if network['updated_at']:
                        network['updated_at'] = timeutils.parse_isotime(network['updated_at'])
                    network_meta = {}
                    for meta in network['metadata']:
                        network_meta[meta['key']] = meta['value']
                    network['metadata'] = network_meta
                    db.vm_network_resource_snap_create(cntx, network)
            elif "security_group_db" in snap['name']:
                secgroups = vault_service.conn.get_object(workload['name'], snap['name'])[1]
                secgroup_values = json.loads(secgroups)
                for secgroup in secgroup_values:
                    secgroup['created_at'] = timeutils.parse_isotime(secgroup['created_at'])
                    if secgroup['updated_at']:
                        secgroup['updated_at'] = timeutils.parse_isotime(secgroup['updated_at'])
                    secgroup_meta = {}
                    for meta in secgroup['metadata']:
                        secgroup_meta[meta['key']] = meta['value']
                    secgroup['metadata'] = secgroup_meta
                    db.vm_security_group_rule_snap_create(cntx, secgroup)
            elif "snapshot_vms_db" in snap['name']:
                snapshot_vms = vault_service.conn.get_object(workload['name'],
                                                             snap['name'])[1]
                snapshot_vms_values = json.loads(snapshot_vms)
                for vm in snapshot_vms_values:
                    vm['created_at'] = timeutils.parse_isotime(vm['created_at'])
                    if vm['updated_at']:
                        vm['updated_at'] = timeutils.parse_isotime(vm['updated_at'])
                    vm_meta = {}
                    for meta in vm['metadata']:
                        vm_meta[meta['key']] = meta['value']
                    vm['metadata'] = vm_meta
                    db.snapshot_vm_create(cntx, vm)
    """

