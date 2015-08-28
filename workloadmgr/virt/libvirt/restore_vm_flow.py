import os
import uuid
from Queue import Queue
import cPickle as pickle
import json
import shutil
import math
import time
import datetime

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
               help='Ceph pool name configured for Cinder')
    ]

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

FLAGS = flags.FLAGS
CONF = cfg.CONF
CONF.register_opts(restore_vm_opts)

class PrepareBackupImage(task.Task):
    """
       Downloads objects in the backup chain and creates linked qcow2 image
    """

    def execute(self, context, restore_id, vm_resource_id):
        return self.execute_with_log(context, restore_id, vm_resource_id)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'PrepareBackupImage.execute')
    def execute_with_log(self, context, restore_id, vm_resource_id):

        db = WorkloadMgrDB().db
        cntx = amqp.RpcContext.from_dict(context)

        restore_obj = db.restore_get(cntx, restore_id)
        snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
        snapshot_vm_resource = db.snapshot_vm_resource_get(cntx, vm_resource_id)

        snapshot_vm_resource_object_store_transfer_time =\
              workload_utils.download_snapshot_vm_resource_from_object_store(cntx,
                                                                             restore_obj.id,
                                                                             restore_obj.snapshot_id,
                                                                             snapshot_vm_resource.id)

        snapshot_vm_object_store_transfer_time = snapshot_vm_resource_object_store_transfer_time
        snapshot_vm_data_transfer_time  =  snapshot_vm_resource_object_store_transfer_time
        temp_directory = os.path.join("/opt/stack/data/wlm", restore_id, vm_resource_id)
        try:
            shutil.rmtree( temp_directory )
        except OSError as exc:
            pass
        fileutils.ensure_tree(temp_directory)

        commit_queue = Queue() # queue to hold the files to be committed

        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
        disk_format = db.get_metadata_value(vm_disk_resource_snap.metadata, 'disk_format')
        disk_filename_extention = db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format')

        restored_file_path =temp_directory + '/' + vm_disk_resource_snap.id + \
                                '_' + snapshot_vm_resource.resource_name + '.' \
                                + disk_filename_extention
        restored_file_path = restored_file_path.replace(" ", "")            

        image_attr = qemuimages.qemu_img_info(vm_disk_resource_snap.vault_path)
        if disk_format == 'qcow2' and image_attr.file_format == 'raw':
            qemuimages.convert_image(vm_disk_resource_snap.vault_path, restored_file_path, 'qcow2')
        else:
            shutil.copyfile(vm_disk_resource_snap.vault_path, restored_file_path)

        while vm_disk_resource_snap.vm_disk_resource_snap_backing_id is not None:
            vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(cntx,
                                                    vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            disk_format = db.get_metadata_value(vm_disk_resource_snap_backing.metadata,'disk_format')
            snapshot_vm_resource_backing = db.snapshot_vm_resource_get(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
            restored_file_path_backing =temp_directory + '/' + vm_disk_resource_snap_backing.id + \
                                            '_' + snapshot_vm_resource_backing.resource_name + '.' \
                                            + disk_filename_extention
            restored_file_path_backing = restored_file_path_backing.replace(" ", "")
            image_attr = qemuimages.qemu_img_info(vm_disk_resource_snap_backing.vault_path)
            if disk_format == 'qcow2' and image_attr.file_format == 'raw':
                qemuimages.convert_image(vm_disk_resource_snap_backing.vault_path, restored_file_path_backing, 'qcow2')
            else:
                shutil.copyfile(vm_disk_resource_snap_backing.vault_path, restored_file_path_backing)
  
            #rebase
            image_info = qemuimages.qemu_img_info(restored_file_path)
            image_backing_info = qemuimages.qemu_img_info(restored_file_path_backing)

            #increase the size of the base image
            if image_backing_info.virtual_size < image_info.virtual_size :
                qemuimages.resize_image(restored_file_path_backing, image_info.virtual_size)  

            #rebase the image                            
            qemuimages.rebase_qcow2(restored_file_path_backing, restored_file_path)

            commit_queue.put(restored_file_path)
            vm_disk_resource_snap = vm_disk_resource_snap_backing
            restored_file_path = restored_file_path_backing

        while commit_queue.empty() is not True:
            file_to_commit = commit_queue.get_nowait()
            try:
                LOG.debug('Commiting QCOW2 ' + file_to_commit)
                qemuimages.commit_qcow2(file_to_commit)
            except Exception, ex:
                LOG.exception(ex)                       

            if restored_file_path != file_to_commit:
                utils.delete_if_exists(file_to_commit)

        image_info = qemuimages.qemu_img_info(restored_file_path)
        self.virtual_size = image_info.virtual_size
        self.restored_file_path = restored_file_path

        return (restored_file_path, image_info.virtual_size)

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
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.restore_obj = restore_obj = db.restore_get(cntx, restore_id)
        snapshot_id = restore_obj.snapshot_id
        self.image_service = image_service = glance.get_default_image_service(\
                                  production= (restore_obj['restore_type'] != 'test'))

        progressmsg = _('Uploading image and volumes of instance %(vmid)s from \
                        snapshot %(snapshot_id)s') % \
                        {'vmid': vmid, 'snapshot_id': snapshot_id}

        LOG.debug(progressmsg)

        db.restore_update(cntx,  restore_id,
                          {'progress_msg': progressmsg, 'status': 'uploading' })                  
        #upload to glance
        snapshot_vm_resource = db.snapshot_vm_resource_get(cntx, vm_resource_id)
        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
        if db.get_metadata_value(vm_disk_resource_snap.metadata, 'disk_format') == 'vmdk':
            image_metadata = {'is_public': False,
                              'status': 'active',
                              'name': snapshot_vm_resource.id,
                              'disk_format' : 'vmdk', 
                              'container_format' : 'bare',
                              'properties': {
                                  'hw_disk_bus' : 'scsi',
                                  'vmware_adaptertype' : 'lsiLogic',
                                  'vmware_disktype': 'preallocated',
                                  'image_location': 'TODO',
                                  'image_state': 'available',
                                  'owner_id': cntx.project_id}
                             }
        else:
            image_metadata = {'is_public': False,
                              'status': 'active',
                              'name': snapshot_vm_resource.id,
                              'disk_format' : 'qcow2',
                              'container_format' : 'bare',
                              'properties': {
                                  'hw_disk_bus' : 'virtio',
                                  'image_location': 'TODO',
                                  'image_state': 'available',
                                  'owner_id': cntx.project_id}
                              }

        LOG.debug('Uploading image ' + restore_file_path)
        self.restored_image = restored_image = \
                      image_service.create(cntx, image_metadata)
        if restore_obj['restore_type'] == 'test':
            shutil.move(restore_file_path, os.path.join(CONF.glance_images_path, restored_image['id']))
            restore_file_path = os.path.join(CONF.glance_images_path, restored_image['id'])
            with file(restore_file_path) as image_file:
                restored_image = image_service.update(cntx, restored_image['id'], image_metadata, image_file)
        else:
            restored_image = image_service.update(cntx, 
                                                  restored_image['id'], 
                                                  image_metadata, 
                                                  utils.ChunkedFile(restore_file_path,
                                                              {'function': db.restore_update,
                                                               'context': cntx,
                                                               'id':restore_obj.id})
                                                  )
        LOG.debug(_("restore_size: %(restore_size)s") %{'restore_size': restore_obj.size,})
        LOG.debug(_("uploaded_size: %(uploaded_size)s") %{'uploaded_size': restore_obj.uploaded_size,})
        LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': restore_obj.progress_percent,})                

        db.restore_update(cntx, restore_id, {'uploaded_size_incremental': restored_image['size']})
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
        # TODO: Delete image from the glance
        try:
            image_service.delete(self.cntx, self.imageid)
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
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.restore_obj = restore_obj = db.restore_get(cntx, restore_id)

        image_service = glance.get_default_image_service(production= (restore_obj['restore_type'] != 'test'))
        self.volume_service = volume_service = cinder.API()

        restored_image = image_service.show(cntx, imageid)

        restored_volume_name = uuid.uuid4().hex
        LOG.debug('Restoring volume from image ' + imageid)

        volume_size = int(math.ceil(image_virtual_size/(float)(1024*1024*1024)))
        self.restored_volume = restored_volume = volume_service.create(cntx, volume_size,
                                                restored_volume_name,
                                                'from workloadmgr', None,
                                                imageid, None, None, None)

        if not restored_volume:
            raise Exception("Cannot create volume from image")
                   
        #delete the image...it is not needed anymore
        #TODO(gbasava): Cinder takes a while to create the volume from image... so we need to verify the volume creation is complete.
        while True:
            time.sleep(10)
            restored_volume = volume_service.get(cntx, restored_volume['id'])
            if restored_volume['status'].lower() == 'available' or\
                restored_volume['status'].lower() == 'error':
                break

        image_service.delete(cntx, imageid)
        if restored_volume['status'].lower() == 'error':
            LOG.error(_("Volume from image %s could not successfully create") % imageid)
            raise Exception("Restoring volume failed")

        restore_obj = db.restore_update(cntx, restore_obj.id, {'uploaded_size_incremental': restored_image['size']})

        return restored_volume['id']

    @autolog.log_method(Logger, 'RestoreVolumeFromImage.revert')
    def revert_with_log(self, *args, **kwargs):
        # TODO: Delete the volume that is created
        try:
            self.volume_service.delete(self.cntx, self.restored_volume)
        except:
            pass

class RestoreCephVolume(task.Task):
    """
       Restore cinder volume from qcow2
    """

    def create_volume_from_file(self, filename, volume_name):
        args = [filename]
        args += [volume_name]
        kwargs = {'run_as_root':True}
        out, err = utils.execute('rbd', 'import', *args, **kwargs)
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
 
    def execute(self, context, restore_id, image_virtual_size,
                     restored_file_path):
        return self.execute_with_log(context, restore_id, image_virtual_size,
                      restored_file_path)

    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)

    @autolog.log_method(Logger, 'RestoreCephVolume.execute')
    def execute_with_log(self, context, restore_id, image_virtual_size,
                           restored_file_path):

        self.db = db = WorkloadMgrDB().db
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.volume_service = volume_service = cinder.API()
        restore_obj = db.restore_get(cntx, restore_id)
     
        restored_volume_name = uuid.uuid4().hex

        volume_size = int(math.ceil(image_virtual_size/(float)(1024*1024*1024)))
        self.restored_volume = restored_volume = volume_service.create(cntx, volume_size,
                                                      restored_volume_name,
                                                      'from workloadmgr', None,
                                                      None, 'ceph', None, None)

        if not restored_volume:
            raise Exception("Cannot create volume from image")

        while True:
            time.sleep(10)
            restored_volume = volume_service.get(cntx, restored_volume['id'])
            if restored_volume['status'].lower() == 'available' or\
                restored_volume['status'].lower() == 'error':
                break

        if restored_volume['status'].lower() == 'error':
            LOG.error(_("Volume from image %s could not successfully create") % imageid)
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

        restore_obj = db.restore_update(cntx, restore_obj.id,
                               {'uploaded_size_incremental': statinfo.st_size})

        return restored_volume['id']

    @autolog.log_method(Logger, 'RestoreVolumeFromImage.revert')
    def revert_with_log(self, *args, **kwargs):
        # TODO: Delete the volume that is created
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
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))

        restore_obj = db.restore_get(cntx, restore_id)
        snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)

        restored_instance_name = vmname + '_of_snapshot_' +\
                                 snapshot_obj.id + '_' + uuid.uuid4().hex[:6]
        if instance_options and 'name' in instance_options:
            restored_instance_name = instance_options['name']

        LOG.debug('Creating Instance ' + restored_instance_name) 
        
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
                     
        restored_compute_flavor = compute_service.get_flavor_by_id(cntx, restored_compute_flavor_id)

        self.volume_service = volume_service = cinder.API()

        restored_volume = volume_service.get(cntx, volumeid)
        volume_service.set_bootable(cntx, restored_volume)

        block_device_mapping = {u'vda': volumeid+":vol"}

        self.restored_instance = restored_instance = \
                     compute_service.create_server(cntx, restored_instance_name, 
                                                   None, restored_compute_flavor, 
                                                   nics=restored_nics,
                                                   block_device_mapping=block_device_mapping,
                                                   security_groups=restored_security_group_ids, 
                                                   availability_zone=availability_zone)

        if not restored_instance:
            raise Exception("Cannot create instance from image")

        while hasattr(restored_instance,'status') == False or restored_instance.status != 'ACTIVE':
            LOG.debug('Waiting for the instance ' + restored_instance.id + ' to boot' )
            time.sleep(10)
            restored_instance =  compute_service.get_server_by_id(cntx, restored_instance.id)
            if hasattr(restored_instance,'status'):
                if restored_instance.status == 'ERROR':
                    raise Exception(_("Error creating instance " + restored_instance.id))

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
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))

        restore_obj = db.restore_get(cntx, restore_id)
        snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)

        restored_instance_name = vmname + '_of_snapshot_' +\
                                 snapshot_obj.id + '_' + uuid.uuid4().hex[:6]
        if instance_options and 'name' in instance_options:
            restored_instance_name = instance_options['name']

        restored_compute_image = compute_service.get_image(cntx, imageid)
        LOG.debug('Creating Instance ' + restored_instance_name) 
        
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
                     
        restored_compute_flavor = compute_service.get_flavor_by_id(cntx, restored_compute_flavor_id)
        self.restored_instance = restored_instance = \
                     compute_service.create_server(cntx, restored_instance_name, 
                                                   restored_compute_image, restored_compute_flavor, 
                                                   nics=restored_nics,
                                                   security_groups=restored_security_group_ids, 
                                                   availability_zone=availability_zone)

        if not restored_instance:
            raise Exception("Cannot create instance from image")
        
        while hasattr(restored_instance,'status') == False or restored_instance.status != 'ACTIVE':
            LOG.debug('Waiting for the instance ' + restored_instance.id + ' to boot' )
            time.sleep(10)
            restored_instance =  compute_service.get_server_by_id(cntx, restored_instance.id)
            if hasattr(restored_instance,'status'):
                if restored_instance.status == 'ERROR':
                    raise Exception(_("Error creating instance " + restored_instance.id))

        return restored_instance['id'] 

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
        self.cntx = cntx = amqp.RpcContext.from_dict(context)
        self.compute_service = compute_service = nova.API(production = (restore_type == 'restore'))
        self.volume_service = volume_service = cinder.API()
        if restore_type == 'restore':
            self.restored_volume = restored_volume = volume_service.get(cntx, volumeid)
            while restored_volume['status'].lower() != 'available' and\
                   restored_volume['status'].lower() != 'error':
                    #TODO:(giri) need a timeout to exit
                    LOG.debug('Waiting for volume ' + restored_volume['id'] + ' to be available')
                    time.sleep(10)
                    restored_volume = volume_service.get(cntx, volumeid)
            LOG.debug('Attaching volume ' + volumeid)
            compute_service.attach_volume(cntx, restored_instance_id, volumeid, ('/dev/' + devname))
            time.sleep(15)
        else:
            params = {'path': restored_volume, 'mountpoint': '/dev/' + devname}
            compute_service.testbubble_attach_volume(cntx, restored_instance.id, params)
        pass

    @autolog.log_method(Logger, 'AttachVolume.revert')
    def revert_with_log(self, *args, **kwargs):
        try:
            self.compute_service.detach_volume(cntx, self.restored_volume)
        except:
            pass

def LinearPrepareBackupImages(context, instance, snapshotobj, restoreid):
    flow = lf.Flow("processbackupimageslf")
    db = WorkloadMgrDB().db
    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        flow.add(PrepareBackupImage("PrepareBackupImage" + snapshot_vm_resource.id,
                                    rebind=dict(vm_resource_id=snapshot_vm_resource.id),
                                    provides=('restore_file_path_' + str(snapshot_vm_resource.id),
                                              'image_virtual_size_' + str(snapshot_vm_resource.id))))
    return flow

def LinearUploadImagesToGlance(context, instance, snapshotobj, restoreid,
                               bootdisk, volumes_direct):
    flow = lf.Flow("uploadimageslf")
    db = WorkloadMgrDB().db

    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        if snapshot_vm_resource.resource_name == 'vda':
            if bootdisk == "image":
                flow.add(UploadImageToGlance("UploadImagesToGlance" + snapshot_vm_resource.id,
                                    rebind=dict( vm_resource_id=snapshot_vm_resource.id,
                                             restore_file_path='restore_file_path_'+snapshot_vm_resource.id),
                                    provides='image_id_' + str(snapshot_vm_resource.id)))
                continue

        if not volumes_direct:
            flow.add(UploadImageToGlance("UploadImagesToGlance" + snapshot_vm_resource.id,
                                    rebind=dict( vm_resource_id=snapshot_vm_resource.id,
                                             restore_file_path='restore_file_path_'+snapshot_vm_resource.id),
                                    provides='image_id_' + str(snapshot_vm_resource.id)))
    return flow

def RestoreVolumes(context, instance, snapshotobj, restoreid,
                   bootdisk, volumes_direct):
    flow = lf.Flow("restorevolumeslf")

    db = WorkloadMgrDB().db
    volume_service = cinder.API()
    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshotobj.id)

    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        if snapshot_vm_resource.resource_name == 'vda':
            fromvolume = (bootdisk == "volume")
        else:
            fromvolume =  volumes_direct

        if fromvolume:
            flow.add(RestoreCephVolume("RestoreCephVolume" + snapshot_vm_resource.id,
                                    rebind=dict(restored_file_path='restore_file_path_' +\
                                                           str(snapshot_vm_resource.id),
                                               image_virtual_size='image_virtual_size_'+\
                                                           str(snapshot_vm_resource.id)),
                                    provides='volume_id_' + str(snapshot_vm_resource.id)))
        else:
            flow.add(RestoreVolumeFromImage("RestoreVolumeFromImage" + snapshot_vm_resource.id,
                                    rebind=dict(vm_resource_id=snapshot_vm_resource.id,
                                               imageid='image_id_' + str(snapshot_vm_resource.id),
                                               image_virtual_size='image_virtual_size_'\
                                                           + str(snapshot_vm_resource.id)),
                                    provides='volume_id_' + str(snapshot_vm_resource.id)))

    return flow

def RestoreInstance(context, instance, snapshotobj, restoreid,
                    bootdisk, volumes_direct):

    flow = lf.Flow("attachvolumeslf")
    db = WorkloadMgrDB().db
    snapshot_vm_resources = db.snapshot_vm_resources_get(context,
                                         instance['vm_id'], snapshotobj.id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        if snapshot_vm_resource.resource_name == 'vda':
            if bootdisk == "volume":
                flow.add(RestoreInstanceFromVolume("RestoreInstanceFromVolume" + instance['vm_id'],
                                    rebind=dict(volumeid='volume_id_' + str(snapshot_vm_resource.id)),
                                    provides='restored_instance_id'))
            else:
                flow.add(RestoreInstanceFromImage("RestoreInstanceFromImage" + instance['vm_id'],
                                    rebind=dict(imageid='image_id_' + str(snapshot_vm_resource.id)),
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
   
    context_dict = dict([('%s' % key, value)
                          for (key, value) in cntx.to_dict().iteritems()])            
    context_dict['conf'] =  None # RpcContext object looks for this during init

    snapshot_vm_resources = db.snapshot_vm_resources_get(cntx,
                                         instance['vm_id'], snapshot_obj.id)
    # find the boot disk type
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue

        disk_type = db.get_metadata_value(snapshot_vm_resource.metadata, 'disk_type')
        if snapshot_vm_resource.resource_name == 'vda':
            if disk_type == "volume":
                bootdisk = "volume"
            else:
                bootdisk = "image"
            break

    # determine if the attached volumes are created using glance images or 
    # directly. Right now only ceph and nfs volumes are created directly.
    # for others we will fall back to glance based volume creation
    volume_service = volume_service = cinder.API()
    volume_types = volume_service.get_types(cntx)
    volumes_direct = volume_types and len(volume_types) and\
                         volume_types[0].name == 'ceph'

    # if the boot disk is volume based and volume cannot
    # be directly created then we use glance based
    # instantiation
    if bootdisk == "volume" and not volumes_direct:
        bootdisk = "image"
   
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
                'bootdisk': bootdisk,
                'volumes_direct': volumes_direct,
            }

    for snapshot_vm_resource in snapshot_vm_resources:
        store[snapshot_vm_resource.id] = snapshot_vm_resource.id
        store['devname_'+snapshot_vm_resource.id] = snapshot_vm_resource.resource_name
        #store['image_virtual_size_'+snapshot_vm_resource.id] = snapshot_vm_resource.size

    #restore, rebase, commit & upload
    LOG.info(_('Processing disks'))
    _restorevmflow = lf.Flow(instance['vm_id'] + "RestoreInstance")

    childflow = LinearPrepareBackupImages(cntx, instance, snapshot_obj, restore['id'])
    if childflow:
        _restorevmflow.add(childflow)

    # This is a linear uploading all vm images to glance
    childflow = LinearUploadImagesToGlance(cntx, instance, snapshot_obj, restore['id'],
                                                  bootdisk, volumes_direct)
    if childflow:
        _restorevmflow.add(childflow)

    # create nova/cinder objects from image ids
    childflow = RestoreVolumes(cntx, instance, snapshot_obj, restore['id'],
                                      bootdisk, volumes_direct)
    if childflow:
        _restorevmflow.add(childflow)

    # create nova from image id
    childflow = RestoreInstance(cntx, instance, snapshot_obj, restore['id'],
                                       bootdisk, volumes_direct)
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
        restored_instance = compute_service.get_server_by_id(cntx, restored_instance_id)

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
            temp_directory = os.path.join("/opt/stack/data/wlm", restore['id'], snapshot_vm_resource.id)
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
