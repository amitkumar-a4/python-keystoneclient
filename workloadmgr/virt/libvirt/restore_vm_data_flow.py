import os
import uuid
from Queue import Queue
import cPickle as pickle
import json
import shutil
import math
import re
import time
import datetime
import subprocess
from subprocess import check_output

from oslo.config import cfg

from taskflow import engines
from taskflow import task
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf

from novaclient.exceptions import Unauthorized as nova_unauthorized

from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.virt import driver
from workloadmgr.virt import qemuimages
from workloadmgr.virt import power_state
from workloadmgr.virt import driver

from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import jsonutils
from workloadmgr.openstack.common import timeutils

from workloadmgr.image import glance
from workloadmgr.volume import cinder
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.workloads import workload_utils

from workloadmgr.vault import vault

from workloadmgr import utils
from workloadmgr import flags
from workloadmgr import autolog
from workloadmgr import exception

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

FLAGS = flags.FLAGS
CONF = cfg.CONF
CONF.register_opts(restore_vm_opts)
 
class CopyBackupImageToVolume(task.Task):
    """
       If the volume is SAN volume, initiate copy of backup data
       to volume on contego.
       SAN volumes include iscsi and fc channel volumes
    """

    def execute(self, context, restored_instance_id,
                restore_id, restore_type,
                restored_file_path,
                progress_tracking_file_path,
                image_overlay_file_path,
                volume_id = None, volume_type = None,
                image_id = None, image_type = None):
        return self.execute_with_log(context, restored_instance_id, 
                                     volume_id, volume_type,
                                     image_id, image_type, 
                                     restore_id, restore_type,
                                     restored_file_path,
                                     image_overlay_file_path,
                                     progress_tracking_file_path)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'CopyBackupImageToVolume.execute')
    def execute_with_log(self, context, restored_instance_id, 
                         volume_id, volume_type,
                         image_id, image_type, 
                         restore_id, restore_type,
                         restored_file_path, 
                         image_overlay_file_path,
                         progress_tracking_file_path):
 
        # Call into contego to copy the data from backend to volume
        compute_service = nova.API(production=True)
        db = WorkloadMgrDB().db

        # Get a new token, just to be safe
        cntx = amqp.RpcContext.from_dict(context)
        cntx = nova._get_tenant_context(cntx)
        vast_params = {'volume_id': volume_id, 'volume_type': volume_type,
                       'image_id': image_id, 'image_type' : image_type,
                       'backup_image_file_path': restored_file_path,
                       'image_overlay_file_path': image_overlay_file_path,
                       'progress_tracking_file_path': progress_tracking_file_path}
        compute_service.copy_backup_image_to_volume(cntx, restored_instance_id, vast_params)

        image_info = qemuimages.qemu_img_info(restored_file_path or image_overlay_file_path)
        prev_copied_size_incremental = 0

        basestat = os.stat(progress_tracking_file_path)
        basetime = time.time()
        while True:
            try:
                time.sleep(10)
                async_task_status = {}
                if progress_tracking_file_path:
                    try:
                        with open(progress_tracking_file_path, 'r') as progress_tracking_file:
                            async_task_status['status'] = progress_tracking_file.readlines()
                    except Exception as ex:
                        LOG.exception(ex)

                    # if the modified timestamp of progress file hasn't for a while
                    # throw an exception
                    progstat = os.stat(progress_tracking_file_path)

                    # if we don't see any update to file time for 5 minutes, something is wrong
                    # deal with it.
                    if progstat.st_mtime > basestat.st_mtime:
                        basestat = progstat
                        basetime = time.time()
                    elif time.time() - basetime > 600:
                        raise Exception("No update to %s modified time for last 10 minutes. "
                                        "Contego may have errored. Aborting Operation" % 
                                        progress_tracking_file_path)
                else:
                    # For swift based backup media
                    async_task_status = compute_service.vast_async_task_status(cntx, 
                                                  instance['vm_id'],
                                                  {'metadata': progress_tracker_metadata})
                data_transfer_completed = False
                percentage="0.0"
                if async_task_status and 'status' in async_task_status and \
                        len(async_task_status['status']):
                    for line in async_task_status['status']:
                        if 'percentage complete' in line:
                            percentage = re.search(r'\d+\.\d+', line).group(0)
                        if 'Error' in line:
                            raise Exception("Data transfer failed - Contego Exception:" + line)
                        if 'Completed' in line:
                            data_transfer_completed = True
                            percentage="100.0"
                            break;

                copied_size_incremental = int(float(percentage) * \
                                                   image_info.virtual_size/100)
                restore_obj = db.restore_update(cntx, restore_id,
                                           {'uploaded_size_incremental': copied_size_incremental - \
                                                                   prev_copied_size_incremental})
                prev_copied_size_incremental = copied_size_incremental
                if data_transfer_completed:
                    break;
            except nova_unauthorized as ex:
                LOG.exception(ex)
                # recreate the token here
                cntx = nova._get_tenant_context(cntx)
            except Exception as ex:
                LOG.exception(ex)
                raise ex

        restore_obj = db.restore_update(cntx, restore_id,
                                        {'uploaded_size_incremental': image_info.virtual_size})

    @autolog.log_method(Logger, 'CopyBackupImageToVolume.revert')
    def revert_with_log(self, *args, **kwargs):
        pass

def CopyBackupImagesToVolumes(context, instance, snapshot_obj, restore_id):
    flow = lf.Flow("copybackupimagestovolumeslf")
    db = WorkloadMgrDB().db
    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshot_obj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        if db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id'):
            flow.add(CopyBackupImageToVolume("CopyBackupImageToVolume" + snapshot_vm_resource.id,
                                  rebind=dict(volume_id='volume_id_' + str(snapshot_vm_resource.id),
                                              volume_type='volume_type_'+str(snapshot_vm_resource.id),
                                              restored_file_path='restore_file_path_' + str(snapshot_vm_resource.id),
                                              progress_tracking_file_path='progress_tracking_file_path_'+str(snapshot_vm_resource.id),
                                              image_overlay_file_path='image_overlay_file_path_' + str(snapshot_vm_resource.id),
                                              )))
        elif db.get_metadata_value(snapshot_vm_resource.metadata, 'image_id'):
            flow.add(CopyBackupImageToVolume("CopyBackupImageToVolume" + snapshot_vm_resource.id,
                                  rebind=dict(image_id='image_id_' + str(snapshot_vm_resource.id),
                                              image_type='image_type_'+str(snapshot_vm_resource.id),
                                              restored_file_path='restore_file_path_' + str(snapshot_vm_resource.id),
                                              progress_tracking_file_path='progress_tracking_file_path_'+str(snapshot_vm_resource.id),
                                              image_overlay_file_path='image_overlay_file_path_' + str(snapshot_vm_resource.id),
                                              )))
    return flow

def restore_vm_data(cntx, db, instance, restore, restored_net_resources,
                    restored_security_groups, restored_compute_flavor,
                    restored_nics, instance_options):

    restore_obj = db.restore_get(cntx, restore['id'])
    snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
    workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)

    backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)

    msg = 'Uploading VM "' + instance['vm_id'] + '" data from snapshot ' + snapshot_obj.id
    db.restore_update(cntx,  restore_obj.id, {'progress_msg': msg})

    # refresh the token so we are attempting each VM restore with a new token
    cntx = nova._get_tenant_context(cntx)

    context_dict = dict([('%s' % key, value)
                          for (key, value) in cntx.to_dict().iteritems()])            
    context_dict['conf'] =  None # RpcContext object looks for this during init

    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'],
                                                         snapshot_obj.id)

    # remove items that cannot be jsoned
    restore_dict = dict(restore.iteritems())
    restore_dict.pop('created_at')
    restore_dict.pop('updated_at')
    store = {
                'connection': FLAGS.sql_connection,
                'context': context_dict,
                'restore': restore_dict,
                'restore_id': restore['id'],
                'vmid': instance['vm_id'],
                'vmname': instance['vm_name'],
                'keyname': 'keyname' in instance and instance['keyname'] or None,
                'snapshot_id': snapshot_obj.id,
                'restore_type': restore['restore_type'],
                'instance_options': instance_options,
            }

    for snapshot_vm_resource in snapshot_vm_resources:
        store[snapshot_vm_resource.id] = snapshot_vm_resource.id
        store['devname_'+snapshot_vm_resource.id] = snapshot_vm_resource.resource_name
        if snapshot_vm_resource.resource_type == 'disk':

            progress_tracker_metadata = {'snapshot_id': snapshot_obj.id,
                                         'resource_id' : snapshot_vm_resource.id}

            progress_tracking_file_path = backup_target.get_progress_tracker_path(progress_tracker_metadata)
            volume_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id')
            if volume_id:
                volume_type = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'volume_type') or "None"
                new_volume_type = get_new_volume_type(instance_options,
                                                      volume_id.lower(),
                                                      volume_type)
                store['volume_type_'+snapshot_vm_resource.id] = new_volume_type
            else:
                store['volume_type_'+snapshot_vm_resource.id] = None

            store['progress_tracking_file_path_'+snapshot_vm_resource.id] = progress_tracking_file_path


    LOG.info(_('Processing disks'))
    _restorevmflow = lf.Flow(instance['vm_id'] + "RestoreInstance")

    # copy data if the volumes are iscsi volumes
    childflow = CopyBackupImagesToVolumes(cntx, instance,
                                          snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    result = engines.run(_restorevmflow, engine_conf='serial',
                         backend={'connection': store['connection'] }, store=store)

    if result and 'restored_instance_id' in result:
        restored_instance_id = result['restored_instance_id']
        compute_service = nova.API(production = (not test))
        restored_instance = compute_service.get_server_by_id(cntx,
                                         restored_instance_id)
        
        restored_vm_values = {'vm_id': restored_instance_id,
                              'vm_name':  restored_instance.name,    
                              'restore_id': restore['id'],
                              'metadata' : {'production' : restored_net_resources[mac_address]['production'], 'instance_id': instance['vm_id']},
                              'status': 'available'}
        restored_vm = db.restored_vm_create(cntx, restored_vm_values)    
        
        LOG.debug(_("VM Data Restore Completed"))
         
        db.restore_update(cntx, restore_obj.id, 
                          {'progress_msg': 'Restored VM "' + instance['vm_id'] + \
                                           '" data from snapshot ' + snapshot_obj.id,
                           'status': 'executing'
                          })
        db.restore_update( cntx, restore_obj.id,
                           {'progress_msg': 'Restored VM:' + restored_vm['vm_id'], 'status': 'executing'})
        return restored_vm
    else:
        raise Exception("Restoring VM data failed")
