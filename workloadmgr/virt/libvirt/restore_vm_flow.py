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
from workloadmgr.workflows import vmtasks_openstack

from workloadmgr.vault import vault

from workloadmgr import utils
from workloadmgr import flags
from workloadmgr import autolog
from workloadmgr import exception
from workloadmgr.workflows.vmtasks import FreezeVM, ThawVM


restore_vm_opts = [
    cfg.StrOpt('cinder_nfs_mount_point_base',
               default='/opt/stack/data/mnt',
               help='Dir where the nfs volume is mounted for restore'),                   

    cfg.StrOpt('nfs_volume_type_substr',
               default='nfs,netapp',
               help='Dir where the nfs volume is mounted for restore'),                   
    cfg.IntOpt('progress_tracking_update_interval',
               default=600,
               help='Number of seconds to wait for progress tracking file '
                    'updated before we call contego crash'),
    ]

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

FLAGS = flags.FLAGS
CONF = cfg.CONF
CONF.register_opts(restore_vm_opts)
 
def get_new_volume_type(instance_options, volume_id, volume_type):
    if instance_options and 'vdisks' in instance_options:
        for voloption in instance_options['vdisks']:
            if voloption['id'].lower() == volume_id:
                volume_type = voloption['new_volume_type']
                break

    if volume_type.lower() == 'none':
        volume_type = None
    return volume_type


def is_supported_backend(volume_type):
    return True


def get_availability_zone(instance_options, volume_id=None, az=None):
    # find the mapping for volume
    if volume_id is not None and 'vdisks' in instance_options and len(instance_options['vdisks']) > 0:
       for vdisk in instance_options['vdisks']:
           if vdisk['id'] == volume_id:
              if 'availability_zone' in vdisk and vdisk['availability_zone'] != '':
                 availability_zone = vdisk.get('availability_zone')
              elif az is not None:
                   availability_zone = az
              else:
                   availability_zone = None
              break
    elif volume_id is not None and az is not None:
         return az
    else:
        # else find the mapping for VM
        if instance_options and 'availability_zone' in instance_options and \
            instance_options['availability_zone'] != '':
            availability_zone = instance_options['availability_zone'] 
        else:
            if CONF.default_production_availability_zone == 'None':
                availability_zone = None
            else:
                availability_zone = CONF.default_production_availability_zone

    if availability_zone == '':
       return None
    return availability_zone


class PrepareBackupImage(task.Task):
    """
       Downloads objects in the backup chain and creates linked qcow2 image
    """

    def execute(self, context, restore_id, vm_resource_id, volume_type):
        return self.execute_with_log(context, restore_id, vm_resource_id, volume_type)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'PrepareBackupImage.execute')
    def execute_with_log(self, context, restore_id, vm_resource_id, volume_type):
        db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)

        restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)
        workload_obj = db.workload_get(self.cntx, snapshot_obj.workload_id)

        backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                'backup_media_target')

        backup_target = vault.get_backup_target(backup_endpoint)

        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(self.cntx, snapshot_vm_resource.id) 
        resource_snap_path = os.path.join(backup_target.mount_path,
                                          vm_disk_resource_snap.vault_url.strip(os.sep))
        """try:
            os.listdir(os.path.join(backup_target.mount_path, 'workload_'+snapshot_obj.workload_id,
                                   'snapshot_'+snapshot_obj.id))
            os.listdir(os.path.split(resource_snap_path)[0])
        except:
               pass"""
        image_info = qemuimages.qemu_img_info(resource_snap_path)

        if snapshot_vm_resource.resource_name == 'vda' and \
            db.get_metadata_value(snapshot_vm_resource.metadata, 'image_id') is not None:
            # upload the bottom of the chain to glance
            while image_info.backing_file:
                image_info = qemuimages.qemu_img_info(image_info.backing_file)

            restore_file_path = image_info.image
            image_overlay_file_path = resource_snap_path
            image_virtual_size = image_info.virtual_size
        else:
            restore_file_path = resource_snap_path
            image_overlay_file_path = 'not-applicable'
            image_virtual_size = image_info.virtual_size

        return restore_file_path, image_overlay_file_path, image_virtual_size

        """
        if db.get_metadata_value(snapshot_vm_resource.metadata, 'image_id') == None and \
           vault.commit_supported() == True:
            image_info = qemuimages.qemu_img_info(vm_disk_resource_snap.vault_path)
            if not image_info.backing_file or is_supported_backend(volume_type):
                return (vm_disk_resource_snap.vault_path, image_info.virtual_size)                           

        # Need to stage the files and commit
        snapshot_vm_resource_object_store_transfer_time =\
              workload_utils.download_snapshot_vm_resource_from_object_store(self.cntx,
                                                                             restore_obj.id,
                                                                             restore_obj.snapshot_id,
                                                                             snapshot_vm_resource.id)

        snapshot_vm_object_store_transfer_time = snapshot_vm_resource_object_store_transfer_time
        snapshot_vm_data_transfer_time  =  snapshot_vm_resource_object_store_transfer_time            
            
        vm_disk_resource_snap_staging_path = vault.get_restore_vm_disk_resource_staging_path(\
                                                {'restore_id' : restore_obj.id,
                                                 'workload_id': snapshot_obj.workload_id,
                                                 'snapshot_id': snapshot_obj.id,
                                                 'snapshot_vm_id': snapshot_vm_resource.vm_id,
                                                 'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                 'snapshot_vm_resource_name':  snapshot_vm_resource.resource_name,
                                                 'vm_disk_resource_snap_id' : vm_disk_resource_snap.id,   
                                                 })
        head, tail = os.path.split(vm_disk_resource_snap_staging_path)
        fileutils.ensure_tree(head)

        convert_thread = qemuimages.convert_image(
                                      vm_disk_resource_snap.vault_path,
                                      vm_disk_resource_snap_staging_path,
                                      'qcow2', run_as_root=True)
            
        start_time = timeutils.utcnow()
        uploaded_size = 0
        uploaded_size_incremental = 0
        previous_uploaded_size = 0  

        while True:
            time.sleep(10)
            image_info = qemuimages.qemu_img_info(vm_disk_resource_snap_staging_path)                
            totalbytes = image_info.disk_size
            if totalbytes:
                progressmsg = _('Rehydrating image of instance %(vmid)s from \
                                snapshot %(snapshot_id)s %(bytes)s bytes done') % \
                                {'vmid': snapshot_vm_resource.vm_id,
                                 'snapshot_id': snapshot_obj.id,
                                 'bytes': totalbytes}
                db.restore_update(self.cntx,  restore_obj.id,
                          {'progress_msg': progressmsg, 'status': 'uploading' })
                restore_obj = db.restore_update(self.cntx, restore_obj.id, 
                                                {'uploaded_size_incremental': uploaded_size_incremental})
            if not convert_thread.isAlive():
                break
            now = timeutils.utcnow()                        
            if (now - start_time) > datetime.timedelta(minutes=10*60):
                raise exception.ErrorOccurred(reason='Timeout uploading data')
            
        image_info = qemuimages.qemu_img_info(vm_disk_resource_snap_staging_path)
        self.restored_file_path = vm_disk_resource_snap_staging_path
        return (self.restored_file_path, image_info.virtual_size)
        """
    @autolog.log_method(Logger, 'PrepareBackupImage.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            if self.restored_file_path:
                os.remove(self.restored_file_path)
        except:
            pass

class UploadImageToGlance(task.Task):
    """
       Upload image to glance
    """

    def execute(self, context, vmid, restore_id, vm_resource_id,
                restore_file_path):
        return self.execute_with_log(context, vmid, restore_id,
                                     vm_resource_id, restore_file_path)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'UploadImageToGlance.execute')
    def execute_with_log(self, context, vmid, restore_id,
                         vm_resource_id, restore_file_path):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.restore_obj = restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, self.restore_obj.snapshot_id)
        snapshot_id = restore_obj.snapshot_id
        self.image_service = glance.get_default_image_service(\
                                  production= (restore_obj['restore_type'] != 'test'))
        
        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(self.cntx, snapshot_vm_resource.id)
        try:
            org_image_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'image_id')
            org_glance_image = self.image_service.show(self.cntx, org_image_id)
            if org_glance_image and org_glance_image['deleted'] is False:
                return org_glance_image['id'], org_glance_image['disk_format']
        except:
            pass
        
        progressmsg = _('Uploading image of instance %(vmid)s from \
                        snapshot %(snapshot_id)s') % \
                        {'vmid': vmid, 'snapshot_id': snapshot_id}

        LOG.debug(progressmsg)

        db.restore_update(self.cntx,  restore_id,
                          {'progress_msg': progressmsg, 'status': 'uploading' })                  
        image_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'image_name')
        if not image_name:
            image_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_name')

        time_offset = datetime.datetime.now() - datetime.datetime.utcnow()
        index = image_name.index('_Snapshot_') if '_Snapshot_' in image_name else -1
        if index != -1:
            image_name = image_name[:index] + '_Snapshot_' + (snapshot_obj.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p")
        else:
            image_name = image_name + '_Snapshot_' + (snapshot_obj.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p")
        if db.get_metadata_value(vm_disk_resource_snap.metadata, 'disk_format') == 'vmdk':
            image_metadata = {'is_public': False,
                              'status': 'active',
                              'name': image_name,
                              'disk_format' : 'vmdk', 
                              'container_format' : 'bare',
                              'properties': {
                                  'hw_disk_bus' : 'scsi',
                                  'vmware_adaptertype' : 'lsiLogic',
                                  'vmware_disktype': 'preallocated',
                                  'image_state': 'available',
                                  'owner_id': self.cntx.project_id}
                             }
        else:
            image_metadata = {'is_public': False,
                              'status': 'active',
                              'name': image_name,
                              'disk_format' : 'qcow2',
                              'container_format' : 'bare',
                              'properties': {}
                              }

        LOG.debug('Uploading image ' + restore_file_path)

        # refresh the token
        self.cntx = nova._get_tenant_context(self.cntx)
        
        # Add hw_qemu_guest_agent information to image metadata if available
        status_hw_qemu_guest_agent = db.get_metadata_value(snapshot_vm_resource.metadata, 'hw_qemu_guest_agent')
        if str(status_hw_qemu_guest_agent).lower() in ['yes', 'no']:
            image_metadata['properties']['hw_qemu_guest_agent'] = status_hw_qemu_guest_agent

        self.restored_image = restored_image = self.image_service.create(self.cntx, image_metadata)
        if restore_obj['restore_type'] == 'test':
            shutil.move(restore_file_path, os.path.join(CONF.glance_images_path, restored_image['id']))
            restore_file_path = os.path.join(CONF.glance_images_path, restored_image['id'])
            with file(restore_file_path) as image_file:
                restored_image = self.image_service.update(self.cntx, restored_image['id'], image_metadata, image_file)
        else:
            restored_image = self.image_service.update(self.cntx, 
                                                       restored_image['id'], 
                                                       image_metadata, 
                                                       utils.ChunkedFile(restore_file_path,
                                                                          {'function': db.restore_update,
                                                                           'context': self.cntx,
                                                                           'id':restore_obj.id})
                                                       )
        LOG.debug(_("restore_size: %(restore_size)s") %{'restore_size': restore_obj.size,})
        LOG.debug(_("uploaded_size: %(uploaded_size)s") %{'uploaded_size': restore_obj.uploaded_size,})
        LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': restore_obj.progress_percent,})                

        db.restore_update(self.cntx, restore_id, {'uploaded_size_incremental': restored_image['size']})
        progress = "{message_color} {message} {progress_percent} {normal_color}".format(**{
                   'message_color': autolog.BROWN,
                   'message': "Restore Progress: ",
                   'progress_percent': str(restore_obj.progress_percent),
                   'normal_color': autolog.NORMAL,
                   })
        LOG.debug( progress)

        if not restored_image:
            raise Exception("Cannot create glance image")

        self.image_id = restored_image['id']
        return restored_image['id'], restored_image['disk_format']

    @autolog.log_method(Logger, 'UploadImageToGlance.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.cntx = nova._get_tenant_context(self.cntx)
            self.image_service.delete(self.cntx, self.image_id)
        except:
            pass

class RestoreVolumeFromImage(task.Task):
    """
       Restore volume from glance image
    """

    def execute(self, context, vmid, restore_id, instance_options,
                vm_resource_id, volume_type, image_id, image_virtual_size):
        return self.execute_with_log(context, vmid, restore_id,
                                     instance_options,
                                     vm_resource_id, volume_type,
                                     image_id, image_virtual_size)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreVolumeFromImage.execute')
    def execute_with_log(self, context, vmid, restore_id, instance_options,
                         vm_resource_id, volume_type, 
                         image_id, image_virtual_size):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.restore_obj = restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)
        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)

        self.image_service = glance.get_default_image_service(production= (restore_obj['restore_type'] != 'test'))
        self.volume_service = volume_service = cinder.API()

        restored_image = self.image_service.show(self.cntx, image_id)

        LOG.debug('Restoring volume from image ' + image_id)

        #volume_size = int(math.ceil(image_virtual_size/(float)(1024*1024*1024)))

        volume_size = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_size')
        volume_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_name')
        volume_description = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_description')
        volume_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id')
        az = ''
        if db.get_metadata_value(snapshot_vm_resource.metadata,'availability_zone'):
           az = db.get_metadata_value(snapshot_vm_resource.metadata,'availability_zone')
        
        availability_zone = get_availability_zone(instance_options,
                                                  volume_id=volume_id,
                                                  az=az)

        self.restored_volume = restored_volume = volume_service.create(self.cntx, volume_size,
                                                volume_name,
                                                volume_description,
                                                image_id=image_id, volume_type=volume_type,
                                                availability_zone=availability_zone)

        if not restored_volume:
            raise Exception("Cannot create volume from image")
                   
        #delete the image...it is not needed anymore
        #TODO(gbasava): Cinder takes a while to create the volume from image... so we need to verify the volume creation is complete.
        start_time = timeutils.utcnow()
        while True:
            time.sleep(10)
            try:
                restored_volume = volume_service.get(self.cntx, restored_volume['id'])
                if restored_volume['status'].lower() == 'available' or\
                    restored_volume['status'].lower() == 'error':
                    break
                now = timeutils.utcnow()
                if (now - start_time) > datetime.timedelta(minutes=10*60):
                    raise exception.ErrorOccurred(reason='Timeout while restoring volume from image')              
            except nova_unauthorized as ex:
                LOG.exception(ex)
                # recreate the token here
                self.cntx = nova._get_tenant_context(self.cntx)

        self.image_service.delete(self.cntx, image_id)
        if restored_volume['status'].lower() == 'error':
            LOG.error(_("Volume from image %s could not successfully create") % image_id)
            raise Exception("Restoring volume failed")

        restore_obj = db.restore_update(self.cntx, restore_obj.id, {'uploaded_size_incremental': restored_image['size']})

        return restored_volume['id']

    @autolog.log_method(Logger, 'RestoreVolumeFromImage.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.volume_service.delete(self.cntx, self.restored_volume)
        except:
            pass

class RestoreNFSVolume(task.Task):
    """
       Restore cinder nfs volume from qcow2
    """

    def execute(self, context, restore_id, instance_options,
                volume_type, vm_resource_id, restored_file_path):
        return self.execute_with_log(context, restore_id, instance_options,
                                     volume_type,  
                                     vm_resource_id, restored_file_path)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreNFSVolume.execute')
    def execute_with_log(self, context, restore_id, instance_options,
                         volume_type, vm_resource_id, restored_file_path):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.volume_service = volume_service = cinder.API()
        restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)        
        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)
        
        time_offset = datetime.datetime.now() - datetime.datetime.utcnow()
        #desciption = 'Restored from Snap_' + (snapshot_obj.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p")
        volume_size = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_size')
        volume_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_name')
        volume_description = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_description')
        volume_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id')
        az = ''
        if db.get_metadata_value(snapshot_vm_resource.metadata,'availability_zone'):
           az = db.get_metadata_value(snapshot_vm_resource.metadata,'availability_zone')
        
        availability_zone = get_availability_zone(instance_options,
                                                  volume_id=volume_id,
                                                  az=az)

        progressmsg = _('Restoring NFS Volume ' + volume_name + ' from snapshot ' + snapshot_obj.id)
        LOG.debug(progressmsg)
        db.restore_update(self.cntx,  restore_id, {'progress_msg': progressmsg, 'status': 'uploading' })             
        
        self.restored_volume = volume_service.create(self.cntx, 
                                                     volume_size,
                                                     volume_name,
                                                     volume_description, 
                                                     volume_type = volume_type,
                                                     availability_zone=availability_zone)

        if not self.restored_volume:
            raise Exception("Failed to create volume type " + volume_type)

        start_time = timeutils.utcnow()
        while True:
            time.sleep(10)
            self.restored_volume = volume_service.get(self.cntx, self.restored_volume['id'])
            if self.restored_volume['status'].lower() == 'available' or\
                self.restored_volume['status'].lower() == 'error':
                break
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=4):
                raise exception.ErrorOccurred(reason='Timeout restoring NFS Volume')               

        if self.restored_volume['status'].lower() == 'error':
            raise Exception("Failed to create volume type " + volume_type)

        connection = volume_service.initialize_connection(self.cntx, self.restored_volume, {})
        if 'data' in connection and \
           'export' in connection['data'] and \
           'name' in connection['data']:
            fileutils.ensure_tree(CONF.cinder_nfs_mount_point_base)
            
            try:
                command = ['sudo', 'umount', CONF.cinder_nfs_mount_point_base]
                subprocess.call(command, shell=False)
            except Exception as exception:
                pass
            
            try:
                command = ['sudo', 'umount', '-l', CONF.cinder_nfs_mount_point_base]
                subprocess.call(command, shell=False)
            except Exception as exception:
                pass
                        
            command = ['timeout', '-sKILL', '30' , 'sudo', 'mount', '-o', 'nolock', connection['data']['export'], CONF.cinder_nfs_mount_point_base]
            subprocess.check_call(command, shell=False)
            os.remove(CONF.cinder_nfs_mount_point_base + '/' + connection['data']['name'])
            
            destination = CONF.cinder_nfs_mount_point_base + '/' + connection['data']['name']
            convert_thread = qemuimages.convert_image(restored_file_path, destination, 'raw', run_as_root=True)
            
            start_time = timeutils.utcnow()
            uploaded_size = 0
            uploaded_size_incremental = 0
            previous_uploaded_size = 0  
            while True:
                time.sleep(10)
                image_info = qemuimages.qemu_img_info(destination)                
                totalbytes = image_info.disk_size
                if totalbytes:
                    uploaded_size_incremental = totalbytes - previous_uploaded_size
                    uploaded_size = totalbytes
                    restore_obj = db.restore_update(self.cntx, restore_obj.id, 
                                                    {'uploaded_size_incremental': uploaded_size_incremental})
                    previous_uploaded_size = uploaded_size
                if not convert_thread.isAlive():
                    break
                now = timeutils.utcnow()                        
                if (now - start_time) > datetime.timedelta(minutes=10*60):
                    raise exception.ErrorOccurred(reason='Timeout uploading data')               
            
            qemuimages.resize_image(destination, '%sG' % volume_size,run_as_root=True)
            try:
                command = ['sudo', 'umount', CONF.cinder_nfs_mount_point_base]
                subprocess.call(command, shell=False)
            except Exception as exception:
                pass
            
            try:
                command = ['sudo', 'umount', '-l', CONF.cinder_nfs_mount_point_base]
                subprocess.call(command, shell=False)
            except Exception as exception:
                pass
        else:
            raise Exception("Failed to get NFS export details for volume")                            

        statinfo = os.stat(restored_file_path)
        restore_obj = db.restore_update(self.cntx, 
                                        restore_obj.id,
                                        {'uploaded_size_incremental': statinfo.st_size})

        return self.restored_volume['id']

    @autolog.log_method(Logger, 'RestoreNFSVolume.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.volume_service.delete(self.cntx, self.restored_volume)
        except:
            pass
        
class RestoreSANVolume(task.Task):
    """
       Restore cinder san volume from qcow2
       SAN volumes including iscsi and fc channel volumes
    """

    def execute(self, context, restore_id, instance_options, volume_type,
                vm_resource_id, restored_file_path):
        return self.execute_with_log(context, restore_id, instance_options,
                                     volume_type,  
                                     vm_resource_id, restored_file_path)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreSANVolume.execute')
    def execute_with_log(self, context, restore_id, instance_options, volume_type,
                         vm_resource_id, restored_file_path):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.volume_service = volume_service = cinder.API()
        restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)        
        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)
        
        time_offset = datetime.datetime.now() - datetime.datetime.utcnow()
        #desciption = 'Restored from Snap_' + (snapshot_obj.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p")
        volume_size = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_size')
        volume_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_name')
        volume_description = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_description')
        volume_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id')
        az = ''
        if db.get_metadata_value(snapshot_vm_resource.metadata,'availability_zone'):
           az = db.get_metadata_value(snapshot_vm_resource.metadata,'availability_zone')
 
        availability_zone = get_availability_zone(instance_options,
                                                  volume_id=volume_id,
                                                  az=az)

        progressmsg = _('Restoring SAN Volume ' + volume_name + ' from snapshot ' + snapshot_obj.id)
        LOG.debug(progressmsg)
        db.restore_update(self.cntx,  restore_id, {'progress_msg': progressmsg, 'status': 'uploading' })             

        self.restored_volume = volume_service.create(self.cntx, 
                                                     volume_size,
                                                     volume_name,
                                                     volume_description, 
                                                     volume_type = volume_type,
                                                     availability_zone=availability_zone)

        if not self.restored_volume:
            raise Exception("Failed to create volume type " + volume_type)

        start_time = timeutils.utcnow()
        while True:
            time.sleep(10)
            self.restored_volume = volume_service.get(self.cntx, self.restored_volume['id'])
            if self.restored_volume['status'].lower() == 'available' or\
                self.restored_volume['status'].lower() == 'error':
                break
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=4):
                raise exception.ErrorOccurred(reason='Timeout restoring SAN Volume')               

        if self.restored_volume['status'].lower() == 'error':
            raise Exception("Failed to create volume type " + volume_type)

        return self.restored_volume['id']

    @autolog.log_method(Logger, 'RestoreSANVolume.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            if self.restored_volume:
                self.volume_service.delete(self.cntx, self.restored_volume)
        except:
            pass

class RestoreInstanceFromVolume(task.Task):
    """
       Restore instance from cinder volume
    """

    def execute(self, context, vmname, restore_id,
                volume_id, restore_type, instance_options,
                restored_security_groups, restored_nics,
                restored_compute_flavor_id, keyname):
        return self.execute_with_log(context, vmname, restore_id,
                                    volume_id, restore_type, instance_options,
                                    restored_security_groups, restored_nics,
                                    restored_compute_flavor_id, keyname)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreInstanceFromVolume.execute')
    def execute_with_log(self, context, vmname, restore_id,
                         volume_id, restore_type, instance_options,
                         restored_security_groups, restored_nics,
                         restored_compute_flavor_id, keyname):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))

        restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)


        restored_instance_name = vmname
        if instance_options and 'name' in instance_options:
            restored_instance_name = instance_options['name']

        LOG.debug('Creating Instance ' + restored_instance_name)
        snapshot_obj = db.snapshot_update(  self.cntx, snapshot_obj.id,
                                            {'progress_msg': 'Creating Instance: '+ restored_instance_name,
                                             'status': 'restoring'
                                            })        

        availability_zone = get_availability_zone(instance_options)
    
        restored_compute_flavor = compute_service.get_flavor_by_id(self.cntx, restored_compute_flavor_id)

        self.volume_service = volume_service = cinder.API()

        restored_volume = volume_service.get(self.cntx, volume_id)
        try:
            volume_service.set_bootable(self.cntx, restored_volume)
        except Exception as ex:
            LOG.exception(ex)
            
        block_device_mapping = {u'vda': volume_id+":vol"}

        self.restored_instance = restored_instance = \
                     compute_service.create_server(self.cntx, restored_instance_name, 
                                                   None, restored_compute_flavor, 
                                                   nics=restored_nics,
                                                   block_device_mapping=block_device_mapping,
                                                   security_groups=[], 
                                                   key_name=keyname,
                                                   availability_zone=availability_zone)

        if not restored_instance:
            raise Exception("Cannot create instance from image")

        start_time = timeutils.utcnow()
        while hasattr(restored_instance,'status') == False or restored_instance.status != 'ACTIVE':
            LOG.debug('Waiting for the instance ' + restored_instance.id + ' to boot' )
            time.sleep(10)
            restored_instance =  compute_service.get_server_by_id(self.cntx, restored_instance.id)
            if hasattr(restored_instance,'status'):
                if restored_instance.status == 'ERROR':
                    raise Exception(_("Error creating instance " + restored_instance.id))
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=4):
                raise exception.ErrorOccurred(reason='Timeout waiting for the instance to boot from volume')                   

        self.restored_instance = restored_instance
        return restored_instance.id

    @autolog.log_method(Logger, 'RestoreInstanceFromVolume.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.compute_service.delete(self.cntx, self.restored_instance.id)
        except:
            pass

class RestoreInstanceFromImage(task.Task):
    """
       Restore instance from glance image
    """

    def execute(self, context, vmname, restore_id,
                image_id, restore_type, instance_options,
                restored_security_groups, restored_nics,
                restored_compute_flavor_id, keyname):
        return self.execute_with_log(context, vmname, restore_id,
                                    image_id, restore_type, instance_options,
                                    restored_security_groups, restored_nics,
                                    restored_compute_flavor_id, keyname)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreInstanceFromImage.execute')
    def execute_with_log(self, context, vmname, restore_id,
                         image_id, restore_type, instance_options,
                         restored_security_groups, restored_nics,
                         restored_compute_flavor_id, keyname):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))

        restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)

        restored_instance_name = vmname
        if instance_options and 'name' in instance_options:
            restored_instance_name = instance_options['name']

        # refresh the token
        self.cntx = nova._get_tenant_context(self.cntx)

        restored_compute_image = compute_service.get_image(self.cntx, image_id)
        LOG.debug('Creating Instance ' + restored_instance_name) 
        snapshot_obj = db.snapshot_update(  self.cntx, snapshot_obj.id,
                                            {'progress_msg': 'Creating Instance: '+ restored_instance_name,
                                             'status': 'restoring'
                                            })  
        
        availability_zone = get_availability_zone(instance_options)
    
        restored_compute_flavor = compute_service.get_flavor_by_id(self.cntx, restored_compute_flavor_id)
        self.restored_instance = restored_instance = \
                     compute_service.create_server(self.cntx, restored_instance_name, 
                                                   restored_compute_image, restored_compute_flavor, 
                                                   nics=restored_nics,
                                                   security_groups=[],
                                                   key_name=keyname,
                                                   availability_zone=availability_zone)
        if not restored_instance:
            raise Exception("Cannot create instance from image")
        
        start_time = timeutils.utcnow()
        while hasattr(restored_instance,'status') == False or restored_instance.status != 'ACTIVE':
            LOG.debug('Waiting for the instance ' + restored_instance.id + ' to boot' )
            time.sleep(10)

            restored_instance =  compute_service.get_server_by_id(self.cntx, restored_instance.id)
            if hasattr(restored_instance,'status'):
                if restored_instance.status == 'ERROR':
                    raise Exception(_("Error creating instance " + restored_instance.id))
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=10*60):
                raise exception.ErrorOccurred(reason='Timeout waiting for the instance to boot from image')                     

        return restored_instance.id

    @autolog.log_method(Logger, 'RestoreInstanceFromImage.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.compute_service.delete(self.cntx, self.restored_instance.id)
        except:
            pass
        pass


class AdjustSG(task.Task):
    """
       Adjust security groups
    """

    def execute(self, context, restored_instance_id, restore_type,
                restored_security_groups):
        return self.execute_with_log(context, restored_instance_id,
                                     restore_type, restored_security_groups)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'AdjustSG.execute')
    def execute_with_log(self, context, restored_instance_id,
                         restore_type, restored_security_groups):
       
        try:
            self.db = db = WorkloadMgrDB().db
            self.cntx = amqp.RpcContext.from_dict(context)

            # refresh the token
            self.cntx = nova._get_tenant_context(self.cntx)
        
            self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))
            sec_groups = compute_service.list_security_group(self.cntx, restored_instance_id)
            sec_group_ids = [sec.id for sec in sec_groups]
            ids_to_remove = set(sec_group_ids) - set(restored_security_groups.values())
            ids_to_add = set(restored_security_groups.values()) - set(sec_group_ids)
            # remove security groups that were not asked for
            for sec in ids_to_remove:
                compute_service.remove_security_group(self.cntx, restored_instance_id,
                                                      sec)

            for sec in ids_to_add:
                compute_service.add_security_group(self.cntx, restored_instance_id,
                                                   sec)
        except Exception as ex:
            LOG.exception(ex)
            msg = "Could not update security groups on the " \
                  "restored instance %s" % restored_instance_id
            LOG.warning(msg)

    @autolog.log_method(Logger, 'AdjustSG.revert')
    def revert_with_log(self, *args, **kwargs):
        pass

class AttachVolume(task.Task):
    """
       Attach volume to the instance
    """

    def execute(self, context, restored_instance_id,
                volume_id, restore_type, devname):
        return self.execute_with_log(context, restored_instance_id, volume_id,
                restore_type, devname)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'AttachVolume.execute')
    def execute_with_log(self, context, restored_instance_id, volume_id,
                         restore_type, devname):
        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        # refresh the token
        self.cntx = nova._get_tenant_context(self.cntx)
        
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))
        self.volume_service = volume_service = cinder.API()
        if restore_type == 'restore':
            self.restored_volume = restored_volume = volume_service.get(self.cntx, volume_id)
            start_time = timeutils.utcnow()
            while restored_volume['status'].lower() != 'available' and restored_volume['status'].lower() != 'error':
                LOG.debug('Waiting for volume ' + restored_volume['id'] + ' to be available')
                time.sleep(10)
                restored_volume = volume_service.get(self.cntx, volume_id)
                now = timeutils.utcnow()
                if (now - start_time) > datetime.timedelta(minutes=4):
                    raise exception.ErrorOccurred(reason='Timeout waiting for the volume ' + volume_id + ' to be available')                   
            
            LOG.debug('Attaching volume ' + volume_id)
            compute_service.attach_volume(self.cntx, restored_instance_id, volume_id, ('/dev/' + devname))
            time.sleep(15)
        else:
            params = {'path': restored_volume, 'mountpoint': '/dev/' + devname}
            compute_service.testbubble_attach_volume(self.cntx, restored_instance_id, params)
        pass

    @autolog.log_method(Logger, 'AttachVolume.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.compute_service.detach_volume(self.cntx, self.restored_volume)
        except:
            pass

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
                vm_resource_id,
                volume_id = None, volume_type = None,
                image_id = None, image_type = None):
        return self.execute_with_log(context, restored_instance_id, 
                                     volume_id, volume_type,
                                     image_id, image_type, 
                                     restore_id, restore_type,
                                     restored_file_path,
                                     image_overlay_file_path,
                                     progress_tracking_file_path,
                                     vm_resource_id)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'CopyBackupImageToVolume.execute')
    def execute_with_log(self, context, restored_instance_id, 
                         volume_id, volume_type,
                         image_id, image_type, 
                         restore_id, restore_type,
                         restored_file_path, 
                         image_overlay_file_path,
                         progress_tracking_file_path,
                         vm_resource_id):
 
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
        snapshot_vm_resource = db.snapshot_vm_resource_get(cntx, vm_resource_id)
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
                    elif time.time() - basetime > CONF.progress_tracking_update_interval:
                        raise Exception("No update to %s modified time for last %d minutes. "
                                        "Contego may have errored. Aborting Operation" % 
                                        (progress_tracking_file_path, CONF.progress_tracking_update_interval/60))
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
                                              snapshot_vm_resource.restore_size/100)
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

class PowerOffInstance(task.Task):
    """
       Power Off restored instance
    """

    def execute(self, context, restored_instance_id, restore_type):
        return self.execute_with_log(context, restored_instance_id,
                                     restore_type)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'PowerOffInstance.execute')
    def execute_with_log(self, context, restored_instance_id, restore_type):
        self.cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = \
                       nova.API(production = (restore_type == 'restore'))

        compute_service.stop(self.cntx, restored_instance_id) 

        restored_instance =  compute_service.get_server_by_id(self.cntx,
                                                        restored_instance_id)
        start_time = timeutils.utcnow()
        while hasattr(restored_instance,'status') == False or \
              restored_instance.status != 'SHUTOFF':
            LOG.debug('Waiting for the instance ' + restored_instance_id +\
                      ' to shutdown' )
            time.sleep(10)
            restored_instance =  compute_service.get_server_by_id(self.cntx,
                                                        restored_instance_id)
            if hasattr(restored_instance,'status'):
                if restored_instance.status == 'ERROR':
                    raise Exception(_("Error creating instance " + \
                                        restored_instance_id))
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=4):
                raise exception.ErrorOccurred(reason='Timeout waiting for '
                                           'the instance to boot from volume')                   

        self.restored_instance = restored_instance
        return

    @autolog.log_method(Logger, 'PowerOffInstance.revert')
    def revert_with_log(self, *args, **kwargs):
        pass

class PowerOnInstance(task.Task):
    """
       Power On restored instance
    """

    def execute(self, context, restored_instance_id, restore_type):
        return self.execute_with_log(context, restored_instance_id,
                                     restore_type)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'PowerOnInstance.execute')
    def execute_with_log(self, context, restored_instance_id, restore_type):
        self.cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = \
                       nova.API(production = (restore_type == 'restore'))

        compute_service.start(self.cntx, restored_instance_id)

        restored_instance =  compute_service.get_server_by_id(self.cntx,
                                                        restored_instance_id)
        start_time = timeutils.utcnow()
        while hasattr(restored_instance,'status') == False or \
              restored_instance.status != 'ACTIVE':
            LOG.debug('Waiting for the instance ' + restored_instance_id +\
                      ' to boot' )
            time.sleep(10)
            restored_instance =  compute_service.get_server_by_id(self.cntx,
                                                        restored_instance_id)
            if hasattr(restored_instance,'status'):
                if restored_instance.status == 'ERROR':
                    raise Exception(_("Error creating instance " + \
                                        restored_instance_id))
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=5):
                raise exception.ErrorOccurred(reason='Timeout waiting for '\
                                           'the instance to boot from volume')                   

        self.restored_instance = restored_instance
        return

    @autolog.log_method(Logger, 'PowerOnInstance.revert')
    def revert_with_log(self, *args, **kwargs):
        pass


class AssignFloatingIP(task.Task):
    """
       Assign floating IP address to restored instance.
       Valid only for one click restore
    """

    def execute(self, context, restored_instance_id, restored_nics,
                restored_net_resources, restore_type):
        return self.execute_with_log(context, restored_instance_id,
                                     restored_nics, restored_net_resources,
                                     restore_type)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'AssignFloatingIP.execute')
    def execute_with_log(self, context, restored_instance_id, restored_nics,
                         restored_net_resources, restore_type):
        self.cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = \
                       nova.API(production = (restore_type == 'restore'))
        for mac, details in restored_net_resources.iteritems():
            for nic in restored_nics:
                try:
                    if ( (details.get('id',None) and nic.get('port-id', None) ) and
                             (details.get('id', None) == nic.get('port-id', None)) ) or\
                         details.get('ip_address',None) == nic.get('v4-fixed-ip') and \
                                        details.get('floating_ip', None) is not None:

                        if details.get('id',None) and nic.get('port-id', None):
                            floating_ip = json.loads(details.get('floating_ip', None))['addr']
                            fixed_ip = details['fixed_ips'][0]['ip_address']
                        else:
                            floating_ip = details.get('floating_ip', None)
                            fixed_ip = details.get('fixed_ip', None)

                        floating_ips_list = compute_service.floating_ip_list(self.cntx)
                        for fp in floating_ips_list:
                            if fp.ip == floating_ip and (fp.instance_id == '' or fp.instance_id == None):
                                compute_service.add_floating_ip(self.cntx, restored_instance_id,
                                                                floating_ip, fixed_ip)

                except:
                    # we will ignore any exceptions during assigning floating ip address
                    pass
        return

    @autolog.log_method(Logger, 'AssignFloatingIP.revert')
    def revert_with_log(self, *args, **kwargs):
        pass


def LinearPrepareBackupImages(context, instance, instance_options, snapshotobj, restore_id):
    flow = lf.Flow("processbackupimageslf")
    db = WorkloadMgrDB().db
    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        flow.add(PrepareBackupImage("PrepareBackupImage" + snapshot_vm_resource.id,
                                    rebind=dict(vm_resource_id=snapshot_vm_resource.id,
                                                volume_type='volume_type_'+snapshot_vm_resource.id),
                                    provides=('restore_file_path_' + str(snapshot_vm_resource.id),
                                              'image_overlay_file_path_' + str(snapshot_vm_resource.id),
                                              'image_virtual_size_' + str(snapshot_vm_resource.id))))
    return flow

def LinearUploadImagesToGlance(context, instance, instance_options,
                               snapshotobj, restore_id, store):
    flow = lf.Flow("uploadimageslf")
    db = WorkloadMgrDB().db

    snapshot_vm_resources = db.snapshot_vm_resources_get(context, instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        if db.get_metadata_value(snapshot_vm_resource.metadata, 'image_id'):
            flow.add(UploadImageToGlance("UploadImagesToGlance" + snapshot_vm_resource.id,
                                         rebind=dict( vm_resource_id=snapshot_vm_resource.id,
                                                      restore_file_path='restore_file_path_'+snapshot_vm_resource.id),
                                         provides=('image_id_' + str(snapshot_vm_resource.id),
                                                   'image_type_' + str(snapshot_vm_resource.id))))
        elif db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id'):
            if not is_supported_backend(store['volume_type_'+snapshot_vm_resource.id]):
                # Fallback to default mode of glance backed images
                flow.add(UploadImageToGlance("UploadImagesToGlance" + snapshot_vm_resource.id,
                                             rebind=dict( vm_resource_id=snapshot_vm_resource.id,
                                                          restore_file_path='restore_file_path_'+snapshot_vm_resource.id),
                                             provides=('image_id_' + str(snapshot_vm_resource.id),
                                                       'image_type_' + str(snapshot_vm_resource.id))))

    return flow

def RestoreVolumes(context, instance, instance_options, snapshotobj, restore_id):
    flow = lf.Flow("restorevolumeslf")

    db = WorkloadMgrDB().db
    volume_service = cinder.API()
    snapshot_vm_resources = db.snapshot_vm_resources_get(context, instance['vm_id'], snapshotobj.id)

    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        if db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id'):
            volume_type = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_type')
            if volume_type:
                volume_type = volume_type.lower()
            else:
                volume_type='default'
            volume_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id').lower()
  
            new_volume_type = get_new_volume_type(instance_options, volume_id, volume_type)

            #if [vtype for vtype in CONF.nfs_volume_type_substr.split(',') if vtype in new_volume_type]:
            if False:
                flow.add(RestoreNFSVolume("RestoreNFSVolume" + snapshot_vm_resource.id,
                                    rebind=dict(vm_resource_id=snapshot_vm_resource.id, 
                                                volume_type='volume_type_'+snapshot_vm_resource.id,
                                                restored_file_path='restore_file_path_' + str(snapshot_vm_resource.id)),
                                    provides='volume_id_' + str(snapshot_vm_resource.id)))
            else:
                flow.add(RestoreSANVolume("RestoreSANVolume" + snapshot_vm_resource.id,
                                    rebind=dict(vm_resource_id=snapshot_vm_resource.id, 
                                                volume_type='volume_type_'+snapshot_vm_resource.id,
                                                restored_file_path='restore_file_path_' + str(snapshot_vm_resource.id)),
                                    provides='volume_id_' + str(snapshot_vm_resource.id)))
            """
            else:
                # Default restore path for backends that we don't recognize
                flow.add(RestoreVolumeFromImage("RestoreVolumeFromImage" + snapshot_vm_resource.id,
                        rebind=dict(vm_resource_id=snapshot_vm_resource.id, 
                                    image_id='image_id_' + str(snapshot_vm_resource.id),
                                    volume_type='volume_type_'+snapshot_vm_resource.id,
                                    image_virtual_size='image_virtual_size_' + str(snapshot_vm_resource.id)),
                        provides='volume_id_' + str(snapshot_vm_resource.id)))
            """

    return flow

def RestoreInstance(context, instance, snapshotobj, restore_id):

    flow = lf.Flow("restoreinstancelf")
    db = WorkloadMgrDB().db
    snapshot_vm_resources = db.snapshot_vm_resources_get(context, instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        if snapshot_vm_resource.resource_name != 'vda':
            continue        
        if db.get_metadata_value(snapshot_vm_resource.metadata, 'image_id'):
            flow.add(RestoreInstanceFromImage("RestoreInstanceFromImage" + instance['vm_id'],
                                rebind=dict(image_id='image_id_' + str(snapshot_vm_resource.id)),
                                provides='restored_instance_id'))            
        else:
            flow.add(RestoreInstanceFromVolume("RestoreInstanceFromVolume" + instance['vm_id'],
                                rebind=dict(volume_id='volume_id_' + str(snapshot_vm_resource.id)),
                                provides='restored_instance_id'))
    return flow


def AdjustInstanceSecurityGroups(context, instance, snapshotobj, restore_id):
    flow = lf.Flow("adjustinstancesecuritygrouplf")
    db = WorkloadMgrDB().db

    flow.add(AdjustSG("AdjustSG"))

    return flow


def AttachVolumes(context, instance, snapshotobj, restore_id):
    flow = lf.Flow("attachvolumeslf")
    db = WorkloadMgrDB().db
    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        if snapshot_vm_resource.resource_name == 'vda':
            continue
        if db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id'):
            flow.add(AttachVolume("AttachVolume" + snapshot_vm_resource.id,
                                  rebind=dict(volume_id='volume_id_' + str(snapshot_vm_resource.id),
                                  devname='devname_' + str(snapshot_vm_resource.id),)))
    return flow

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
                                              vm_resource_id=snapshot_vm_resource.id, 
                                              )))
        elif db.get_metadata_value(snapshot_vm_resource.metadata, 'image_id'):
            flow.add(CopyBackupImageToVolume("CopyBackupImageToVolume" + snapshot_vm_resource.id,
                                  rebind=dict(image_id='image_id_' + str(snapshot_vm_resource.id),
                                              image_type='image_type_'+str(snapshot_vm_resource.id),
                                              restored_file_path='restore_file_path_' + str(snapshot_vm_resource.id),
                                              progress_tracking_file_path='progress_tracking_file_path_'+str(snapshot_vm_resource.id),
                                              image_overlay_file_path='image_overlay_file_path_' + str(snapshot_vm_resource.id),
                                              vm_resource_id=snapshot_vm_resource.id, 
                                              )))            
    return flow

def PowerOffInstanceFlow(context):

    flow = lf.Flow("poweroffinstancelf")
    flow.add(PowerOffInstance("PowerOffInstance"))

    return flow

def PowerOnInstanceFlow(context):

    flow = lf.Flow("poweroninstancelf")
    flow.add(PowerOnInstance("PowerOnInstance"))

    return flow

def AssignFloatingIPFlow(context):

    flow = lf.Flow("assignfloatingiplf")
    flow.add(AssignFloatingIP("AssignFloatingIP"))

    return flow

def FreezeNThawFlow(context):

    flow = lf.Flow("freezenthawlf")
    flow.add(FreezeVM("FreezeVM", rebind={'instance': 'restored_instance_id', 'snapshot': 'restored_instance_id', 
                 'source_platform': 'restored_instance_id', 'restored_instance_id': 'restored_instance_id'}))
    flow.add(ThawVM("ThawVM", rebind={'instance': 'restored_instance_id', 'snapshot': 'restored_instance_id', 
                  'source_platform': 'restored_instance_id', 'restored_instance_id': 'restored_instance_id'}))

    return flow

def restore_vm(cntx, db, instance, restore, restored_net_resources,
               restored_security_groups, restored_compute_flavor,
               restored_nics, instance_options):

    restore_obj = db.restore_get(cntx, restore['id'])
    snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
    workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)

    backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                            'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)

    test = (restore['restore_type'] == 'test')
    
    msg = 'Creating VM ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id  
    db.restore_update(cntx,  restore_obj.id, {'progress_msg': msg}) 
   
    # refresh the token so we are attempting each VM restore with a new token

    cntx = nova._get_tenant_context(cntx)

    context_dict = dict([('%s' % key, value)
                          for (key, value) in cntx.to_dict().iteritems()])            
    context_dict['conf'] =  None # RpcContext object looks for this during init

    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'],
                                                                 snapshot_obj.id)

    restored_security_group_ids = {}
    vm_id = instance['vm_id']
    if restored_security_groups:
        for pit_id, restored_security_group_id in restored_security_groups[vm_id].iteritems():
            restored_security_group_ids[pit_id] = restored_security_group_id

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
                'restored_net_resources': restored_net_resources,    
                'restored_security_groups': restored_security_group_ids,
                'restored_compute_flavor_id': restored_compute_flavor.id,
                'restored_nics': restored_nics,
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

        if snapshot_vm_resource.resource_type == 'nic':
            vm_nic_snapshot = db.vm_network_resource_snap_get(cntx, snapshot_vm_resource.id)
            nic_data = pickle.loads(str(vm_nic_snapshot.pickle))
            mac_address = nic_data['mac_address']

    LOG.info(_('Processing disks'))
    _restorevmflow = lf.Flow(instance['vm_id'] + "RestoreInstance")

    childflow = LinearPrepareBackupImages(cntx, instance, instance_options,
                                          snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    # This is a linear uploading all vm images to glance
    childflow = LinearUploadImagesToGlance(cntx, instance, instance_options,
                                           snapshot_obj, restore['id'], store)
    if childflow:
        _restorevmflow.add(childflow)

    # create nova/cinder objects from image ids
    childflow = RestoreVolumes(cntx, instance, instance_options,
                               snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    # create nova from image id
    childflow = RestoreInstance(cntx, instance, snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    # create nova from image id
    childflow = AdjustInstanceSecurityGroups(cntx, instance, snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    # power off the restored instance until all volumes are attached
    childflow = PowerOffInstanceFlow(cntx)
    if childflow:
        _restorevmflow.add(childflow)

    # attach restored volumes to restored instances
    childflow = AttachVolumes(cntx, instance, snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    # copy data if the volumes are iscsi volumes
    # attach restored volumes to restored instances
    childflow = CopyBackupImagesToVolumes(cntx, instance,
                                          snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    # power on the restored instance until all volumes are attached
    childflow = PowerOnInstanceFlow(cntx)
    if childflow:
        _restorevmflow.add(childflow)

    # Assign floating IP address
    childflow = AssignFloatingIPFlow(cntx)
    if childflow:
        _restorevmflow.add(childflow)

    childflow = FreezeNThawFlow(cntx)
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
        
        if test == True:
            LOG.debug(_("Test Restore Completed"))
        else:
            LOG.debug(_("Restore Completed"))
         
        # Cleanup any intermediatory files that were created
        # should be a separate task?
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type != 'disk':
                continue
            temp_directory = os.path.join("/var/triliovault", restore['id'], snapshot_vm_resource.id)
            try:
                shutil.rmtree(temp_directory)
            except OSError as exc:
                pass 

        db.restore_update(cntx, restore_obj.id, 
                          {'progress_msg': 'Created VM ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id,
                           'status': 'executing'
                          })        
        db.restore_update( cntx, restore_obj.id,
                           {'progress_msg': 'Created VM:' + restored_vm['vm_id'], 'status': 'executing'})
        return restored_vm          
    else:
        raise Exception("Restoring VM instance failed")
