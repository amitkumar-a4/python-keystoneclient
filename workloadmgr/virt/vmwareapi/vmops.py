# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


"""
Class for VM tasks like spawn, snapshot, suspend, resume etc.
"""

import base64
import collections
import copy
import os
import time
import urllib
import urllib2
import uuid
from Queue import Queue
import cPickle as pickle
import re
import shutil
import math

from oslo.config import cfg

#Note(Giri): importing instance_metadata from nova will cause import issues
#from nova.api.metadata import base as instance_metadata

#Note(Giri): importing compute from nova will cause import issues
#from nova import compute

#Note(Giri): importing task_states from nova will cause import issues
#from nova.compute import task_states

#Note(Giri): importing context from nova will cause import issues
#from nova import context as nova_context

#Note(Giri): importing configdrive from nova will cause import issues
#from workloadmgr.virt import configdrive

from workloadmgr.virt import power_state
from workloadmgr import exception
from workloadmgr.openstack.common import excutils
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import fileutils
from workloadmgr import utils
from workloadmgr.virt import driver
from workloadmgr.virt.vmwareapi import vif as vmwarevif
from workloadmgr.virt.vmwareapi import vim_util
from workloadmgr.virt.vmwareapi import vm_util
from workloadmgr.virt.vmwareapi import vmware_images
from workloadmgr.virt.vmwareapi import read_write_util
from workloadmgr.vault import vault
from workloadmgr import autolog
from workloadmgr.virt import qemuimages
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB




vmware_vif_opts = [
    cfg.StrOpt('integration_bridge',
               default='br-int',
               help='Name of Integration Bridge'),
    ]

vmware_group = cfg.OptGroup(name='vmware',
                            title='VMware Options')

CONF = cfg.CONF
CONF.register_group(vmware_group)
CONF.register_opts(vmware_vif_opts, vmware_group)
#Note(Giri): workloadmgr.virt.libvirt.imagecache is not available in workloadmgr
#CONF.import_opt('base_dir_name', 'workloadmgr.virt.libvirt.imagecache')
CONF.import_opt('vnc_enabled', 'nova.vnc')

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

VMWARE_POWER_STATES = {
                   'poweredOff': power_state.SHUTDOWN,
                    'poweredOn': power_state.RUNNING,
                    'suspended': power_state.SUSPENDED}
VMWARE_PREFIX = 'vmware'

VMWARE_LINKED_CLONE = 'vmware_linked_clone'

RESIZE_TOTAL_STEPS = 4

DcInfo = collections.namedtuple('DcInfo',
                                ['ref', 'name', 'vmFolder'])

class VMwareVMOps(object):
    """Management class for VM-related tasks."""

    def __init__(self, session, virtapi, volumeops, cluster=None,
                 datastore_regex=None):
        """Initializer."""
        
        #self.compute_api = compute.API()
        self._session = session
        self._virtapi = virtapi
        self._volumeops = volumeops
        self._cluster = cluster
        self._datastore_regex = datastore_regex
        #self._instance_path_base = VMWARE_PREFIX + CONF.base_dir_name
        self._instance_path_base = VMWARE_PREFIX + '_base'
        self._default_root_device = 'vda'
        self._rescue_suffix = '-rescue'
        self._poll_rescue_last_ran = None
        self._is_neutron = utils.is_neutron()
        self._datastore_dc_mapping = {}        

    def rebase_vmdk(self, base, orig_base, base_descriptor, top, orig_top, top_descriptor):
        """
        rebase the top to base
        """
        base_path, base_filename = os.path.split(base)
        orig_base_path, orig_base_filename = os.path.split(orig_base)
        base_extent_path = base_path
        base_extent_filename = base_filename + '.extent' 
        if(os.path.isfile(os.path.join(base_extent_path,base_extent_filename)) == False):
            os.rename(base, os.path.join(base_extent_path,base_extent_filename)) 
            base_descriptor = base_descriptor.replace((' "' + orig_base_filename +'"'), (' "' + base_extent_filename +'"'))
            if top_descriptor is not None:
                top_parentCID =  re.search('parentCID=(\w+)', top_descriptor).group(1)
                base_descriptor = re.sub(r'(^CID=)(\w+)', "CID=%s"%top_parentCID, base_descriptor)
            with open(base, "w") as base_descriptor_file:
                base_descriptor_file.write("%s"%base_descriptor)

        
        if top_descriptor is not None:
            top_path, top_filename = os.path.split(top)
            orig_top_path, orig_top_filename = os.path.split(orig_top)
            top_extent_path = top_path
            top_extent_filename = top_filename + '.extent'             
            if(os.path.isfile(os.path.join(top_extent_path,top_extent_filename))):
                with open(top, "r") as top_descriptor_file:
                    top_descriptor =  top_descriptor_file.read() 
            else:
                os.rename(top, os.path.join(top_extent_path,top_extent_filename))
                top_descriptor = top_descriptor.replace((' "' + orig_top_filename +'"'), (' "' + top_extent_filename +'"'))
 
            top_descriptor = re.sub(r'parentFileNameHint="([^"]*)"', "parentFileNameHint=\"%s\""%base, top_descriptor)
            with open(top, "w") as top_descriptor_file:
                top_descriptor_file.write("%s"%top_descriptor)                            
 
    def commit_vmdk(self, file_to_commit, commit_to, test):
        """rebase the backing_file_top to backing_file_base
         :param backing_file_top: top file to commit from to its base
        """
        #due to a bug in Nova VMware Driver (https://review.openstack.org/#/c/43994/) we will create a preallocated disk
        #utils.execute( 'vmware-vdiskmanager', '-r', file_to_commit, '-t 0',  commit_to, run_as_root=False)
        if test:
            utils.execute( 'env', 'LD_LIBRARY_PATH=/usr/lib/vmware-vix-disklib/lib64', 
                           'vmware-vdiskmanager', '-r', file_to_commit, '-t 2',  commit_to, run_as_root=False)
        else:
            utils.execute( 'env', 'LD_LIBRARY_PATH=/usr/lib/vmware-vix-disklib/lib64',
                           'vmware-vdiskmanager', '-r', file_to_commit, '-t 4',  commit_to, run_as_root=False)
        
        utils.chmod(commit_to, '0664')
        utils.chmod(commit_to.replace(".vmdk", "-flat.vmdk"), '0664')
        return commit_to.replace(".vmdk", "-flat.vmdk")
        """
        if test:
            utils.execute('qemu-img', 'convert', '-f', 'vmdk', '-O', 'raw', commit_to, commit_to.replace(".vmdk", ".img"), run_as_root=False)
            return commit_to.replace(".vmdk", ".img")
        else:
            return commit_to.replace(".vmdk", "-flat.vmdk") 
        """     
        
    def list_instances(self):
        """Lists the VM instances that are registered with the ESX host."""
        LOG.debug(_("Getting list of instances"))
        vms = self._session._call_method(vim_util, "get_objects",
                     "VirtualMachine",
                     ["name", "runtime.connectionState"])
        lst_vm_names = []

        while vms:
            token = vm_util._get_token(vms)
            for vm in vms.objects:
                vm_name = None
                conn_state = None
                for prop in vm.propSet:
                    if prop.name == "name":
                        vm_name = prop.val
                    elif prop.name == "runtime.connectionState":
                        conn_state = prop.val
                # Ignoring the orphaned or inaccessible VMs
                if conn_state not in ["orphaned", "inaccessible"]:
                    lst_vm_names.append(vm_name)
            if token:
                vms = self._session._call_method(vim_util,
                                                 "continue_to_get_objects",
                                                 token)
            else:
                break

        LOG.debug(_("Got total of %s instances") % str(len(lst_vm_names)))
        return lst_vm_names

    def _extend_virtual_disk(self, instance, requested_size, name,
                             datacenter):
        service_content = self._session._get_vim().get_service_content()
        LOG.debug(_("Extending root virtual disk to %s"), requested_size)
        vmdk_extend_task = self._session._call_method(
                self._session._get_vim(),
                "ExtendVirtualDisk_Task",
                service_content.virtualDiskManager,
                name=name,
                datacenter=datacenter,
                newCapacityKb=requested_size,
                eagerZero=False)
        self._session._wait_for_task(instance['uuid'],
                                     vmdk_extend_task)
        LOG.debug(_("Extended root virtual disk"))
        
    def _delete_datastore_file(self, instance, datastore_path, dc_ref):
        LOG.debug(_("Deleting the datastore file %s") % datastore_path,
                  instance=instance)
        vim = self._session._get_vim()
        file_delete_task = self._session._call_method(
                self._session._get_vim(),
                "DeleteDatastoreFile_Task",
                vim.get_service_content().fileManager,
                name=datastore_path,
                datacenter=dc_ref)
        self._session._wait_for_task(instance['uuid'],
                                     file_delete_task)
        LOG.debug(_("Deleted the datastore file"), instance=instance)
        

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info=None):
        """
        Creates a VM instance.

        Steps followed are:

        1. Create a VM with no disk and the specifics in the instance object
           like RAM size.
        2. For flat disk
          2.1. Create a dummy vmdk of the size of the disk file that is to be
               uploaded. This is required just to create the metadata file.
          2.2. Delete the -flat.vmdk file created in the above step and retain
               the metadata .vmdk file.
          2.3. Upload the disk file.
        3. For sparse disk
          3.1. Upload the disk file to a -sparse.vmdk file.
          3.2. Copy/Clone the -sparse.vmdk file to a thin vmdk.
          3.3. Delete the -sparse.vmdk file.
        4. Attach the disk to the VM by reconfiguring the same.
        5. Power on the VM.
        """
        ebs_root = False
        if block_device_info:
            LOG.debug(_("Block device information present: %s")
                      % block_device_info, instance=instance)
            block_device_mapping = driver.block_device_info_get_mapping(
                    block_device_info)
            if block_device_mapping:
                ebs_root = True

        client_factory = self._session._get_vim().client.factory
        service_content = self._session._get_vim().get_service_content()
        ds = vm_util.get_datastore_ref_and_name(self._session, self._cluster,
                 datastore_regex=self._datastore_regex)
        data_store_ref = ds[0]
        data_store_name = ds[1]

        #TODO(hartsocks): this pattern is confusing, reimplement as methods
        # The use of nested functions in this file makes for a confusing and
        # hard to maintain file. At some future date, refactor this method to
        # be a full-fledged method. This will also make unit testing easier.
        def _get_image_properties(root_size):
            """
            Get the Size of the flat vmdk file that is there on the storage
            repository.
            """
            image_ref = instance.get('image_ref')
            if image_ref:
                _image_info = vmware_images.get_vmdk_size_and_properties(
                        context, image_ref, instance)
            else:
                # The case that the image may be booted from a volume
                _image_info = (root_size, {})

            image_size, image_properties = _image_info
            vmdk_file_size_in_kb = int(image_size) / 1024
            os_type = image_properties.get("vmware_ostype", "otherGuest")
            adapter_type = image_properties.get("vmware_adaptertype",
                                                "lsiLogic")
            disk_type = image_properties.get("vmware_disktype",
                                             "preallocated")
            # Get the network card type from the image properties.
            vif_model = image_properties.get("hw_vif_model", "VirtualE1000")

            # Fetch the image_linked_clone data here. It is retrieved
            # with the above network based API call. To retrieve it
            # later will necessitate additional network calls using the
            # identical method. Consider this a cache.
            image_linked_clone = image_properties.get(VMWARE_LINKED_CLONE)

            return (vmdk_file_size_in_kb, os_type, adapter_type, disk_type,
                vif_model, image_linked_clone)

        root_gb = instance['root_gb']
        root_gb_in_kb = root_gb * 1024 * 1024

        (vmdk_file_size_in_kb, os_type, adapter_type, disk_type, vif_model,
            image_linked_clone) = _get_image_properties(root_gb_in_kb)

        if root_gb_in_kb and vmdk_file_size_in_kb > root_gb_in_kb:
            reason = _("Image disk size greater than requested disk size")
            raise exception.InstanceUnacceptable(instance_id=instance['uuid'],
                                                 reason=reason)

        vm_folder_ref = self._get_vmfolder_ref()
        node_mo_id = vm_util.get_mo_id_from_instance(instance)
        res_pool_ref = vm_util.get_res_pool_ref(self._session,
                                                self._cluster, node_mo_id)

        def _get_vif_infos():
            vif_infos = []
            if network_info is None:
                return vif_infos
            for vif in network_info:
                mac_address = vif['address']
                network_name = vif['network']['bridge'] or \
                               CONF.vmware.integration_bridge
                network_ref = vmwarevif.get_network_ref(self._session,
                                                        self._cluster,
                                                        vif,
                                                        self._is_neutron)
                vif_infos.append({'network_name': network_name,
                                  'mac_address': mac_address,
                                  'network_ref': network_ref,
                                  'iface_id': vif['id'],
                                  'vif_model': vif_model
                                 })
            return vif_infos

        vif_infos = _get_vif_infos()

        # Get the create vm config spec
        config_spec = vm_util.get_vm_create_spec(
                            client_factory, instance,
                            data_store_name, vif_infos, os_type)

        def _execute_create_vm():
            """Create VM on ESX host."""
            LOG.debug(_("Creating VM on the ESX host"), instance=instance)
            # Create the VM on the ESX host
            vm_create_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "CreateVM_Task", vm_folder_ref,
                                    config=config_spec, pool=res_pool_ref)
            self._session._wait_for_task(instance['uuid'], vm_create_task)

            LOG.debug(_("Created VM on the ESX host"), instance=instance)

        _execute_create_vm()
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        # Set the machine.id parameter of the instance to inject
        # the NIC configuration inside the VM
        if CONF.flat_injected:
            self._set_machine_id(client_factory, instance, network_info)

        # Set the vnc configuration of the instance, vnc port starts from 5900
        if CONF.vnc_enabled:
            vnc_port = self._get_vnc_port(vm_ref)
            vnc_pass = CONF.vmware.vnc_password or ''
            self._set_vnc_config(client_factory, instance, vnc_port, vnc_pass)

        def _create_virtual_disk():
            """Create a virtual disk of the size of flat vmdk file."""
            # Create a Virtual Disk of the size of the flat vmdk file. This is
            # done just to generate the meta-data file whose specifics
            # depend on the size of the disk, thin/thick provisioning and the
            # storage adapter type.
            # Here we assume thick provisioning and lsiLogic for the adapter
            # type
            LOG.debug(_("Creating Virtual Disk of size  "
                      "%(vmdk_file_size_in_kb)s KB and adapter type "
                      "%(adapter_type)s on the ESX host local store "
                      "%(data_store_name)s") %
                       {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                        "adapter_type": adapter_type,
                        "data_store_name": data_store_name},
                      instance=instance)
            vmdk_create_spec = vm_util.get_vmdk_create_spec(client_factory,
                                    vmdk_file_size_in_kb, adapter_type,
                                    disk_type)
            vmdk_create_task = self._session._call_method(
                self._session._get_vim(),
                "CreateVirtualDisk_Task",
                service_content.virtualDiskManager,
                name=uploaded_vmdk_path,
                datacenter=dc_ref,
                spec=vmdk_create_spec)
            self._session._wait_for_task(instance['uuid'], vmdk_create_task)
            LOG.debug(_("Created Virtual Disk of size %(vmdk_file_size_in_kb)s"
                        " KB and type %(disk_type)s on "
                        "the ESX host local store %(data_store_name)s") %
                        {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                         "disk_type": disk_type,
                         "data_store_name": data_store_name},
                      instance=instance)

        def _delete_disk_file(vmdk_path):
            LOG.debug(_("Deleting the file %(vmdk_path)s "
                        "on the ESX host local"
                        "store %(data_store_name)s") %
                        {"vmdk_path": vmdk_path,
                         "data_store_name": data_store_name},
                      instance=instance)
            # Delete the vmdk file.
            vmdk_delete_task = self._session._call_method(
                        self._session._get_vim(),
                        "DeleteDatastoreFile_Task",
                        service_content.fileManager,
                        name=vmdk_path,
                        datacenter=dc_ref)
            self._session._wait_for_task(instance['uuid'], vmdk_delete_task)
            LOG.debug(_("Deleted the file %(vmdk_path)s on the "
                        "ESX host local store %(data_store_name)s") %
                        {"vmdk_path": vmdk_path,
                         "data_store_name": data_store_name},
                      instance=instance)

        def _fetch_image_on_esx_datastore():
            """Fetch image from Glance to ESX datastore."""
            LOG.debug(_("Downloading image file data %(image_ref)s to the ESX "
                        "data store %(data_store_name)s") %
                        {'image_ref': instance['image_ref'],
                         'data_store_name': data_store_name},
                      instance=instance)
            # For flat disk, upload the -flat.vmdk file whose meta-data file
            # we just created above
            # For sparse disk, upload the -sparse.vmdk file to be copied into
            # a flat vmdk
            upload_vmdk_name = sparse_uploaded_vmdk_name \
                if disk_type == "sparse" else flat_uploaded_vmdk_name
            vmware_images.fetch_image(
                context,
                instance['image_ref'],
                instance,
                host=self._session._host_ip,
                data_center_name=self._get_datacenter_ref_and_name()[1],
                datastore_name=data_store_name,
                cookies=cookies,
                file_path=upload_vmdk_name)
            LOG.debug(_("Downloaded image file data %(image_ref)s to "
                        "%(upload_vmdk_name)s on the ESX data store "
                        "%(data_store_name)s") %
                        {'image_ref': instance['image_ref'],
                         'upload_vmdk_name': upload_vmdk_name,
                         'data_store_name': data_store_name},
                      instance=instance)

        def _copy_virtual_disk(source, dest):
            #Note(Giri): configdrive is not available. return 
            return
            """Copy a sparse virtual disk to a thin virtual disk."""
            # Copy a sparse virtual disk to a thin virtual disk. This is also
            # done to generate the meta-data file whose specifics
            # depend on the size of the disk, thin/thick provisioning and the
            # storage adapter type.
            LOG.debug(_("Copying Virtual Disk of size "
                      "%(vmdk_file_size_in_kb)s KB and adapter type "
                      "%(adapter_type)s on the ESX host local store "
                      "%(data_store_name)s to disk type %(disk_type)s") %
                       {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                        "adapter_type": adapter_type,
                        "data_store_name": data_store_name,
                        "disk_type": disk_type},
                      instance=instance)
            vmdk_copy_spec = self.get_copy_virtual_disk_spec(client_factory,
                                                             adapter_type,
                                                             disk_type)
            vmdk_copy_task = self._session._call_method(
                self._session._get_vim(),
                "CopyVirtualDisk_Task",
                service_content.virtualDiskManager,
                sourceName=source,
                sourceDatacenter=self._get_datacenter_ref_and_name()[0],
                destName=dest,
                destSpec=vmdk_copy_spec)
            self._session._wait_for_task(instance['uuid'], vmdk_copy_task)
            LOG.debug(_("Copied Virtual Disk of size %(vmdk_file_size_in_kb)s"
                        " KB and type %(disk_type)s on "
                        "the ESX host local store %(data_store_name)s") %
                        {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                         "disk_type": disk_type,
                         "data_store_name": data_store_name},
                        instance=instance)

        if not ebs_root:
            # this logic allows for instances or images to decide
            # for themselves which strategy is best for them.

            linked_clone = VMwareVMOps.decide_linked_clone(
                image_linked_clone,
                CONF.vmware.use_linked_clone
            )
            upload_folder = self._instance_path_base
            upload_name = instance['image_ref']

            # The vmdk meta-data file
            uploaded_vmdk_name = "%s/%s.vmdk" % (upload_folder, upload_name)
            uploaded_vmdk_path = vm_util.build_datastore_path(data_store_name,
                                                uploaded_vmdk_name)

            session_vim = self._session._get_vim()
            cookies = session_vim.client.options.transport.cookiejar

            if not (self._check_if_folder_file_exists(
                                        data_store_ref, data_store_name,
                                        upload_folder, upload_name + ".vmdk")):

                # Naming the VM files in correspondence with the VM instance
                # The flat vmdk file name
                flat_uploaded_vmdk_name = "%s/%s-flat.vmdk" % (
                                            upload_folder, upload_name)
                # The sparse vmdk file name for sparse disk image
                sparse_uploaded_vmdk_name = "%s/%s-sparse.vmdk" % (
                                            upload_folder, upload_name)

                flat_uploaded_vmdk_path = vm_util.build_datastore_path(
                                                    data_store_name,
                                                    flat_uploaded_vmdk_name)
                sparse_uploaded_vmdk_path = vm_util.build_datastore_path(
                                                    data_store_name,
                                                    sparse_uploaded_vmdk_name)
                dc_ref = self._get_datacenter_ref_and_name()[0]

                if disk_type != "sparse":
                   # Create a flat virtual disk and retain the metadata file.
                    _create_virtual_disk()
                    _delete_disk_file(flat_uploaded_vmdk_path)

                _fetch_image_on_esx_datastore()

                if disk_type == "sparse":
                    # Copy the sparse virtual disk to a thin virtual disk.
                    disk_type = "thin"
                    _copy_virtual_disk(sparse_uploaded_vmdk_path,
                                       uploaded_vmdk_path)
                    _delete_disk_file(sparse_uploaded_vmdk_path)
            else:
                # linked clone base disk exists
                if disk_type == "sparse":
                    disk_type = "thin"

            # Extend the disk size if necessary
            if not linked_clone:
                # If we are not using linked_clone, copy the image from
                # the cache into the instance directory.  If we are using
                # linked clone it is references from the cache directory
                dest_folder = instance['uuid']
                dest_name = instance['name']
                dest_vmdk_name = "%s/%s.vmdk" % (dest_folder,
                                                         dest_name)
                dest_vmdk_path = vm_util.build_datastore_path(
                    data_store_name, dest_vmdk_name)
                _copy_virtual_disk(uploaded_vmdk_path, dest_vmdk_path)

                root_vmdk_path = dest_vmdk_path
                if root_gb_in_kb > vmdk_file_size_in_kb:
                    self._extend_virtual_disk(instance, root_gb_in_kb,
                                              root_vmdk_path, dc_ref)
            else:
                root_vmdk_name = "%s/%s.%s.vmdk" % (upload_folder, upload_name,
                                                    root_gb)
                root_vmdk_path = vm_util.build_datastore_path(data_store_name,
                                                              root_vmdk_name)
                if not self._check_if_folder_file_exists(
                                        data_store_ref, data_store_name,
                                        upload_folder,
                                        upload_name + ".%s.vmdk" % root_gb):
                    dc_ref = self._get_datacenter_ref_and_name()[0]
                    LOG.debug(_("Copying root disk of size %sGb"), root_gb)
                    copy_spec = self.get_copy_virtual_disk_spec(
                            client_factory, adapter_type, disk_type)
                    vmdk_copy_task = self._session._call_method(
                        self._session._get_vim(),
                        "CopyVirtualDisk_Task",
                        service_content.virtualDiskManager,
                        sourceName=uploaded_vmdk_path,
                        sourceDatacenter=dc_ref,
                        destName=root_vmdk_path,
                        destSpec=copy_spec)
                    self._session._wait_for_task(instance['uuid'],
                                                 vmdk_copy_task)
                    if root_gb_in_kb > vmdk_file_size_in_kb:
                        self._extend_virtual_disk(instance, root_gb_in_kb,
                                                  root_vmdk_path, dc_ref)

            # Attach the root disk to the VM.
            self._volumeops.attach_disk_to_vm(
                                vm_ref, instance,
                                adapter_type, disk_type, root_vmdk_path,
                                root_gb_in_kb, linked_clone)

            if configdrive.required_by(instance):
                uploaded_iso_path = self._create_config_drive(instance,
                                                              injected_files,
                                                              admin_password,
                                                              data_store_name,
                                                              instance['uuid'],
                                                              cookies)
                uploaded_iso_path = vm_util.build_datastore_path(
                    data_store_name,
                    uploaded_iso_path)
                self._attach_cdrom_to_vm(
                    vm_ref, instance,
                    data_store_ref,
                    uploaded_iso_path,
                    1 if adapter_type in ['ide'] else 0)

        else:
            # Attach the root disk to the VM.
            for root_disk in block_device_mapping:
                connection_info = root_disk['connection_info']
                self._volumeops.attach_root_volume(connection_info, instance,
                                                   self._default_root_device,
                                                   data_store_ref)

        def _power_on_vm():
            """Power on the VM."""
            LOG.debug(_("Powering on the VM instance"), instance=instance)
            # Power On the VM
            power_on_task = self._session._call_method(
                               self._session._get_vim(),
                               "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], power_on_task)
            LOG.debug(_("Powered on the VM instance"), instance=instance)
        _power_on_vm()

    def _create_config_drive(self, instance, injected_files, admin_password,
                             data_store_name, upload_folder, cookies):
        #Note(Giri): instance_metadata and configdrive are not available. return 
        return
        if CONF.config_drive_format != 'iso9660':
            reason = (_('Invalid config_drive_format "%s"') %
                      CONF.config_drive_format)
            raise exception.InstancePowerOnFailure(reason=reason)

        LOG.info(_('Using config drive for instance'), instance=instance)
        extra_md = {}
        if admin_password:
            extra_md['admin_pass'] = admin_password

        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md)
        try:
            with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
                with utils.tempdir() as tmp_path:
                    tmp_file = os.path.join(tmp_path, 'configdrive.iso')
                    cdb.make_drive(tmp_file)
                    dc_name = self._get_datacenter_ref_and_name()[1]

                    upload_iso_path = "%s/configdrive.iso" % (
                        upload_folder)
                    vmware_images.upload_iso_to_datastore(
                        tmp_file, instance,
                        host=self._session._host_ip,
                        data_center_name=dc_name,
                        datastore_name=data_store_name,
                        cookies=cookies,
                        file_path=upload_iso_path)
                    return upload_iso_path
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Creating config drive failed with error: %s'),
                          e, instance=instance)

    def _attach_cdrom_to_vm(self, vm_ref, instance,
                         datastore, file_path,
                         cdrom_unit_number):
        """Attach cdrom to VM by reconfiguration."""
        instance_name = instance['name']
        instance_uuid = instance['uuid']
        client_factory = self._session._get_vim().client.factory
        vmdk_attach_config_spec = vm_util.get_cdrom_attach_config_spec(
                                    client_factory, datastore, file_path,
                                    cdrom_unit_number)

        LOG.debug(_("Reconfiguring VM instance %(instance_name)s to attach "
                    "cdrom %(file_path)s"),
                  {'instance_name': instance_name, 'file_path': file_path})
        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=vmdk_attach_config_spec)
        self._session._wait_for_task(instance_uuid, reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(instance_name)s to attach "
                    "cdrom %(file_path)s"),
                  {'instance_name': instance_name, 'file_path': file_path})

    @staticmethod
    def decide_linked_clone(image_linked_clone, global_linked_clone):
        """Explicit decision logic: whether to use linked clone on a vmdk.

        This is *override* logic not boolean logic.

        1. let the image over-ride if set at all
        2. default to the global setting

        In math terms, I need to allow:
        glance image to override global config.

        That is g vs c. "g" for glance. "c" for Config.

        So, I need  g=True vs c=False to be True.
        And, I need g=False vs c=True to be False.
        And, I need g=None vs c=True to be True.

        Some images maybe independently best tuned for use_linked_clone=True
        saving datastorage space. Alternatively a whole OpenStack install may
        be tuned to performance use_linked_clone=False but a single image
        in this environment may be best configured to save storage space and
        set use_linked_clone=True only for itself.

        The point is: let each layer of control override the layer beneath it.

        rationale:
        For technical discussion on the clone strategies and their trade-offs
        see: https://www.vmware.com/support/ws5/doc/ws_clone_typeofclone.html

        :param image_linked_clone: boolean or string or None
        :param global_linked_clone: boolean or string or None
        :return: Boolean
        """

        value = None

        # Consider the values in order of override.
        if image_linked_clone is not None:
            value = image_linked_clone
        else:
            # this will never be not-set by this point.
            value = global_linked_clone

        return utils.get_boolean(value)

    def get_copy_virtual_disk_spec(self, client_factory, adapter_type,
                                   disk_type):
        return vm_util.get_copy_virtual_disk_spec(client_factory,
                                                  adapter_type,
                                                  disk_type)

    def _get_values_from_object_properties(self, props, query):
        while props:
            token = vm_util._get_token(props)
            for elem in props.objects:
                for prop in elem.propSet:
                    for key in query.keys():
                        if prop.name == key:
                            query[key] = prop.val
                            break
            if token:
                props = self._session._call_method(vim_util,
                                                   "continue_to_get_objects",
                                                   token)
            else:
                break

    def reboot(self, instance, network_info):
        """Reboot a VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        self.plug_vifs(instance, network_info)

        lst_properties = ["summary.guest.toolsStatus", "runtime.powerState",
                          "summary.guest.toolsRunningStatus"]
        props = self._session._call_method(vim_util, "get_object_properties",
                           None, vm_ref, "VirtualMachine",
                           lst_properties)
        query = {'runtime.powerState': None,
                 'summary.guest.toolsStatus': None,
                 'summary.guest.toolsRunningStatus': False}
        self._get_values_from_object_properties(props, query)
        pwr_state = query['runtime.powerState']
        tools_status = query['summary.guest.toolsStatus']
        tools_running_status = query['summary.guest.toolsRunningStatus']

        # Raise an exception if the VM is not powered On.
        if pwr_state not in ["poweredOn"]:
            reason = _("instance is not powered on")
            raise exception.InstanceRebootFailure(reason=reason)

        # If latest vmware tools are installed in the VM, and that the tools
        # are running, then only do a guest reboot. Otherwise do a hard reset.
        if (tools_status == "toolsOk" and
                tools_running_status == "guestToolsRunning"):
            LOG.debug(_("Rebooting guest OS of VM"), instance=instance)
            self._session._call_method(self._session._get_vim(), "RebootGuest",
                                       vm_ref)
            LOG.debug(_("Rebooted guest OS of VM"), instance=instance)
        else:
            LOG.debug(_("Doing hard reboot of VM"), instance=instance)
            reset_task = self._session._call_method(self._session._get_vim(),
                                                    "ResetVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], reset_task)
            LOG.debug(_("Did hard reboot of VM"), instance=instance)

    def _delete(self, instance, network_info):
        """
        Destroy a VM instance. Steps followed are:
        1. Power off the VM, if it is in poweredOn state.
        2. Destroy the VM.
        """
        try:
            vm_ref = vm_util.get_vm_ref(self._session, instance)
            self.power_off(instance)
            try:
                LOG.debug(_("Destroying the VM"), instance=instance)
                destroy_task = self._session._call_method(
                    self._session._get_vim(),
                    "Destroy_Task", vm_ref)
                self._session._wait_for_task(instance['uuid'], destroy_task)
                LOG.debug(_("Destroyed the VM"), instance=instance)
            except Exception as excep:
                LOG.warn(_("In vmwareapi:vmops:delete, got this exception"
                           " while destroying the VM: %s") % str(excep))

            if network_info:
                self.unplug_vifs(instance, network_info)
        except Exception as exc:
            LOG.exception(exc, instance=instance)

    def destroy(self, instance, network_info, destroy_disks=True):
        """
        Destroy a VM instance. Steps followed are:
        1. Power off the VM, if it is in poweredOn state.
        2. Un-register a VM.
        3. Delete the contents of the folder holding the VM related data.
        """
        try:
            vm_ref = vm_util.get_vm_ref(self._session, instance)
            lst_properties = ["config.files.vmPathName", "runtime.powerState"]
            props = self._session._call_method(vim_util,
                        "get_object_properties",
                        None, vm_ref, "VirtualMachine", lst_properties)
            query = {'runtime.powerState': None,
                     'config.files.vmPathName': None}
            self._get_values_from_object_properties(props, query)
            pwr_state = query['runtime.powerState']
            vm_config_pathname = query['config.files.vmPathName']
            if vm_config_pathname:
                _ds_path = vm_util.split_datastore_path(vm_config_pathname)
                datastore_name, vmx_file_path = _ds_path
            # Power off the VM if it is in PoweredOn state.
            if pwr_state == "poweredOn":
                LOG.debug(_("Powering off the VM"), instance=instance)
                poweroff_task = self._session._call_method(
                       self._session._get_vim(),
                       "PowerOffVM_Task", vm_ref)
                self._session._wait_for_task(instance['uuid'], poweroff_task)
                LOG.debug(_("Powered off the VM"), instance=instance)

            # Un-register the VM
            try:
                LOG.debug(_("Unregistering the VM"), instance=instance)
                self._session._call_method(self._session._get_vim(),
                                           "UnregisterVM", vm_ref)
                LOG.debug(_("Unregistered the VM"), instance=instance)
            except Exception as excep:
                LOG.warn(_("In vmwareapi:vmops:destroy, got this exception"
                           " while un-registering the VM: %s") % str(excep))

            if network_info:
                self.unplug_vifs(instance, network_info)

            # Delete the folder holding the VM related content on
            # the datastore.
            if destroy_disks:
                try:
                    dir_ds_compliant_path = vm_util.build_datastore_path(
                                     datastore_name,
                                     os.path.dirname(vmx_file_path))
                    LOG.debug(_("Deleting contents of the VM from "
                                "datastore %(datastore_name)s") %
                               {'datastore_name': datastore_name},
                              instance=instance)
                    vim = self._session._get_vim()
                    delete_task = self._session._call_method(
                        vim,
                        "DeleteDatastoreFile_Task",
                        vim.get_service_content().fileManager,
                        name=dir_ds_compliant_path,
                        datacenter=self._get_datacenter_ref_and_name()[0])
                    self._session._wait_for_task(instance['uuid'], delete_task)
                    LOG.debug(_("Deleted contents of the VM from "
                                "datastore %(datastore_name)s") %
                               {'datastore_name': datastore_name},
                              instance=instance)
                except Exception as excep:
                    LOG.warn(_("In vmwareapi:vmops:destroy, "
                                 "got this exception while deleting"
                                 " the VM contents from the disk: %s")
                                 % str(excep))
        except Exception as exc:
            LOG.exception(exc, instance=instance)

    def pause(self, instance):
        msg = _("pause not supported for vmwareapi")
        raise NotImplementedError(msg)

    def unpause(self, instance):
        msg = _("unpause not supported for vmwareapi")
        raise NotImplementedError(msg)

    def suspend(self, instance):
        """Suspend the specified instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        pwr_state = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "runtime.powerState")
        # Only PoweredOn VMs can be suspended.
        if pwr_state == "poweredOn":
            LOG.debug(_("Suspending the VM"), instance=instance)
            suspend_task = self._session._call_method(self._session._get_vim(),
                    "SuspendVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], suspend_task)
            LOG.debug(_("Suspended the VM"), instance=instance)
        # Raise Exception if VM is poweredOff
        elif pwr_state == "poweredOff":
            reason = _("instance is powered off and cannot be suspended.")
            raise exception.InstanceSuspendFailure(reason=reason)
        else:
            LOG.debug(_("VM was already in suspended state. So returning "
                      "without doing anything"), instance=instance)

    def resume(self, instance):
        """Resume the specified instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        pwr_state = self._session._call_method(vim_util,
                                     "get_dynamic_property", vm_ref,
                                     "VirtualMachine", "runtime.powerState")
        if pwr_state.lower() == "suspended":
            LOG.debug(_("Resuming the VM"), instance=instance)
            suspend_task = self._session._call_method(
                                        self._session._get_vim(),
                                       "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], suspend_task)
            LOG.debug(_("Resumed the VM"), instance=instance)
        else:
            reason = _("instance is not in a suspended state")
            raise exception.InstanceResumeFailure(reason=reason)

    def rescue(self, context, instance, network_info, image_meta):
        """Rescue the specified instance.

            - shutdown the instance VM.
            - spawn a rescue VM (the vm name-label will be instance-N-rescue).

        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        self.power_off(instance)
        r_instance = copy.deepcopy(instance)
        r_instance['name'] = r_instance['name'] + self._rescue_suffix
        r_instance['uuid'] = r_instance['uuid'] + self._rescue_suffix
        self.spawn(context, r_instance, image_meta,
                   None, None, network_info)

        # Attach vmdk to the rescue VM
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")
        vmdk_path, controller_key, adapter_type, disk_type, unit_number \
            = vm_util.get_vmdk_path_and_adapter_type(hardware_devices)
        # Figure out the correct unit number
        unit_number = unit_number + 1
        rescue_vm_ref = vm_util.get_vm_ref_from_uuid(self._session,
                                                     r_instance['uuid'])
        if rescue_vm_ref is None:
            rescue_vm_ref = vm_util.get_vm_ref_from_name(self._session,
                                                     r_instance['name'])
        self._volumeops.attach_disk_to_vm(
                                rescue_vm_ref, r_instance,
                                adapter_type, disk_type, vmdk_path,
                                controller_key=controller_key,
                                unit_number=unit_number)

    def unrescue(self, instance):
        """Unrescue the specified instance."""
        r_instance = copy.deepcopy(instance)
        r_instance['name'] = r_instance['name'] + self._rescue_suffix
        r_instance['uuid'] = r_instance['uuid'] + self._rescue_suffix
        self.destroy(r_instance, None)
        self._power_on(instance)

    def power_off(self, instance):
        """Power off the specified instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        pwr_state = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "runtime.powerState")
        # Only PoweredOn VMs can be powered off.
        if pwr_state == "poweredOn":
            LOG.debug(_("Powering off the VM"), instance=instance)
            poweroff_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "PowerOffVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], poweroff_task)
            LOG.debug(_("Powered off the VM"), instance=instance)
        # Raise Exception if VM is suspended
        elif pwr_state == "suspended":
            reason = _("instance is suspended and cannot be powered off.")
            raise exception.InstancePowerOffFailure(reason=reason)
        else:
            LOG.debug(_("VM was already in powered off state. So returning "
                        "without doing anything"), instance=instance)

    def _power_on(self, instance):
        """Power on the specified instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        pwr_state = self._session._call_method(vim_util,
                                     "get_dynamic_property", vm_ref,
                                     "VirtualMachine", "runtime.powerState")
        if pwr_state == "poweredOn":
            LOG.debug(_("VM was already in powered on state. So returning "
                      "without doing anything"), instance=instance)
        # Only PoweredOff and Suspended VMs can be powered on.
        else:
            LOG.debug(_("Powering on the VM"), instance=instance)
            poweron_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], poweron_task)
            LOG.debug(_("Powered on the VM"), instance=instance)

    def power_on(self, context, instance, network_info, block_device_info):
        self._power_on(instance)

    def _get_orig_vm_name_label(self, instance):
        return instance['name'] + '-orig'

    def _update_instance_progress(self, context, instance, step, total_steps):
        """Update instance progress percent to reflect current step number
        """
        # Divide the action's workflow into discrete steps and "bump" the
        # instance's progress field as each step is completed.
        #
        # For a first cut this should be fine, however, for large VM images,
        # the clone disk step begins to dominate the equation. A
        # better approximation would use the percentage of the VM image that
        # has been streamed to the destination host.
        progress = round(float(step) / total_steps * 100)
        instance_uuid = instance['uuid']
        LOG.debug(_("Updating instance '%(instance_uuid)s' progress to"
                    " %(progress)d"),
                  {'instance_uuid': instance_uuid, 'progress': progress},
                  instance=instance)
        self._virtapi.instance_update(context, instance_uuid,
                                      {'progress': progress})

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type):
        """
        Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.
        """
        # 0. Zero out the progress to begin
        self._update_instance_progress(context, instance,
                                       step=0,
                                       total_steps=RESIZE_TOTAL_STEPS)

        vm_ref = vm_util.get_vm_ref(self._session, instance)
        host_ref = self._get_host_ref_from_name(dest)
        if host_ref is None:
            raise exception.HostNotFound(host=dest)

        # 1. Power off the instance
        self.power_off(instance)
        self._update_instance_progress(context, instance,
                                       step=1,
                                       total_steps=RESIZE_TOTAL_STEPS)

        # 2. Rename the original VM with suffix '-orig'
        name_label = self._get_orig_vm_name_label(instance)
        LOG.debug(_("Renaming the VM to %s") % name_label,
                  instance=instance)
        rename_task = self._session._call_method(
                            self._session._get_vim(),
                            "Rename_Task", vm_ref, newName=name_label)
        self._session._wait_for_task(instance['uuid'], rename_task)
        LOG.debug(_("Renamed the VM to %s") % name_label,
                  instance=instance)
        self._update_instance_progress(context, instance,
                                       step=2,
                                       total_steps=RESIZE_TOTAL_STEPS)

        # Get the clone vm spec
        ds_ref = vm_util.get_datastore_ref_and_name(
                            self._session, None, dest)[0]
        client_factory = self._session._get_vim().client.factory
        rel_spec = vm_util.relocate_vm_spec(client_factory, ds_ref, host_ref)
        clone_spec = vm_util.clone_vm_spec(client_factory, rel_spec)
        vm_folder_ref = self._get_vmfolder_ref()

        # 3. Clone VM on ESX host
        LOG.debug(_("Cloning VM to host %s") % dest, instance=instance)
        vm_clone_task = self._session._call_method(
                                self._session._get_vim(),
                                "CloneVM_Task", vm_ref,
                                folder=vm_folder_ref,
                                name=instance['name'],
                                spec=clone_spec)
        self._session._wait_for_task(instance['uuid'], vm_clone_task)
        LOG.debug(_("Cloned VM to host %s") % dest, instance=instance)
        self._update_instance_progress(context, instance,
                                       step=3,
                                       total_steps=RESIZE_TOTAL_STEPS)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        instance_name = self._get_orig_vm_name_label(instance)
        # Destroy the original VM.
        vm_ref = vm_util.get_vm_ref_from_uuid(self._session, instance['uuid'])
        if vm_ref is None:
            vm_ref = vm_util.get_vm_ref_from_name(self._session, instance_name)
        if vm_ref is None:
            LOG.debug(_("instance not present"), instance=instance)
            return

        try:
            LOG.debug(_("Destroying the VM"), instance=instance)
            destroy_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "Destroy_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], destroy_task)
            LOG.debug(_("Destroyed the VM"), instance=instance)
        except Exception as excep:
            LOG.warn(_("In vmwareapi:vmops:confirm_migration, got this "
                     "exception while destroying the VM: %s") % str(excep))

        if network_info:
            self.unplug_vifs(instance, network_info)

    def finish_revert_migration(self, instance, network_info,
                                block_device_info, power_on=True):
        """Finish reverting a resize."""
        # The original vm was suffixed with '-orig'; find it using
        # the old suffix, remove the suffix, then power it back on.
        name_label = self._get_orig_vm_name_label(instance)
        vm_ref = vm_util.get_vm_ref_from_name(self._session, name_label)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=name_label)

        LOG.debug(_("Renaming the VM from %s") % name_label,
                  instance=instance)
        rename_task = self._session._call_method(
                            self._session._get_vim(),
                            "Rename_Task", vm_ref, newName=instance['uuid'])
        self._session._wait_for_task(instance['uuid'], rename_task)
        LOG.debug(_("Renamed the VM from %s") % name_label,
                  instance=instance)
        if power_on:
            self._power_on(instance)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        """Completes a resize, turning on the migrated instance."""
        # 4. Start VM
        if power_on:
            self._power_on(instance)
        self._update_instance_progress(context, instance,
                                       step=4,
                                       total_steps=RESIZE_TOTAL_STEPS)

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False):
        """Spawning live_migration operation for distributing high-load."""
        vm_ref = vm_util.get_vm_ref(self._session, instance_ref)

        host_ref = self._get_host_ref_from_name(dest)
        if host_ref is None:
            raise exception.HostNotFound(host=dest)

        LOG.debug(_("Migrating VM to host %s") % dest, instance=instance_ref)
        try:
            vm_migrate_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "MigrateVM_Task", vm_ref,
                                    host=host_ref,
                                    priority="defaultPriority")
            self._session._wait_for_task(instance_ref['uuid'], vm_migrate_task)
        except Exception:
            with excutils.save_and_reraise_exception():
                recover_method(context, instance_ref, dest, block_migration)
        post_method(context, instance_ref, dest, block_migration)
        LOG.debug(_("Migrated VM to host %s") % dest, instance=instance_ref)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        #Note(Giri): nova_context and compute_api are not available. return 
        return
        ctxt = nova_context.get_admin_context()

        instances_info = dict(instance_count=len(instances),
                timeout=timeout)

        if instances_info["instance_count"] > 0:
            LOG.info(_("Found %(instance_count)d hung reboots "
                    "older than %(timeout)d seconds") % instances_info)

        for instance in instances:
            LOG.info(_("Automatically hard rebooting"), instance=instance)
            self.compute_api.reboot(ctxt, instance, "HARD")

    def get_info(self, instance):
        """Return data about the VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        lst_properties = ["summary.config.numCpu",
                    "summary.config.memorySizeMB",
                    "runtime.powerState"]
        vm_props = self._session._call_method(vim_util,
                    "get_object_properties", None, vm_ref, "VirtualMachine",
                    lst_properties)
        query = {'summary.config.numCpu': None,
                 'summary.config.memorySizeMB': None,
                 'runtime.powerState': None}
        self._get_values_from_object_properties(vm_props, query)
        max_mem = int(query['summary.config.memorySizeMB']) * 1024
        return {'state': VMWARE_POWER_STATES[query['runtime.powerState']],
                'max_mem': max_mem,
                'mem': max_mem,
                'num_cpu': int(query['summary.config.numCpu']),
                'cpu_time': 0}

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        msg = _("get_diagnostics not implemented for vmwareapi")
        raise NotImplementedError(msg)

    def get_console_output(self, instance):
        """Return snapshot of console."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        param_list = {"id": str(vm_ref.value)}
        base_url = "%s://%s/screen?%s" % (self._session._scheme,
                                         self._session._host_ip,
                                         urllib.urlencode(param_list))
        request = urllib2.Request(base_url)
        base64string = base64.encodestring(
                        '%s:%s' % (
                        self._session._host_username,
                        self._session._host_password)).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        result = urllib2.urlopen(request)
        if result.code == 200:
            return result.read()
        else:
            return ""

    def get_vnc_console(self, instance):
        """Return connection info for a vnc console."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        return {'host': CONF.vmware.host_ip,
                'port': self._get_vnc_port(vm_ref),
                'internal_access_path': None}

    def get_vnc_console_vcenter(self, instance):
        """Return connection info for a vnc console using vCenter logic."""

        # vCenter does not run virtual machines and does not run
        # a VNC proxy. Instead, you need to tell OpenStack to talk
        # directly to the ESX host running the VM you are attempting
        # to connect to via VNC.

        vnc_console = self.get_vnc_console(instance)
        host_name = vm_util.get_host_name_for_vm(
                        self._session,
                        instance)
        vnc_console['host'] = host_name

        # NOTE: VM can move hosts in some situations. Debug for admins.
        LOG.debug(_("VM %(uuid)s is currently on host %(host_name)s"),
                {'uuid': instance['name'], 'host_name': host_name})

        return vnc_console

    @staticmethod
    def _get_vnc_port(vm_ref):
        """Return VNC port for an VM."""
        vm_id = int(vm_ref.value.replace('vm-', ''))
        port = CONF.vmware.vnc_port + vm_id % CONF.vmware.vnc_port_total

        return port

    @staticmethod
    def _get_machine_id_str(network_info):
        machine_id_str = ''
        for vif in network_info:
            # TODO(vish): add support for dns2
            # TODO(sateesh): add support for injection of ipv6 configuration
            network = vif['network']
            ip_v4 = netmask_v4 = gateway_v4 = broadcast_v4 = dns = None
            subnets_v4 = [s for s in network['subnets'] if s['version'] == 4]
            if len(subnets_v4[0]['ips']) > 0:
                ip_v4 = subnets_v4[0]['ips'][0]
            if len(subnets_v4[0]['dns']) > 0:
                dns = subnets_v4[0]['dns'][0]['address']

            netmask_v4 = str(subnets_v4[0].as_netaddr().netmask)
            gateway_v4 = subnets_v4[0]['gateway']['address']
            broadcast_v4 = str(subnets_v4[0].as_netaddr().broadcast)

            interface_str = ";".join([vif['address'],
                                      ip_v4 and ip_v4['address'] or '',
                                      netmask_v4 or '',
                                      gateway_v4 or '',
                                      broadcast_v4 or '',
                                      dns or ''])
            machine_id_str = machine_id_str + interface_str + '#'
        return machine_id_str

    def _set_machine_id(self, client_factory, instance, network_info):
        """
        Set the machine id of the VM for guest tools to pick up and reconfigure
        the network interfaces.
        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        machine_id_change_spec = vm_util.get_machine_id_change_spec(
                                 client_factory,
                                 self._get_machine_id_str(network_info))

        LOG.debug(_("Reconfiguring VM instance to set the machine id"),
                  instance=instance)
        reconfig_task = self._session._call_method(self._session._get_vim(),
                           "ReconfigVM_Task", vm_ref,
                           spec=machine_id_change_spec)
        self._session._wait_for_task(instance['uuid'], reconfig_task)
        LOG.debug(_("Reconfigured VM instance to set the machine id"),
                  instance=instance)

    def _set_vnc_config(self, client_factory, instance, port, password):
        """
        Set the vnc configuration of the VM.
        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        vnc_config_spec = vm_util.get_vnc_config_spec(
                                      client_factory, port, password)

        LOG.debug(_("Reconfiguring VM instance to enable vnc on "
                  "port - %(port)s") % {'port': port},
                  instance=instance)
        reconfig_task = self._session._call_method(self._session._get_vim(),
                           "ReconfigVM_Task", vm_ref,
                           spec=vnc_config_spec)
        self._session._wait_for_task(instance['uuid'], reconfig_task)
        LOG.debug(_("Reconfigured VM instance to enable vnc on "
                  "port - %(port)s") % {'port': port},
                  instance=instance)

    def get_datacenter_ref_and_name(self, ds_ref):
        """Get the datacenter name and the reference."""
        map = self._datastore_dc_mapping.get(ds_ref.value)
        if not map:
            dc_obj = self._session._call_method(vim_util, "get_objects",
                    "Datacenter", ["name"])
            vm_util._cancel_retrieve_if_necessary(self._session, dc_obj)
            map = DcInfo(ref=dc_obj.objects[0].obj,
                         name=dc_obj.objects[0].propSet[0].val,
                         vmFolder=self._get_vmfolder_ref())
            self._datastore_dc_mapping[ds_ref.value] = map
        return map
    
    def _get_datacenter_ref_and_name(self):
        """Get the datacenter name and the reference."""
        dc_obj = self._session._call_method(vim_util, "get_objects",
                "Datacenter", ["name"])
        vm_util._cancel_retrieve_if_necessary(self._session, dc_obj)
        return dc_obj.objects[0].obj, dc_obj.objects[0].propSet[0].val

    def _get_host_ref_from_name(self, host_name):
        """Get reference to the host with the name specified."""
        host_objs = self._session._call_method(vim_util, "get_objects",
                    "HostSystem", ["name"])
        vm_util._cancel_retrieve_if_necessary(self._session, host_objs)
        for host in host_objs:
            if host.propSet[0].val == host_name:
                return host.obj
        return None
    
    def _get_vm_ref_from_name_folder(self, vmfolder_ref, name):
        obj_refs = self._session._call_method(vim_util, "get_dynamic_property", vmfolder_ref, "Folder", "childEntity")
        for obj_ref in obj_refs.ManagedObjectReference:
            if obj_ref._type != "VirtualMachine":
                continue
            vm_name = self._session._call_method(vim_util, "get_dynamic_property", obj_ref, "VirtualMachine", "name")
            if vm_name == name:
                return obj_ref
        raise exception.VMNotFound()                
       
    def _get_vmfolder_ref(self, vmfolder_moid=None):
        
        if vmfolder_moid is None:
            """Get the Vm folder ref from the datacenter."""
            dc_objs = self._session._call_method(vim_util, "get_objects",
                                                 "Datacenter", ["vmFolder"])
            vm_util._cancel_retrieve_if_necessary(self._session, dc_objs)
            # There is only one default datacenter in a standalone ESX host
            vm_folder_ref = dc_objs.objects[0].propSet[0].val
            return vm_folder_ref
        else:
            dc_objs = self._session._call_method(vim_util, "get_objects", "Datacenter", ["vmFolder"])
            #TODO(giri): do this recursively for an infinite folder tree depth
            vmfolder_refs = self._session._call_method(vim_util, "get_dynamic_property", dc_objs.objects[0].propSet[0].val, "Folder", "childEntity")
            for vmfolder_ref in vmfolder_refs.ManagedObjectReference:
                if vmfolder_ref.value == vmfolder_moid:
                    return vmfolder_ref
            raise exception.VMFolderNotFound()                
    
    def _get_res_pool_ref(self, resourcepool_moid=None):
        res_pool_ref = None
        if resourcepool_moid or  self._cluster is None:
            resourcepools = self._session._call_method(vim_util, "get_objects", "ResourcePool")
            if self._cluster is None:
                vm_util._cancel_retrieve_if_necessary(self._session, resourcepools)
                res_pool_ref = resourcepools.objects[0].obj
                return res_pool_ref
            while resourcepools:
                token = vm_util._get_token(resourcepools)
                for obj_content in resourcepools.objects:
                    if obj_content.obj.value == resourcepool_moid:
                        res_pool_ref =  obj_content.obj
                if res_pool_ref:
                    if token:
                        self._session._call_method(vim_util,
                                             "cancel_retrieve",
                                             token)
                    return res_pool_ref
                if token:
                    resourcepools = self._session._call_method(vim_util,
                                                               "continue_to_get_objects",
                                                               token)
                else:
                    break                    
            raise exception.ResourcePoolNotFound()                
            
        else:
            res_pool_ref = self._session._call_method(vim_util,
                                                      "get_dynamic_property",
                                                      self._cluster,
                                                      "ClusterComputeResource",
                                                      "resourcePool")
        return res_pool_ref
    
    def _get_network_ref(self, network_moid, dc_ref):
        network_folder_ref = self._session._call_method(vim_util, "get_dynamic_property", dc_ref, "Datacenter", "networkFolder")
        network_refs = self._session._call_method(vim_util, "get_dynamic_property", network_folder_ref, "Folder", "childEntity")
        for network_ref in network_refs.ManagedObjectReference:
            if network_ref.__class__.__name__ == "Network" or network_ref.__class__.__name__ == "DistributedVirtualPortgroup":
                if network_ref.value == network_moid:
                    return network_ref
        raise exception.NetworkNotFound()                


    def _path_exists(self, ds_browser, ds_path):
        """Check if the path exists on the datastore."""
        search_task = self._session._call_method(self._session._get_vim(),
                                   "SearchDatastore_Task",
                                   ds_browser,
                                   datastorePath=ds_path)
        # Wait till the state changes from queued or running.
        # If an error state is returned, it means that the path doesn't exist.
        while True:
            task_info = self._session._call_method(vim_util,
                                       "get_dynamic_property",
                                       search_task, "Task", "info")
            if task_info.state in ['queued', 'running']:
                time.sleep(2)
                continue
            break
        if task_info.state == "error":
            return False
        return True

    def _path_file_exists(self, ds_browser, ds_path, file_name):
        """Check if the path and file exists on the datastore."""
        client_factory = self._session._get_vim().client.factory
        search_spec = vm_util.search_datastore_spec(client_factory, file_name)
        search_task = self._session._call_method(self._session._get_vim(),
                                   "SearchDatastore_Task",
                                   ds_browser,
                                   datastorePath=ds_path,
                                   searchSpec=search_spec)
        # Wait till the state changes from queued or running.
        # If an error state is returned, it means that the path doesn't exist.
        while True:
            task_info = self._session._call_method(vim_util,
                                       "get_dynamic_property",
                                       search_task, "Task", "info")
            if task_info.state in ['queued', 'running']:
                time.sleep(2)
                continue
            break
        if task_info.state == "error":
            return False, False

        file_exists = (getattr(task_info.result, 'file', False) and
                       task_info.result.file[0].path == file_name)
        return True, file_exists

    def _mkdir(self, ds_path, ds_ref):
        """
        Creates a directory at the path specified. If it is just "NAME",
        then a directory with this name is created at the topmost level of the
        DataStore.
        """
        LOG.debug(_("Creating directory with path %s") % ds_path)
        dc_info = self.get_datacenter_ref_and_name(ds_ref)
        self._session._call_method(self._session._get_vim(), "MakeDirectory",
                    self._session._get_vim().get_service_content().fileManager,
                    name=ds_path, datacenter=dc_info.ref,
                    createParentDirectories=False)
        LOG.debug(_("Created directory with path %s") % ds_path)

    def _check_if_folder_file_exists(self, ds_ref, ds_name,
                                     folder_name, file_name):
        ds_browser = vim_util.get_dynamic_property(
                                self._session._get_vim(),
                                ds_ref,
                                "Datastore",
                                "browser")
        # Check if the folder exists or not. If not, create one
        # Check if the file exists or not.
        folder_path = vm_util.build_datastore_path(ds_name, folder_name)
        folder_exists, file_exists = self._path_file_exists(ds_browser,
                                                            folder_path,
                                                            file_name)
        if not folder_exists:
            self._mkdir(vm_util.build_datastore_path(ds_name, folder_name),
                        ds_ref)

        return file_exists

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance."""
        # Set the machine.id parameter of the instance to inject
        # the NIC configuration inside the VM
        client_factory = self._session._get_vim().client.factory
        self._set_machine_id(client_factory, instance, network_info)

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        pass

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        pass
    
    def _replace_last(self, source_string, replace_what, replace_with):
        head, sep, tail = source_string.rpartition(replace_what)
        return head + replace_with + tail      
  
    @autolog.log_method(Logger, 'vmwareapi.vmops.pre_snapshot_vm')
    def pre_snapshot_vm(self, cntx, db, instance, snapshot):
        pass 
        
    @autolog.log_method(Logger, 'vmwareapi.vmops.snapshot_vm')
    def snapshot_vm(self, cntx, db, instance, snapshot):  
        
        vm_ref = vm_util.get_vm_ref(self._session, {'uuid': instance['vm_id'],
                                                    'vm_name': instance['vm_name'],
                                                    'vmware_uuid':instance['vmware_uuid'],
                                                    })
        
        hardware_devices = self._session._call_method(vim_util,"get_dynamic_property", vm_ref,
                                                      "VirtualMachine", "config.hardware.device")
        disks = vm_util.get_disks(hardware_devices)

        lst_properties = ["config.files.vmPathName", "runtime.powerState"]
        props = self._session._call_method(vim_util,
                    "get_object_properties",None, vm_ref, "VirtualMachine", lst_properties)
        query = {'config.files.vmPathName': None}
        self._get_values_from_object_properties(props, query)
        vmx_file_path = query['config.files.vmPathName']
        if vmx_file_path:
            datastore_name, vmx_file_name = vm_util.split_datastore_path(vmx_file_path)
        vmx_file = {'vmx_file_path': vmx_file_path, 
                    'datastore_name': datastore_name,
                    'vmx_file_name': vmx_file_name}
                
        snapshot_task = self._session._call_method(
                    self._session._get_vim(),
                    "CreateSnapshot_Task", vm_ref,
                    name="snapshot_id:%s" % snapshot['id'],
                    description="Trilio VAST Snapshot",
                    memory=False,
                    quiesce=True)
        self._session._wait_for_task(instance['vm_id'], snapshot_task)
        snapshot_data = {'disks' : disks, 'vmx_file' : vmx_file}
        return snapshot_data
      
                    
    @autolog.log_method(Logger, 'vmwareapi.vmops.get_snapshot_disk_info')
    def get_snapshot_disk_info(self, cntx, db, instance, snapshot, snapshot_data):
        
        return snapshot_data
            
    @autolog.log_method(Logger, 'vmwareapi.vmops.get_snapshot_data_size')
    def get_snapshot_data_size(self, cntx, db, instance, snapshot, snapshot_data):
        
        def _get_vmdk_file_size(file_path, datastore_name):
            tmp, vmdk_descriptor_file = vm_util.split_datastore_path(file_path)
            try:
                vmdk_data_file = self._replace_last(vmdk_descriptor_file, '.vmdk', '-delta.vmdk')
                vmdk_data_file_handle = read_write_util.VMwareHTTPReadFile(
                                                        self._session._host_ip,
                                                        self._get_datacenter_ref_and_name()[1],
                                                        datastore_name,
                                                        cookies,
                                                        vmdk_data_file)
            
            except Exception as ex:
                vmdk_data_file = self._replace_last(vmdk_descriptor_file, '.vmdk', '-flat.vmdk')
                vmdk_data_file_handle = read_write_util.VMwareHTTPReadFile(
                                                        self._session._host_ip,
                                                        self._get_datacenter_ref_and_name()[1],
                                                        datastore_name,
                                                        cookies,
                                                        vmdk_data_file)                     
                     
            vmdk_file_size = int(vmdk_data_file_handle.get_size())
            return vmdk_file_size            
       
        vm_data_size = 0
        cookies = self._session._get_vim().client.options.transport.cookiejar
        for disk in  snapshot_data['disks']:         
            full = True
            if snapshot['snapshot_type'] != 'full':
                vm_recent_snapshot = db.vm_recent_snapshot_get(cntx, instance['vm_id'])
                if vm_recent_snapshot:
                    #TODO(giri): the disk could have changed between the snapshots
                    #TODO(giri): handle the snapshots created out side of WLM                    
                    previous_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_name(
                                                            cntx, 
                                                            instance['vm_id'], 
                                                            vm_recent_snapshot.snapshot_id, 
                                                            disk['label'])
                    if previous_snapshot_vm_resource and previous_snapshot_vm_resource.status == 'available':
                        previous_vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, previous_snapshot_vm_resource.id)
                        if previous_vm_disk_resource_snap and previous_vm_disk_resource_snap.status == 'available':
                            vm_disk_resource_snap_backing_id = previous_vm_disk_resource_snap.id
                            full = False                           
                        

            vm_data_size = vm_data_size +_get_vmdk_file_size(disk['vmdk_file_path'], disk['datastore_name'])
            if full:
                for backing in disk['backings']:
                    vm_data_size = vm_data_size +_get_vmdk_file_size(backing['vmdk_file_path'], backing['datastore_name'])                    
          
                                     
                    
        return vm_data_size 
    
    @autolog.log_method(Logger, 'vmwareapi.vmops..upload_snapshot')
    def upload_snapshot(self, cntx, db, instance, snapshot, snapshot_data):

        def _upload_vmdk_extent(vmdk_extent_file, vm_disk_resource_snap_backing_id, top):
            datastore_name, vmdk_descriptor_file = vm_util.split_datastore_path(vmdk_extent_file)
                            
            vmdk_descriptor_file_handle = read_write_util.VMwareHTTPReadFile(
                                                    self._session._host_ip,
                                                    self._get_datacenter_ref_and_name()[1],
                                                    datastore_name,
                                                    cookies,
                                                    vmdk_descriptor_file)
            vmdk_descriptor_file_size = int(vmdk_descriptor_file_handle.get_size())
            #TODO(giri): throw exception if the size is more than 65536    
            vmdk_descriptor = vmdk_descriptor_file_handle.read(vmdk_descriptor_file_size)
            vmdk_descriptor_file_handle.close()
            
            try:
                vmdk_data_file = self._replace_last(vmdk_descriptor_file, '.vmdk', '-delta.vmdk')
                vmdk_data_file_handle = read_write_util.VMwareHTTPReadFile(
                                                        self._session._host_ip,
                                                        self._get_datacenter_ref_and_name()[1],
                                                        datastore_name,
                                                        cookies,
                                                        vmdk_data_file)
            
            except Exception as ex:
                vmdk_data_file = self._replace_last(vmdk_descriptor_file, '.vmdk', '-flat.vmdk')
                vmdk_data_file_handle = read_write_util.VMwareHTTPReadFile(
                                                        self._session._host_ip,
                                                        self._get_datacenter_ref_and_name()[1],
                                                        datastore_name,
                                                        cookies,
                                                        vmdk_data_file)                     
                     
            vmdk_extent_size = int(vmdk_data_file_handle.get_size())
                        
            # create an entry in the vm_disk_resource_snaps table
            vm_disk_resource_snap_id = str(uuid.uuid4())
            vm_disk_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_disk_resource_snap_metadata.setdefault('disk_format','vmdk')
            vm_disk_resource_snap_metadata.setdefault('vmware_disktype','thin')
            vm_disk_resource_snap_metadata.setdefault('vmware_adaptertype','lsiLogic')
            vm_disk_resource_snap_metadata.setdefault('vmdk_descriptor',vmdk_descriptor)
            vm_disk_resource_snap_metadata.setdefault('vmdk_data_file_name',vmdk_data_file)
            vm_disk_resource_snap_values = { 'id': vm_disk_resource_snap_id,
                                             'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                             'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                                             'metadata': vm_disk_resource_snap_metadata,       
                                             'top':  top,
                                             'size': vmdk_extent_size,                                             
                                             'status': 'creating'}     
                                                 
            vm_disk_resource_snap = db.vm_disk_resource_snap_create(cntx, vm_disk_resource_snap_values) 
    
            vault_metadata = {'metadata': vm_disk_resource_snap_metadata,
                              'vm_disk_resource_snap_id' : vm_disk_resource_snap_id,
                              'snapshot_vm_resource_id': snapshot_vm_resource.id,
                              'resource_name':  disk['label'],
                              'snapshot_vm_id': instance['vm_id'],
                              'snapshot_id': snapshot_obj.id}


            
            db.snapshot_update( cntx, snapshot_obj.id, 
                                {'progress_msg': 'Uploading '+ disk['label'] + ' of VM:' + instance['vm_id'],
                                 'status': 'uploading'
                                })            
            LOG.debug(_('Uploading '+ disk['label'] + ' of VM:' + instance['vm_id'] + '; backing file:' + vmdk_data_file))
            vault_service_url = vault_service.store(vault_metadata, vmdk_data_file_handle, int(vmdk_data_file_handle.get_size()));
            db.snapshot_update( cntx, snapshot_obj.id, 
                                {'progress_msg': 'Uploaded '+ disk['label'] + ' of VM:' + instance['vm_id'],
                                 'status': 'uploading'
                                })   
            vmdk_data_file_handle.close() 
            # update the entry in the vm_disk_resource_snap table
            vm_disk_resource_snap_values = {'vault_service_url' :  vault_service_url ,
                                            'vault_service_metadata' : 'None',
                                            'status': 'available'}
            db.vm_disk_resource_snap_update(cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
            
            return vmdk_extent_size, vm_disk_resource_snap.id             
           
       
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        vault_service = vault.get_vault_service(cntx)
        cookies = self._session._get_vim().client.options.transport.cookiejar
                
                
        for disk in snapshot_data['disks']: 
            vm_disk_size = 0
            snapshot_vm_resource_metadata = {}
            snapshot_vm_resource_metadata['vmdk_controler_key'] = disk['vmdk_controler_key']
            snapshot_vm_resource_metadata['adapter_type'] = disk['adapter_type']
            snapshot_vm_resource_metadata['label'] = disk['label']
            snapshot_vm_resource_metadata['unit_number'] = disk['unit_number']
            snapshot_vm_resource_metadata['disk_type'] = disk['disk_type']
            snapshot_vm_resource_metadata['capacityInKB'] = disk['capacityInKB']
            
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                           'vm_id': instance['vm_id'],
                                           'snapshot_id': snapshot_obj.id,       
                                           'resource_type': 'disk',
                                           'resource_name':  disk['label'],
                                           'metadata': snapshot_vm_resource_metadata,
                                           'status': 'creating'}
    
            snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, snapshot_vm_resource_values)                                                

            full = True
            vm_disk_resource_snap_backing_id = None
            if snapshot['snapshot_type'] != 'full':
                vm_recent_snapshot = db.vm_recent_snapshot_get(cntx, instance['vm_id'])
                if vm_recent_snapshot:
                    #TODO(giri): the disk colud have changed between the snapshots
                    #TODO(giri): handle the snapshots created out side of WLM
                    previous_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_name(
                                                            cntx, 
                                                            instance['vm_id'], 
                                                            vm_recent_snapshot.snapshot_id, 
                                                            disk['label'])
                    if previous_snapshot_vm_resource and previous_snapshot_vm_resource.status == 'available':
                        previous_vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, previous_snapshot_vm_resource.id)
                        if previous_vm_disk_resource_snap and previous_vm_disk_resource_snap.status == 'available':
                            vm_disk_resource_snap_backing_id = previous_vm_disk_resource_snap.id
                            full = False                           

            if full:
                for backing in disk['backings']:
                    vmdk_extent_size, vm_disk_resource_snap_backing_id = _upload_vmdk_extent(backing['vmdk_file_path'], 
                                                                                            vm_disk_resource_snap_backing_id, 
                                                                                            False)
                    vm_disk_size = vm_disk_size + vmdk_extent_size
                    
            vmdk_extent_size, vm_disk_resource_snap_backing_id = _upload_vmdk_extent(disk['vmdk_file_path'], 
                                                                                     vm_disk_resource_snap_backing_id, 
                                                                                     True)                    
            vm_disk_size = vm_disk_size + vmdk_extent_size
            db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, {'status': 'available', 'size': vm_disk_size})
            
        #vmx file 
        vmx_file_handle = read_write_util.VMwareHTTPReadFile(
                                                self._session._host_ip,
                                                self._get_datacenter_ref_and_name()[1],
                                                snapshot_data['vmx_file']['datastore_name'],
                                                cookies,
                                                snapshot_data['vmx_file']['vmx_file_name'])
        vmx_file_size = int(vmx_file_handle.get_size())
        #TODO(giri): throw exception if the size is more than 65536    
        vmx_file_data = vmx_file_handle.read(vmx_file_size)
        vmx_file_handle.close()        
        snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                       'vm_id': instance['vm_id'],
                                       'snapshot_id': snapshot_obj.id,       
                                       'resource_type': 'vmx',
                                       'resource_name':  snapshot_data['vmx_file']['vmx_file_name'],
                                       'metadata': {'vmx_file_data':vmx_file_data},
                                       'status': 'creating'}

        snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, snapshot_vm_resource_values)                                                
        db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, {'status': 'available', 'size': vmx_file_size})
        

    @autolog.log_method(Logger, 'vmwareapi.vmops.post_snapshot_vm')
    def post_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_data): 
        
        def _get_snapshot_to_remove(snapshot_list):
            snapshot_to_remove = None
            if snapshot_list:    
                for vmw_snapshot in snapshot_list:
                    if vmw_snapshot.name == ('snapshot_id:' + vm_recent_snapshot.snapshot_id) :
                        snapshot_to_remove = vmw_snapshot.snapshot
                        break
                    if hasattr(vmw_snapshot, 'childSnapshotList'):
                        snapshot_to_remove = _get_snapshot_to_remove(vmw_snapshot.childSnapshotList)
                        if snapshot_to_remove:
                            break
            return snapshot_to_remove             

        vm_recent_snapshot = db.vm_recent_snapshot_get(cntx, instance['vm_id'])
        if vm_recent_snapshot:
            vm_ref = vm_util.get_vm_ref(self._session, {'uuid': instance['vm_id'],
                                                        'vm_name': instance['vm_name'],
                                                        'vmware_uuid':instance['vmware_uuid'],
                                                        })
            root_snapshot_array = self._session._call_method(vim_util,"get_dynamic_property", vm_ref, "VirtualMachine", "snapshot.rootSnapshotList")
           
            if root_snapshot_array and len(root_snapshot_array) > 0 : 
                snapshot_to_remove = _get_snapshot_to_remove(root_snapshot_array[0])
                if snapshot_to_remove :
                    remove_snapshot_task = self._session._call_method(
                                            self._session._get_vim(),
                                            "RemoveSnapshot_Task", snapshot_to_remove,
                                            removeChildren=False)
                    self._session._wait_for_task(instance['vm_id'], remove_snapshot_task)
    
    @autolog.log_method(Logger, 'vmwareapi.vmops.restore_vm')
    def restore_vm(self, cntx, db, instance, restore, restored_net_resources, restored_security_groups,
                   restored_compute_flavor, restored_nics, instance_options):  
        
        restore_obj = db.restore_get(cntx, restore['id'])
        snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
        instance['uuid']= instance_name = instance['vm_id']
        instance['name']= instance_uuid = instance['vm_name']
    
        msg = 'Creating VM ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id  
        db.restore_update(cntx,  restore_obj.id, {'progress_msg': msg})
        
        client_factory = self._session._get_vim().client.factory
        service_content = self._session._get_vim().get_service_content()
        cookies = self._session._get_vim().client.options.transport.cookiejar
        ds = vm_util.get_datastore_ref_and_name(self._session, datastore_moid=instance_options['datastore']['moid'])
        datastore_ref = ds[0]
        datastore_name = ds[1]
        dc_info = self.get_datacenter_ref_and_name(datastore_ref)
        
        vm_folder_name = restore['id'] + '-' + instance['vm_name']
        vm_folder_path = vm_util.build_datastore_path(datastore_name, vm_folder_name)
        self._mkdir(vm_folder_path, datastore_ref)
    
        vault_service = vault.get_vault_service(cntx)
        snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'], snapshot_obj.id)
    
        """Restore vmx file"""
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type == 'vmx':
                vmx_name = "%s/%s" % (vm_folder_name, os.path.basename(snapshot_vm_resource.resource_name))
                vmdk_write_file_handle = read_write_util.VMwareHTTPWriteFile(
                                        self._session._host_ip,
                                        instance_options['datacenter']['name'],
                                        instance_options['datastore']['name'],
                                        cookies,
                                        vmx_name,
                                        snapshot_vm_resource.size)
                vmx_file_data =  db.get_metadata_value(snapshot_vm_resource.metadata,'vmx_file_data')              
                vmdk_write_file_handle.write(vmx_file_data)
                vmdk_write_file_handle.close()    
                
        """Register VM on ESX host."""
        LOG.debug(_("Registering VM on the ESX host"))
        # Create the VM on the ESX host
        if 'vmfolder' in instance_options:
            if 'moid' in instance_options['vmfolder']:
                vm_folder_ref = self._get_vmfolder_ref(instance_options['vmfolder']['moid'])
        if not vm_folder_ref:
            vm_folder_ref = self._get_vmfolder_ref()    
        
        resourcepool_ref = self._get_res_pool_ref(instance_options['resourcepool']['moid'])
        vmx_path = vm_util.build_datastore_path(datastore_name, vmx_name)
        vm_register_task = self._session._call_method(
                                self._session._get_vim(),
                                "RegisterVM_Task", 
                                vm_folder_ref,
                                path=vmx_path,
                                name=instance['vm_name'],
                                asTemplate=False,
                                pool=resourcepool_ref,
                                #host=computeresource_ref,
                                )
        self._session._wait_for_task(instance['uuid'], vm_register_task)

        LOG.debug(_("Registered VM on the ESX host"))
        
        vm_ref = self._get_vm_ref_from_name_folder(vm_folder_ref, instance['vm_name'])
        hardware_devices = self._session._call_method(vim_util,"get_dynamic_property", vm_ref,
                                                      "VirtualMachine", "config.hardware.device")
        if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
            hardware_devices = hardware_devices.VirtualDevice
        
        for device in hardware_devices:
            if device.__class__.__name__ == "VirtualDisk":
                self._volumeops.detach_disk_from_vm(vm_ref, instance, device, destroy_disk=False)
        
        for device in hardware_devices:
            if device.backing and device.backing.__class__.__name__ == "VirtualEthernetCardNetworkBackingInfo":
                for nic in instance_options['nics']:
                    if device.backing.deviceName == nic['network_name']:
                        device.backing.deviceName = nic['new_network_name']
                        device.backing.network = self._get_network_ref(nic['new_network_moid'], dc_info.ref) 
                        virtual_device_config_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
                        virtual_device_config_spec.operation = "edit"
                        virtual_device_config_spec.operationSpecified = True
                        virtual_device_config_spec.fileOperationSpecified = False
                        LOG.debug(_("Reconfiguring VM instance %(instance_name)s for nic %(nic_label) %",
                                    {'instance_name': instance_name, 'nic_label': device.deviceInfo.label}))
                        reconfig_task = self._session._call_method( self._session._get_vim(),
                                                                    "ReconfigVM_Task", vm_ref,
                                                                    spec=virtual_device_config_spec)
                        self._session._wait_for_task(instance_uuid, reconfig_task)
                        LOG.debug(_("Reconfigured VM instance %(instance_name)s for nic %(nic_label) %",
                                    {'instance_name': instance_name, 'nic_label': device.deviceInfo.label}))
                        

                        
        
        #restore, rebase, commit & upload
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type != 'disk':
                continue
            temp_directory = os.path.join("/opt/stack/data/wlm", restore['id'], snapshot_vm_resource.id)
            try:
                shutil.rmtree( temp_directory )
            except OSError as exc:
                pass
            fileutils.ensure_tree(temp_directory)
            
            commit_queue = Queue() # queue to hold the files to be committed                 
            vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
            disk_filename_extention = db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format')
            restored_file_path =temp_directory + '/' + vm_disk_resource_snap.id + \
                                '_' + snapshot_vm_resource.resource_name + '.' \
                                + disk_filename_extention
            restored_file_path = restored_file_path.replace(" ", "")
            vault_metadata = {'vault_service_url' : vm_disk_resource_snap.vault_service_url,
                              'vault_service_metadata' : vm_disk_resource_snap.vault_service_metadata,
                              'vm_disk_resource_snap_id' : vm_disk_resource_snap.id,
                              'disk_format' : db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format'),                              
                              'snapshot_vm_resource_id': snapshot_vm_resource.id,
                              'resource_name':  snapshot_vm_resource.resource_name,
                              'snapshot_vm_id': snapshot_vm_resource.vm_id,
                              'snapshot_id': snapshot_vm_resource.snapshot_id,
                              'restore_id': restore_obj.id}
            LOG.debug('Restoring ' + vm_disk_resource_snap.vault_service_url)
            vault_service.restore(vault_metadata, restored_file_path)
            LOG.debug('Restored ' + vm_disk_resource_snap.vault_service_url)

            if(db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'vmdk'):
                if vm_disk_resource_snap.vm_disk_resource_snap_backing_id is None:
                    self.rebase_vmdk(restored_file_path,
                                     db.get_metadata_value(vm_disk_resource_snap.metadata,'vmdk_data_file_name'),
                                     db.get_metadata_value(vm_disk_resource_snap.metadata,'vmdk_descriptor'),
                                     None,
                                     None,
                                     None)
                    commit_queue.put(restored_file_path)  
                                 
            while vm_disk_resource_snap.vm_disk_resource_snap_backing_id is not None:
                vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(cntx, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                snapshot_vm_resource_backing = db.snapshot_vm_resource_get(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                restored_file_path_backing =temp_directory + '/' + vm_disk_resource_snap_backing.id + \
                                            '_' + snapshot_vm_resource_backing.resource_name + '.' \
                                            + disk_filename_extention
                restored_file_path_backing = restored_file_path_backing.replace(" ", "")
                vault_metadata = {'vault_service_url' : vm_disk_resource_snap_backing.vault_service_url,
                                  'vault_service_metadata' : vm_disk_resource_snap_backing.vault_service_metadata,
                                  'vm_disk_resource_snap_id' : vm_disk_resource_snap_backing.id,
                                  'disk_format' : db.get_metadata_value(vm_disk_resource_snap_backing.metadata,'disk_format'),
                                  'snapshot_vm_resource_id': snapshot_vm_resource_backing.id,
                                  'resource_name':  snapshot_vm_resource_backing.resource_name,
                                  'snapshot_vm_id': snapshot_vm_resource_backing.vm_id,
                                  'snapshot_id': snapshot_vm_resource_backing.snapshot_id,
                                  'restore_id': restore_obj.id}
                LOG.debug('Restoring ' + vm_disk_resource_snap_backing.vault_service_url)
                vault_service.restore(vault_metadata, restored_file_path_backing)
                LOG.debug('Restored ' + vm_disk_resource_snap_backing.vault_service_url)     
                #rebase
                if(db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'qcow2'):
                    image_info = qemuimages.qemu_img_info(restored_file_path)
                    image_backing_info = qemuimages.qemu_img_info(restored_file_path_backing)
                    #covert the raw image to qcow2
                    if image_backing_info.file_format == 'raw':
                        converted = os.path.join(os.path.dirname(restored_file_path_backing), str(uuid.uuid4()))
                        LOG.debug('Converting ' + restored_file_path_backing + ' to QCOW2')  
                        qemuimages.convert_image(restored_file_path_backing, converted, 'qcow2')
                        LOG.debug('Finished Converting ' + restored_file_path_backing + ' to QCOW2')
                        utils.delete_if_exists(restored_file_path_backing)
                        shutil.move(converted, restored_file_path_backing)
                        image_backing_info = qemuimages.qemu_img_info(restored_file_path_backing)
                    #increase the size of the base image
                    if image_backing_info.virtual_size < image_info.virtual_size :
                        qemuimages.resize_image(restored_file_path_backing, image_info.virtual_size)  
                    #rebase the image                            
                    qemuimages.rebase_qcow2(restored_file_path_backing, restored_file_path)
                elif(db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'vmdk'):
                    self.rebase_vmdk(restored_file_path_backing,
                                     db.get_metadata_value(vm_disk_resource_snap_backing.metadata,'vmdk_data_file_name'),
                                     db.get_metadata_value(vm_disk_resource_snap_backing.metadata,'vmdk_descriptor'),
                                     restored_file_path,
                                     db.get_metadata_value(vm_disk_resource_snap.metadata,'vmdk_data_file_name'),
                                     db.get_metadata_value(vm_disk_resource_snap.metadata,'vmdk_descriptor'))               
                commit_queue.put(restored_file_path)                                 
                vm_disk_resource_snap = vm_disk_resource_snap_backing
                restored_file_path = restored_file_path_backing

            if(db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'qcow2'):
                while commit_queue.empty() is not True:
                    file_to_commit = commit_queue.get_nowait()
                    try:
                        LOG.debug('Commiting QCOW2 ' + file_to_commit)
                        qemuimages.commit_qcow2(file_to_commit)
                    except Exception, ex:
                        LOG.exception(ex)                       
                    if restored_file_path != file_to_commit:
                        utils.delete_if_exists(file_to_commit)
            elif(db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'vmdk'):
                    file_to_commit = commit_queue.get_nowait()
                    commit_to = temp_directory + '/' + vm_disk_resource_snap.id + '_Restored_' + snapshot_vm_resource.resource_name + '.' + disk_filename_extention
                    commit_to = commit_to.replace(" ", "")
                    LOG.debug('Commiting VMDK ' + file_to_commit)
                    restored_file_path = self.commit_vmdk(file_to_commit, commit_to, test=False)
           
            #create vmdk
            file_size = int(os.path.getsize(restored_file_path))
            vmdk_name = "%s/%s.vmdk" % (vm_folder_name, snapshot_vm_resource.resource_name.replace(' ', '-'))
            vmdk_path = vm_util.build_datastore_path(instance_options['datastore']['name'], vmdk_name)
            flat_vmdk_name = "%s/%s-flat.vmdk" % (vm_folder_name, snapshot_vm_resource.resource_name.replace(' ', '-'))
            flat_vmdk_path = vm_util.build_datastore_path(instance_options['datastore']['name'], flat_vmdk_name)
            
            vmdk_create_spec = vm_util.get_vmdk_create_spec(client_factory,
                                                            file_size/1024,  #vmdk_file_size_in_kb, 
                                                            'lsiLogic',      #adapter_type,
                                                            'preallocated'   #disk_type
                                                            )
            vmdk_create_task = self._session._call_method(self._session._get_vim(),
                                                          "CreateVirtualDisk_Task",
                                                          service_content.virtualDiskManager,
                                                          name=vmdk_path,
                                                          datacenter=dc_info.ref,
                                                          spec=vmdk_create_spec)
            self._session._wait_for_task(instance['uuid'], vmdk_create_task)
            self._delete_datastore_file(instance, flat_vmdk_path, dc_info.ref)
                    
            LOG.debug('Uploading image and volumes of instance ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id)        
            db.restore_update(cntx,  restore['id'], 
                              {'progress_msg': 'Uploading image and volumes of instance ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id,
                               'status': 'uploading' 
                              })                  
            
            vmdk_write_file_handle = read_write_util.VMwareHTTPWriteFile(
                                        self._session._host_ip,
                                        instance_options['datacenter']['name'],
                                        instance_options['datastore']['name'],
                                        cookies,
                                        flat_vmdk_name,
                                        file_size)

            for chunk in utils.ChunkedFile(restored_file_path, {'function': WorkloadMgrDB().db.restore_update,
                                                                'context': cntx,
                                                                'id':restore['id']}):
                vmdk_write_file_handle.write(chunk)
            vmdk_write_file_handle.close()

            adapter_type = db.get_metadata_value(snapshot_vm_resource.metadata,'adapter_type')
            capacityInKB = db.get_metadata_value(snapshot_vm_resource.metadata,'capacityInKB')
            vmdk_controler_key = db.get_metadata_value(snapshot_vm_resource.metadata,'vmdk_controler_key')
            unit_number = db.get_metadata_value(snapshot_vm_resource.metadata,'unit_number')
            disk_type = db.get_metadata_value(snapshot_vm_resource.metadata,'disk_type')
            device_name = db.get_metadata_value(snapshot_vm_resource.metadata,'label')
            linked_clone = False

            self._volumeops.attach_disk_to_vm( vm_ref, instance,
                                               adapter_type, disk_type, vmdk_path,
                                               capacityInKB, linked_clone,
                                               vmdk_controler_key, unit_number, device_name)
            
            
            restore_obj = db.restore_get(cntx, restore['id'])
            progress = "{message_color} {message} {progress_percent} {normal_color}".format(**{
                'message_color': autolog.BROWN,
                'message': "Restore Progress: ",
                'progress_percent': str(restore_obj.progress_percent),
                'normal_color': autolog.NORMAL,
                }) 
            LOG.debug( progress)    
                    


        restored_instance_id = self._session._call_method(vim_util,"get_dynamic_property", vm_ref,
                                                          "VirtualMachine", "config.uuid")
        restored_instance_name =  instance['vm_name']                                                
        restored_vm_values = {'vm_id': restored_instance_id,
                              'vm_name':  restored_instance_name,    
                              'restore_id': restore_obj.id,
                              'status': 'available'}
        restored_vm = db.restored_vm_create(cntx,restored_vm_values)
        
        
        
        LOG.debug(_("Restore Completed"))
         
        #TODO(giri): Execuete the following in a finally block
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type != 'disk':
                continue
            temp_directory = os.path.join("/opt/stack/data/wlm", restore['id'], snapshot_vm_resource.id)
            try:
                shutil.rmtree(temp_directory)
            except OSError as exc:
                pass 

         
        db.restore_update(cntx,restore_obj.id, 
                          {'progress_msg': 'Created VM ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id,
                           'status': 'executing'
                          })        
        db.restore_update( cntx, restore_obj.id, {'progress_msg': 'Created VM:' + restored_vm['vm_id'], 'status': 'executing'})
        return restored_vm          
    

class VMwareVCVMOps(VMwareVMOps):
    """Management class for VM-related tasks.

    Contains specializations to account for differences in vSphere API behavior
    when invoked on Virtual Center instead of ESX host.
    """

    def get_copy_virtual_disk_spec(self, client_factory, adapter_type,
                                   disk_type):
        LOG.debug(_("Will copy while retaining adapter type "
                    "%(adapter_type)s and disk type %(disk_type)s") %
                    {"disk_type": disk_type,
                     "adapter_type": adapter_type})
        # Passing of the destination copy spec is not supported when
        # VirtualDiskManager.CopyVirtualDisk is called on VC. The behavior of a
        # spec-less copy is to consolidate to the target disk while keeping its
        # disk and adapter type unchanged.
