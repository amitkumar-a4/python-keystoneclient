import os
import uuid
from Queue import Queue
import cPickle as pickle
import json
import shutil
import math
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
from taskflow.utils import reflection

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


restore_vm_opts = [
    cfg.StrOpt('ceph_pool_name',
               default='volumes',
               help='Ceph pool name configured for Cinder'),
    cfg.StrOpt('cinder_nfs_mount_point_base',
               default='/opt/stack/data/mnt',
               help='Dir where the nfs volume is mounted for restore'),                   
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

    return volume_type

def is_supported_backend(volume_type):

    if volume_type:
        return 'ceph' in volume_type.lower() or \
               'nfs' in volume_type.lower()
    else:
        return False

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
        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(self.cntx, snapshot_vm_resource.id) 
        
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

        progressmsg = _('Uploading image of instance %(vmid)s from \
                        snapshot %(snapshot_id)s') % \
                        {'vmid': vmid, 'snapshot_id': snapshot_id}

        LOG.debug(progressmsg)

        db.restore_update(self.cntx,  restore_id,
                          {'progress_msg': progressmsg, 'status': 'uploading' })                  
        #upload to glance
        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(self.cntx, snapshot_vm_resource.id)
        image_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'image_name')
        if not image_name:
            image_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_name')

        time_offset = datetime.datetime.now() - datetime.datetime.utcnow()
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
        user_id = self.cntx.user
        project_id = self.cntx.tenant
        self.cntx = nova._get_tenant_context(user_id, project_id)

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

        self.imageid = restored_image['id']
        return restored_image['id']

    @autolog.log_method(Logger, 'UploadImageToGlance.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            user_id = self.cntx.user
            project_id = self.cntx.tenant
            self.cntx = nova._get_tenant_context(user_id, project_id)
            self.image_service.delete(self.cntx, self.imageid)
        except:
            pass

class RestoreVolumeFromImage(task.Task):
    """
       Restore volume from glance image
    """

    def execute(self, context, vmid, restore_id, vm_resource_id,
                imageid, image_virtual_size):
        return self.execute_with_log(context, vmid, restore_id,
                                     vm_resource_id, imageid, image_virtual_size)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreVolumeFromImage.execute')
    def execute_with_log(self, context, vmid, restore_id,
                         vm_resource_id, imageid, image_virtual_size):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.restore_obj = restore_obj = db.restore_get(self.cntx, restore_id)

        self.image_service = glance.get_default_image_service(production= (restore_obj['restore_type'] != 'test'))
        self.volume_service = volume_service = cinder.API()

        restored_image = self.image_service.show(self.cntx, imageid)

        restored_volume_name = uuid.uuid4().hex
        LOG.debug('Restoring volume from image ' + imageid)

        volume_size = int(math.ceil(image_virtual_size/(float)(1024*1024*1024)))
        self.restored_volume = restored_volume = volume_service.create(self.cntx, volume_size,
                                                restored_volume_name,
                                                'from Trilio Vault', None,
                                                imageid, None, None, None)

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
                user_id = self.cntx.user
                project_id = self.cntx.tenant
                self.cntx = nova._get_tenant_context(user_id, project_id)

        self.image_service.delete(self.cntx, imageid)
        if restored_volume['status'].lower() == 'error':
            LOG.error(_("Volume from image %s could not successfully create") % imageid)
            raise Exception("Restoring volume failed")

        restore_obj = db.restore_update(self.cntx, restore_obj.id, {'uploaded_size_incremental': restored_image['size']})

        return restored_volume['id']

    @autolog.log_method(Logger, 'RestoreVolumeFromImage.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.volume_service.delete(self.cntx, self.restored_volume)
        except:
            pass

class RestoreCephVolume(task.Task):
    """
       Restore cinder volume from qcow2
    """

    def create_volume_from_file(self, filename, volume_name):
        kwargs = {}
        args = [filename]
        args += ['rbd:'+volume_name]
        out, err = utils.execute('qemu-img', 'convert', '-O',
                                 'raw', *args, **kwargs)
        return

    def rename_volume(self, source, target):
        args = [source]
        args += [target]
        kwargs = {'run_as_root':True}
        out, err = utils.execute('rbd', 'mv', *args, **kwargs)
        return

    def delete_volume(self, volume_name):
        args = [volume_name]
        kwargs = {'run_as_root':True}
        out, err = utils.execute('rbd', 'rm', *args, **kwargs)
        return
 
    def execute(self, context, restore_id, volume_type, image_virtual_size,
                     restored_file_path):
        return self.execute_with_log(context, restore_id, volume_type,
                     image_virtual_size, restored_file_path)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreCephVolume.execute')
    def execute_with_log(self, context, restore_id, volume_type,
                         image_virtual_size, restored_file_path):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.volume_service = volume_service = cinder.API()
        restore_obj = db.restore_get(self.cntx, restore_id)
     
        restored_volume_name = uuid.uuid4().hex

        volume_size = int(math.ceil(image_virtual_size/(float)(1024*1024*1024)))
        self.restored_volume = restored_volume = volume_service.create(self.cntx, volume_size,
                                                      restored_volume_name,
                                                      'from Trilio Vault', None,
                                                      None, volume_type, None, None)

        if not restored_volume:
            raise Exception("Cannot create volume from image")

        start_time = timeutils.utcnow()
        while True:
            time.sleep(10)
            restored_volume = volume_service.get(self.cntx, restored_volume['id'])
            if restored_volume['status'].lower() == 'available' or\
                restored_volume['status'].lower() == 'error':
                break
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=4):
                raise exception.ErrorOccurred(reason='Timeout restoring CEPH Volume')                

        if restored_volume['status'].lower() == 'error':
            LOG.error(_("Volume from image could not successfully create"))
            raise Exception("Restoring volume failed")

        # import image to rbd volume
        volume_name = CONF.ceph_pool_name + '/' + "volume-" + str(uuid.uuid4().hex)
        self.create_volume_from_file(restored_file_path, volume_name)
        
        # delete volume created by cinder
        cinder_volume_name = CONF.ceph_pool_name + '/' + "volume-" \
                                + restored_volume['id']
        self.delete_volume(cinder_volume_name)

        # rename the other volume to cinder created volume name
        self.rename_volume(volume_name, cinder_volume_name)
        statinfo = os.stat(restored_file_path)

        restore_obj = db.restore_update(self.cntx, restore_obj.id,
                               {'uploaded_size_incremental': statinfo.st_size})

        return restored_volume['id']

    @autolog.log_method(Logger, 'RestoreCephVolume.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.volume_service.delete(self.cntx, self.restored_volume)
        except:
            pass

class RestoreNFSVolume(task.Task):
    """
       Restore cinder nfs volume from qcow2
    """

    def execute(self, context, restore_id, volume_type, vm_resource_id, restored_file_path):
        return self.execute_with_log(context, restore_id, volume_type,  
                                     vm_resource_id, restored_file_path)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreNFSVolume.execute')
    def execute_with_log(self, context, restore_id, volume_type,
                         vm_resource_id, restored_file_path):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.volume_service = volume_service = cinder.API()
        restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)        
        snapshot_vm_resource = db.snapshot_vm_resource_get(self.cntx, vm_resource_id)
        
        time_offset = datetime.datetime.now() - datetime.datetime.utcnow()
        desciption = 'Restored from Snap_' + (snapshot_obj.created_at + time_offset).strftime("%m/%d/%Y %I:%M %p")
        volume_size = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_size')
        volume_type = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_type')
        volume_name = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_name')

        progressmsg = _('Restoring NFS Volume ' + volume_name + ' from snapshot ' + snapshot_obj.id)
        LOG.debug(progressmsg)
        db.restore_update(self.cntx,  restore_id, {'progress_msg': progressmsg, 'status': 'uploading' })             
        
        self.restored_volume = volume_service.create(self.cntx, 
                                                     volume_size,
                                                     volume_name,
                                                     desciption, 
                                                     volume_type = volume_type)

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
        
class RestoreInstanceFromVolume(task.Task):
    """
       Restore instance from cinder volume
    """

    def execute(self, context, vmname, restore_id,
                volumeid, restore_type, instance_options,
                restored_security_groups, restored_nics,
                restored_compute_flavor_id):
        return self.execute_with_log(context, vmname, restore_id,
                                    volumeid, restore_type, instance_options,
                                    restored_security_groups, restored_nics,
                                    restored_compute_flavor_id)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreInstanceFromVolume.execute')
    def execute_with_log(self, context, vmname, restore_id,
                         volumeid, restore_type, instance_options,
                         restored_security_groups, restored_nics,
                         restored_compute_flavor_id):

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
        
        if instance_options and 'availability_zone' in instance_options:
            availability_zone = instance_options['availability_zone']
        else:   
            if restore_type == 'test':   
                availability_zone = CONF.default_tvault_availability_zone
            else:
                if CONF.default_production_availability_zone == 'None':
                    availability_zone = None
                else:
                    availability_zone = CONF.default_production_availability_zone
    
        restored_security_group_ids = []
        for pit_id, restored_security_group_id in restored_security_groups.iteritems():
            restored_security_group_ids.append(restored_security_group_id)
                     
        restored_compute_flavor = compute_service.get_flavor_by_id(self.cntx, restored_compute_flavor_id)

        self.volume_service = volume_service = cinder.API()

        restored_volume = volume_service.get(self.cntx, volumeid)
        try:
            volume_service.set_bootable(self.cntx, restored_volume)
        except Exception as ex:
            LOG.exception(ex)
            
        block_device_mapping = {u'vda': volumeid+":vol"}

        self.restored_instance = restored_instance = \
                     compute_service.create_server(self.cntx, restored_instance_name, 
                                                   None, restored_compute_flavor, 
                                                   nics=restored_nics,
                                                   block_device_mapping=block_device_mapping,
                                                   security_groups=restored_security_group_ids, 
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
                imageid, restore_type, instance_options,
                restored_security_groups, restored_nics,
                restored_compute_flavor_id):
        return self.execute_with_log(context, vmname, restore_id,
                                    imageid, restore_type, instance_options,
                                    restored_security_groups, restored_nics,
                                    restored_compute_flavor_id)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreInstanceFromImage.execute')
    def execute_with_log(self, context, vmname, restore_id,
                         imageid, restore_type, instance_options,
                         restored_security_groups, restored_nics,
                         restored_compute_flavor_id):

        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))

        restore_obj = db.restore_get(self.cntx, restore_id)
        snapshot_obj = db.snapshot_get(self.cntx, restore_obj.snapshot_id)

        restored_instance_name = vmname
        if instance_options and 'name' in instance_options:
            restored_instance_name = instance_options['name']

        # refresh the token
        user_id = self.cntx.user
        project_id = self.cntx.tenant
        self.cntx = nova._get_tenant_context(user_id, project_id)

        restored_compute_image = compute_service.get_image(self.cntx, imageid)
        LOG.debug('Creating Instance ' + restored_instance_name) 
        snapshot_obj = db.snapshot_update(  self.cntx, snapshot_obj.id,
                                            {'progress_msg': 'Creating Instance: '+ restored_instance_name,
                                             'status': 'restoring'
                                            })  
                
        if instance_options and 'availability_zone' in instance_options:
            availability_zone = instance_options['availability_zone']
        else:   
            if restore_type == 'test':   
                availability_zone = CONF.default_tvault_availability_zone
            else:
                if CONF.default_production_availability_zone == 'None':
                    availability_zone = None
                else:
                    availability_zone = CONF.default_production_availability_zone
    
        restored_security_group_ids = []
        for pit_id, restored_security_group_id in restored_security_groups.iteritems():
            restored_security_group_ids.append(restored_security_group_id)
                     
        restored_compute_flavor = compute_service.get_flavor_by_id(self.cntx, restored_compute_flavor_id)
        self.restored_instance = restored_instance = \
                     compute_service.create_server(self.cntx, restored_instance_name, 
                                                   restored_compute_image, restored_compute_flavor, 
                                                   nics=restored_nics,
                                                   security_groups=restored_security_group_ids, 
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

class AttachVolume(task.Task):
    """
       Attach volume to the instance
    """

    def execute(self, context, restored_instance_id,
                volumeid, restore_type, devname):
        return self.execute_with_log(context, restored_instance_id, volumeid,
                restore_type, devname)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'AttachVolume.execute')
    def execute_with_log(self, context, restored_instance_id, volumeid,
                         restore_type, devname):
        self.db = db = WorkloadMgrDB().db
        self.cntx = amqp.RpcContext.from_dict(context)
        # refresh the token
        user_id = self.cntx.user
        project_id = self.cntx.tenant
        self.cntx = nova._get_tenant_context(user_id, project_id)
        
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))
        self.volume_service = volume_service = cinder.API()
        if restore_type == 'restore':
            self.restored_volume = restored_volume = volume_service.get(self.cntx, volumeid)
            start_time = timeutils.utcnow()
            while restored_volume['status'].lower() != 'available' and restored_volume['status'].lower() != 'error':
                LOG.debug('Waiting for volume ' + restored_volume['id'] + ' to be available')
                time.sleep(10)
                restored_volume = volume_service.get(self.cntx, volumeid)
                now = timeutils.utcnow()
                if (now - start_time) > datetime.timedelta(minutes=4):
                    raise exception.ErrorOccurred(reason='Timeout waiting for the volume ' + volumeid + ' to be available')                   
                
            LOG.debug('Attaching volume ' + volumeid)
            compute_service.attach_volume(self.cntx, restored_instance_id, volumeid, ('/dev/' + devname))
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

def LinearPrepareBackupImages(context, instance, instance_options, snapshotobj, restoreid):
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
                                              'image_virtual_size_' + str(snapshot_vm_resource.id))))
    return flow

def LinearUploadImagesToGlance(context, instance, instance_options,
                               snapshotobj, restoreid, store):
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
                                         provides='image_id_' + str(snapshot_vm_resource.id)))
        elif db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id'):

            if not is_supported_backend(store['volume_type_'+snapshot_vm_resource.id]):
                # Fallback to default mode of glance backed images
                flow.add(UploadImageToGlance("UploadImagesToGlance" + snapshot_vm_resource.id,
                                         rebind=dict( vm_resource_id=snapshot_vm_resource.id,
                                                      restore_file_path='restore_file_path_'+snapshot_vm_resource.id),
                                         provides='image_id_' + str(snapshot_vm_resource.id)))

    return flow

def RestoreVolumes(context, instance, instance_options, snapshotobj, restoreid):
    flow = lf.Flow("restorevolumeslf")

    db = WorkloadMgrDB().db
    volume_service = cinder.API()
    snapshot_vm_resources = db.snapshot_vm_resources_get(context, instance['vm_id'], snapshotobj.id)

    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        if db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id'):
            volume_type = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_type').lower()
            volume_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id').lower()
  
            volume_type = get_new_volume_type(instance_options, volume_id, volume_type)

            if 'ceph' in volume_type:
                flow.add(RestoreCephVolume("RestoreCephVolume" + snapshot_vm_resource.id,
                                    rebind=dict(restored_file_path='restore_file_path_' + str(snapshot_vm_resource.id),
                                                volume_type='volume_type_'+snapshot_vm_resource.id,
                                                image_virtual_size='image_virtual_size_'+ str(snapshot_vm_resource.id)),
                                    provides='volume_id_' + str(snapshot_vm_resource.id)))
            elif 'nfs' in volume_type:
                flow.add(RestoreNFSVolume("RestoreNFSVolume" + snapshot_vm_resource.id,
                                    rebind=dict(vm_resource_id=snapshot_vm_resource.id, 
                                                volume_type='volume_type_'+snapshot_vm_resource.id,
                                                restored_file_path='restore_file_path_' + str(snapshot_vm_resource.id)),
                                    provides='volume_id_' + str(snapshot_vm_resource.id)))                               
            else:
                # Default restore path for backends that we don't recognize
                flow.add(RestoreVolumeFromImage("RestoreVolumeFromImage" + snapshot_vm_resource.id,
                        rebind=dict(vm_resource_id=snapshot_vm_resource.id, 
                                    imageid='image_id_' + str(snapshot_vm_resource.id),
                                    image_virtual_size='image_virtual_size_' + str(snapshot_vm_resource.id)),
                        provides='volume_id_' + str(snapshot_vm_resource.id)))

    return flow

def RestoreInstance(context, instance, snapshotobj, restoreid):

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
                                rebind=dict(imageid='image_id_' + str(snapshot_vm_resource.id)),
                                provides='restored_instance_id'))            
        else:
            flow.add(RestoreInstanceFromVolume("RestoreInstanceFromVolume" + instance['vm_id'],
                                rebind=dict(volumeid='volume_id_' + str(snapshot_vm_resource.id)),
                                provides='restored_instance_id'))
    return flow

def AttachVolumes(context, instance, snapshotobj, restoreid):
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
                                  rebind=dict(volumeid='volume_id_' + str(snapshot_vm_resource.id),
                                  devname='devname_' + str(snapshot_vm_resource.id),)))
    return flow

def restore_vm(cntx, db, instance, restore, restored_net_resources,
               restored_security_groups, restored_compute_flavor,
               restored_nics, instance_options):    

    restore_obj = db.restore_get(cntx, restore['id'])
    snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
    test = (restore['restore_type'] == 'test')
    
    msg = 'Creating VM ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id  
    db.restore_update(cntx,  restore_obj.id, {'progress_msg': msg}) 
   
    # refresh the token so we are attempting each VM restore with a new token
    user_id = cntx.user
    project_id = cntx.tenant
    cntx = nova._get_tenant_context(user_id, project_id)

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
                'restore_type': restore['restore_type'],
                'restored_net_resources': restored_net_resources,    
                'restored_security_groups': restored_security_groups,
                'restored_compute_flavor_id': restored_compute_flavor.id,
                'restored_nics': restored_nics,
                'instance_options': instance_options,
            }

    for snapshot_vm_resource in snapshot_vm_resources:
        store[snapshot_vm_resource.id] = snapshot_vm_resource.id
        store['devname_'+snapshot_vm_resource.id] = snapshot_vm_resource.resource_name
        if snapshot_vm_resource.resource_type == 'disk':
            volume_id = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_id')
            if volume_id:
                volume_type = db.get_metadata_value(snapshot_vm_resource.metadata, 'volume_type')
                new_volume_type = get_new_volume_type(instance_options,
                                                      volume_id.lower(),
                                                      volume_type)
                store['volume_type_'+snapshot_vm_resource.id] = new_volume_type
            else:
                store['volume_type_'+snapshot_vm_resource.id] = None
       

    LOG.info(_('Processing disks'))
    _restorevmflow = lf.Flow(instance['vm_id'] + "RestoreInstance")

    childflow = LinearPrepareBackupImages(cntx, instance, instance_options, snapshot_obj, restore['id'])
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

    # attach restored volumes to restored instances
    childflow = AttachVolumes(cntx, instance, snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(AttachVolumes(cntx, instance, snapshot_obj, restore['id']))

    result = engines.run(_restorevmflow, engine_conf='serial',
                         backend={'connection': store['connection'] }, store=store)

    if result and 'restored_instance_id' in result:
        restored_instance_id = result['restored_instance_id']
        compute_service = nova.API(production = (not test))
        restored_instance = compute_service.get_server_by_id(cntx,
                                         restored_instance_id, admin=True)

        restored_vm_values = {'vm_id': restored_instance_id,
                              'vm_name':  restored_instance.name,    
                              'restore_id': restore['id'],
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
