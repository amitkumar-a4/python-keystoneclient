# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
A connection to the VMware ESX/vCenter platform.
"""

import os
import re
import time
import uuid
from Queue import Queue
import cPickle as pickle
import shutil
import math
import subprocess
from os import remove, close
from Queue import Queue, Empty
from threading  import Thread
from subprocess import call
from subprocess import check_call
from subprocess import check_output

from eventlet import event
from oslo.config import cfg

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import jsonutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import loopingcall
from workloadmgr.openstack.common import uuidutils
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import timeutils

from workloadmgr.virt import driver
from workloadmgr.virt.vmwareapi import error_util
from workloadmgr.virt.vmwareapi import host
from workloadmgr.virt.vmwareapi import vim
from workloadmgr.virt.vmwareapi import vim_util
from workloadmgr.virt.vmwareapi import vm_util
from workloadmgr.virt.vmwareapi import vmops
from workloadmgr.virt.vmwareapi import volumeops
from workloadmgr.virt.vmwareapi import read_write_util
from workloadmgr.vault import vault
from workloadmgr.virt import qemuimages
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import utils
from workloadmgr import exception
from workloadmgr import autolog
from workloadmgr.workflows import vmtasks


LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

vmwareapi_opts = [
    cfg.StrOpt('host_ip',
               deprecated_name='vmwareapi_host_ip',
               deprecated_group='DEFAULT',
               help='URL for connection to VMware ESX/VC host. Required if '
                    'compute_driver is vmwareapi.VMwareESXDriver or '
                    'vmwareapi.VMwareVCDriver.'),
    cfg.StrOpt('host_username',
               deprecated_name='vmwareapi_host_username',
               deprecated_group='DEFAULT',
               help='Username for connection to VMware ESX/VC host. '
                    'Used only if compute_driver is '
                    'vmwareapi.VMwareESXDriver or vmwareapi.VMwareVCDriver.'),
    cfg.StrOpt('host_password',
               deprecated_name='vmwareapi_host_password',
               deprecated_group='DEFAULT',
               help='Password for connection to VMware ESX/VC host. '
                    'Used only if compute_driver is '
                    'vmwareapi.VMwareESXDriver or vmwareapi.VMwareVCDriver.',
               secret=True),
    cfg.FloatOpt('task_poll_interval',
                 default=5.0,
                 deprecated_name='vmwareapi_task_poll_interval',
                 deprecated_group='DEFAULT',
                 help='The interval used for polling of remote tasks. '
                       'Used only if compute_driver is '
                       'vmwareapi.VMwareESXDriver or '
                       'vmwareapi.VMwareVCDriver.'),
    cfg.IntOpt('api_retry_count',
               default=10,
               deprecated_name='vmwareapi_api_retry_count',
               deprecated_group='DEFAULT',
               help='The number of times we retry on failures, e.g., '
                    'socket error, etc. '
                    'Used only if compute_driver is '
                    'vmwareapi.VMwareESXDriver or vmwareapi.VMwareVCDriver.'),
    ]

CONF = cfg.CONF
CONF.register_opts(vmwareapi_opts, 'vmware')

TIME_BETWEEN_API_CALL_RETRIES = 2.0


class Failure(Exception):
    """Base Exception class for handling task failures."""

    def __init__(self, details):
        self.details = details

    def __str__(self):
        return str(self.details)

def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()

class VMwareESXDriver(driver.ComputeDriver):
    """The ESX host connection object."""

    # VMwareAPI has both ESXi and vCenter API sets.
    # The ESXi API are a proper sub-set of the vCenter API.
    # That is to say, nearly all valid ESXi calls are
    # valid vCenter calls. There are some small edge-case
    # exceptions regarding VNC, CIM, User management & SSO.

    def __init__(self, virtapi, read_only=False, scheme="https"):
        super(VMwareESXDriver, self).__init__(virtapi)

        self._host_ip = CONF.vmware.host_ip
        if not (self._host_ip or CONF.vmware.host_username is None or
                        CONF.vmware.host_password is None):
            raise Exception(_("Must specify host_ip, "
                              "host_username "
                              "and host_password to use "
                              "compute_driver=vmwareapi.VMwareESXDriver or "
                              "vmwareapi.VMwareVCDriver"))

        self._session = VMwareAPISession(scheme=scheme)
        self._volumeops = volumeops.VMwareVolumeOps(self._session)

    def pause(self, cntx, db, instance):
        """Pause VM instance."""
        msg = _("pause not supported for vmwareapi")
        raise NotImplementedError(msg)

    def unpause(self, cntx, db, instance):
        """Unpause paused VM instance."""
        msg = _("unpause not supported for vmwareapi")
        raise NotImplementedError(msg)

    def suspend(self, cntx, db, instance):
        """Suspend the specified instance."""
        instance['uuid'] = instance['vm_id']
        vm_ref = vm_util.get_vm_ref(self._session, {'uuid': instance['vm_id'],
                                                    'vm_name': instance['vm_name'],
                                                    'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                                    })
                
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
            LOG.debug(_("instance is powered off and cannot be suspended. So returning "
                      "without doing anything"), instance=instance)
        else:
            LOG.debug(_("VM was already in suspended state. So returning "
                      "without doing anything"), instance=instance)

    def resume(self, cntx, db, instance):
        """Resume the specified instance."""
        instance['uuid'] = instance['vm_id']
        vm_ref = vm_util.get_vm_ref(self._session, {'uuid': instance['vm_id'],
                                                    'vm_name': instance['vm_name'],
                                                    'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                                    })
                
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
            LOG.debug(_("instance is not in suspended state. So returning "
                      "without doing anything"), instance=instance)


    def power_off(self, vm_ref, instance):
        """Power off the specified instance."""
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

    def power_on(self, vm_ref, instance):
        """Power on the specified instance."""
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
            vmSummary = self._session._call_method(vim_util, "get_dynamic_property", vm_ref,
                                                   "VirtualMachine", "summary")
            
            while vmSummary.runtime.powerState != "poweredOn":
                question_answered = False
                start = timeutils.utcnow()
                if hasattr(vmSummary.runtime, 'question') and vmSummary.runtime.question:
                    if "I copied it" in vmSummary.runtime.question.text:
                        for choiceInfo in vmSummary.runtime.question.choice.choiceInfo:
                            if "copied" in choiceInfo.label:
                                self._session._call_method(self._session._get_vim(),"AnswerVM", vm_ref,
                                                           questionId=vmSummary.runtime.question.id, 
                                                           answerChoice=choiceInfo.key)
                                question_answered = True
                                break
                if question_answered:
                    break
                vmSummary = self._session._call_method(vim_util, "get_dynamic_property", vm_ref,
                                                       "VirtualMachine", "summary")
                end = timeutils.utcnow()                            
                delay = CONF.vmware.task_poll_interval - timeutils.delta_seconds(start, end)
                if delay <= 0:
                    LOG.warn(_('timeout waiting for a question during poweron'))
                time.sleep(delay if delay > 0 else 0)
                       
            self._session._wait_for_task(instance['uuid'], poweron_task)
            LOG.debug(_("Powered on the VM"), instance=instance)

    def get_host_ip_addr(self):
        """Retrieves the IP address of the ESX host."""
        return self._host_ip


    
class VMwareVCDriver(VMwareESXDriver):
    """The ESX host connection object."""

    # The vCenter driver includes several additional VMware vSphere
    # capabilities that include API that act on hosts or groups of
    # hosts in clusters or non-cluster logical-groupings.
    #
    # vCenter is not a hypervisor itself, it works with multiple
    # hypervisor host machines and their guests. This fact can
    # subtly alter how vSphere and OpenStack interoperate.

    def __init__(self, virtapi, read_only=False, scheme="https"):
        super(VMwareVCDriver, self).__init__(virtapi)

        # Get the list of clusters to be used
        self._virtapi = virtapi

    def _mkdir(self, ds_path, datacenter_ref):
        """
        Creates a directory at the path specified. If it is just "NAME",
        then a directory with this name is created at the topmost level of the
        DataStore.
        """
        LOG.debug(_("Creating directory with path %s") % ds_path)
        self._session._call_method(self._session._get_vim(), "MakeDirectory",
                    self._session._get_vim().get_service_content().fileManager,
                    name=ds_path, datacenter=datacenter_ref,
                    createParentDirectories=False)
        LOG.debug(_("Created directory with path %s") % ds_path)

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

    def _replace_last(self, source_string, replace_what, replace_with):
        head, sep, tail = source_string.rpartition(replace_what)
        return head + replace_with + tail      

    def _get_datacenter_ref_and_name(self, datastore_ref):
        """Get the datacenter name and the reference."""
        datacenter_ref = None
        datacenter_name = None
        
        datacenters = self._session._call_method(vim_util, "get_objects",
                                                "Datacenter", ["datastore", "name"])
        while datacenters:
            token = vm_util._get_token(datacenters)
            for obj_content in datacenters.objects:
                for datastore in obj_content.propSet[0].val[0]:
                    if datastore.value == datastore_ref.value and \
                       datastore._type == datastore_ref._type:
                        datacenter_ref = obj_content.obj
                        datacenter_name = obj_content.propSet[1].val
                        break
            if datacenter_ref:
                if token:
                    self._session._call_method(vim_util,
                                         "cancel_retrieve",
                                         token)
                return datacenter_ref, datacenter_name
            if token:
                datacenters = self._session._call_method(vim_util,
                                                           "continue_to_get_objects",
                                                           token)
            else:
                break                
        raise exception.DatacenterNotFound()
    
    def _get_host_ref_and_name(self, datastore_ref):
        """
        Get the host name and the reference from datastore.
        This gives the first hostmount. TODO: handle multiple host mounts
        """
        datastore_host_mounts = self._session._call_method(vim_util, "get_dynamic_property", datastore_ref, "Datastore", "host")
        for datastore_host_mount in datastore_host_mounts:
            host_ref =  datastore_host_mount[1][0].key
            host_name = self._session._call_method(vim_util, "get_dynamic_property", host_ref, "HostSystem", "name")
            return host_ref, host_name
        raise exception.HostNotFound()
             
                    

    def _get_vm_ref_from_name_folder(self, vmfolder_ref, name):
        obj_refs = self._session._call_method(vim_util, "get_dynamic_property", vmfolder_ref, "Folder", "childEntity")
        for obj_ref in obj_refs.ManagedObjectReference:
            if obj_ref._type != "VirtualMachine":
                continue
            vm_name = self._session._call_method(vim_util, "get_dynamic_property", obj_ref, "VirtualMachine", "name")
            if vm_name == name:
                return obj_ref
        raise exception.VMNotFound()
    
    def _get_vmfolder_ref_from_parent_folder(self, vmfolder_ref_parent, vmfolder_moid):
        vmfolder_refs = self._session._call_method(vim_util, "get_dynamic_property", vmfolder_ref_parent, "Folder", "childEntity")
        if not len(vmfolder_refs):
            return None
        for vmfolder_ref in vmfolder_refs.ManagedObjectReference:
            if vmfolder_ref.value == vmfolder_moid:
                return vmfolder_ref
            if vmfolder_ref._type == "Folder":
                result = self._get_vmfolder_ref_from_parent_folder(vmfolder_ref, vmfolder_moid)
                if result:
                    return result;
        return None 
        
    def _get_vmfolder_ref(self, datacenter_ref, vmfolder_moid = None):
        vmfolder_ref = self._session._call_method(vim_util, "get_dynamic_property", datacenter_ref, "Datacenter", "vmFolder")
        if vmfolder_moid == None or vmfolder_ref.value == vmfolder_moid:
            return vmfolder_ref
        result = self._get_vmfolder_ref_from_parent_folder(vmfolder_ref, vmfolder_moid)
        if result:
            return result
        else:
            raise exception.VMFolderNotFound()

    def _get_computeresource_host_ref(self, computeresource_moid):
        computeresource_ref = None
        computeresources = self._session._call_method(vim_util, "get_objects", "ComputeResource")
        while computeresources:
            token = vm_util._get_token(computeresources)
            for obj_content in computeresources.objects:
                if obj_content.obj.value == computeresource_moid:
                    computeresource_ref =  obj_content.obj
            if computeresource_ref:
                if token:
                    self._session._call_method(vim_util,
                                         "cancel_retrieve",
                                         token)
                return computeresource_ref, None
            if token:
                computeresources = self._session._call_method(vim_util,
                                                           "continue_to_get_objects",
                                                           token)
            else:
                break
        
        computeresources = self._session._call_method(vim_util, "get_objects", "ClusterComputeResource")
        while computeresources:
            token = vm_util._get_token(computeresources)
            for obj_content in computeresources.objects:
                if obj_content.obj.value == computeresource_moid:
                    computeresource_ref =  obj_content.obj
            if computeresource_ref:
                if token:
                    self._session._call_method(vim_util,
                                         "cancel_retrieve",
                                         token)
                return computeresource_ref, None
            if token:
                computeresources = self._session._call_method(vim_util,
                                                           "continue_to_get_objects",
                                                           token)
            else:
                break
        
        hosts = self._session._call_method(vim_util, "get_objects", "HostSystem")
        while hosts:
            token = vm_util._get_token(hosts)
            for obj_content in hosts.objects:
                if obj_content.obj.value == computeresource_moid:
                    host_ref =  obj_content.obj
                    computeresource_ref = self._session._call_method(vim_util, "get_dynamic_property", host_ref, "HostSystem", "parent")
            if computeresource_ref:
                if token:
                    self._session._call_method(vim_util,
                                         "cancel_retrieve",
                                         token)
                return computeresource_ref, host_ref
            if token:
                hosts = self._session._call_method(vim_util,
                                                   "continue_to_get_objects",
                                                   token)
            else:
                break                                
                
        raise exception.ResourcePoolNotFound()    
    
    def _get_res_pool_ref(self, resourcepool_moid):
        res_pool_ref = None
        resourcepools = self._session._call_method(vim_util, "get_objects", "ResourcePool")
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
    
    def _get_network_ref(self, network_moid, dc_ref):
        network_folder_ref = self._session._call_method(vim_util, "get_dynamic_property", dc_ref, "Datacenter", "networkFolder")
        network_refs = self._session._call_method(vim_util, "get_dynamic_property", network_folder_ref, "Folder", "childEntity")
        for network_ref in network_refs.ManagedObjectReference:
            if network_ref._type == "Network" or network_ref._type == "DistributedVirtualPortgroup":
                if network_ref.value == network_moid:
                    return network_ref
        raise exception.NetworkNotFound()     
    
    def _detach_disk_from_vm(self, vm_ref, instance, device, destroy_disk=False):
        """
        Detach disk from VM by reconfiguration.
        """
        instance_name = instance['name']
        instance_uuid = instance['uuid']
        client_factory = self._session._get_vim().client.factory
        vmdk_detach_config_spec = vm_util.get_vmdk_detach_config_spec(
                                    client_factory, device, destroy_disk)
        disk_key = device.key
        LOG.debug(_("Reconfiguring VM instance %(instance_name)s to detach "
                    "disk %(disk_key)s"),
                  {'instance_name': instance_name, 'disk_key': disk_key})
        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=vmdk_detach_config_spec)
        self._session._wait_for_task(instance_uuid, reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(instance_name)s to detach "
                    "disk %(disk_key)s"),
                  {'instance_name': instance_name, 'disk_key': disk_key})

    def _rebase_vmdk(self, base, orig_base, base_descriptor, base_monolithicsparse,
                            top, orig_top, top_descriptor, top_monolithicsparse):
        """
        rebase the top to base
        """
        if base_monolithicsparse == False:
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
 
    def _commit_vmdk(self, file_to_commit, commit_to, test):
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
        
    @autolog.log_method(Logger, 'vmwareapi.driver.pre_snapshot_vm')
    def pre_snapshot_vm(self, cntx, db, instance, snapshot):
        self.enable_cbt(cntx, db, instance)               
    
    @autolog.log_method(Logger, 'vmwareapi.driver.freeze_vm')
    def freeze_vm(self, cntx, db, instance, snapshot):
        pass     
    
    @autolog.log_method(Logger, 'vmwareapi.driver.thaw_vm')
    def thaw_vm(self, cntx, db, instance, snapshot):
        pass      
    
    @autolog.log_method(Logger, 'vmwareapi.driver.snapshot_delete')
    def snapshot_delete(self, cntx, db, snapshot): 
        
        def _remove_data():
            db.snapshot_update(cntx, snapshot.id, {'data_deleted':True})
            try:
                shutil.rmtree(vault.get_vault_service(cntx).get_snapshot_path({'workload_id': snapshot.workload_id,
                                                                               'snapshot_id': snapshot.id}))
            except Exception as ex:
                LOG.exception(ex)            
            
        db.snapshot_delete(cntx, snapshot.id)
        if snapshot.status == 'error':
            return _remove_data()
        try:
            snapshot_vm_resources = db.snapshot_resources_get(cntx, snapshot.id)
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type != 'disk':
                    continue
                if snapshot_vm_resource.status != 'deleted':
                    return
        except exception.SnapshotVMResourcesNotFound as ex:
            LOG.Exception(ex)
            return 
                   
        return _remove_data()
  
    
    @autolog.log_method(Logger, 'vmwareapi.driver.enable_cbt')
    def enable_cbt(self, cntx, db, instance):
        vm_ref = vm_util.get_vm_ref(self._session, {'uuid': instance['vm_id'],
                                                    'vm_name': instance['vm_name'],
                                                    'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                                    })

        # set the change block tracking for VM and for virtual disks
        # make this part of workload create so if there are outstanding
        # snapshots on any VM, we can error out
        if self._session._call_method(vim_util,"get_dynamic_property",
                                      vm_ref, "VirtualMachine", 
                                      "capability.changeTrackingSupported"):
            if not self._session._call_method(vim_util,"get_dynamic_property",
                                              vm_ref, "VirtualMachine", 
                                              "config.changeTrackingEnabled"):
                rootsnapshot = self._session._call_method(vim_util,"get_dynamic_property", vm_ref,
                                                          "VirtualMachine", "rootSnapshot")
                if not rootsnapshot:
                    client_factory = self._session._get_vim().client.factory
                    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
                    config_spec.changeTrackingEnabled = True
                    reconfig_task = self._session._call_method( self._session._get_vim(),
                                                                "ReconfigVM_Task", vm_ref,
                                                                spec=config_spec)
                    self._session._wait_for_task(instance['vm_metadata']['vmware_uuid'], reconfig_task)
                    if not self._session._call_method(vim_util,"get_dynamic_property",
                                                      vm_ref, "VirtualMachine", 
                                                      "config.changeTrackingEnabled"):
                        raise Exception(_("VM '%s(%s)' changeTracking is not enabled") %
                                          (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))
                else:
                    raise Exception(_("VM '%s(%s)' already has snapshots and "
                                      "enable change block tracking feature. "
                                      "Remove snapshots and create workload again") %
                                      (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))
        else:
            raise Exception(_("VM '%s(%s)' does not support changeTracking") %
                             (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))

    @autolog.log_method(Logger, 'vmwareapi.driver.snapshot_vm')
    def snapshot_vm(self, cntx, db, instance, snapshot):
        try:
            vm_ref = vm_util.get_vm_ref(self._session, {'uuid': instance['vm_id'],
                                                        'vm_name': instance['vm_name'],
                                                        'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                                        })
    
            # set the change block tracking for VM and for virtual disks
            # make this part of workload create so if there are outstanding
            # snapshots on any VM, we can error out
            if self._session._call_method(vim_util,"get_dynamic_property",
                                          vm_ref, "VirtualMachine", 
                                          "capability.changeTrackingSupported"):
                if not self._session._call_method(vim_util,"get_dynamic_property",
                                                  vm_ref, "VirtualMachine", 
                                                  "config.changeTrackingEnabled"):
                    raise Exception(_("VM '%s(%s)' does not have changeTracking enabled") %
                                     (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))
            else:
                raise Exception(_("VM '%s(%s)' does not support changeTracking") %
                                 (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))
            
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
            datastores = self._session._call_method(vim_util,"get_dynamic_property", vm_ref,
                                                        "VirtualMachine", "datastore")
            for datastore in datastores[0]:
                name = self._session._call_method(vim_util,"get_dynamic_property", datastore,
                                       "Datastore", "name")
                if name == datastore_name:
                    datastore_ref = datastore
                    break
                
            vmx_file = {'vmx_file_path': vmx_file_path, 
                        'datastore_name': datastore_name,
                        'datastore_ref' : datastore_ref,
                        'vmx_file_name': vmx_file_name}
                    
            snapshot_task = self._session._call_method(
                        self._session._get_vim(),
                        "CreateSnapshot_Task", vm_ref,
                        name="snapshot_id:%s" % snapshot['id'],
                        description="TrilioVault VAST Snapshot",
                        memory=False,
                        quiesce=True)
            task_info = self._session._wait_for_task(instance['vm_id'], snapshot_task)
            snapshot_ref = task_info.result
            snapshot_data = {'disks' : disks, 'vmx_file' : vmx_file}
            hardware = self._session._call_method(vim_util,"get_dynamic_property", snapshot_ref,
                                                  "VirtualMachineSnapshot", "config.hardware")
            snapshot_devices = []
            for device in hardware.device:
                if device.__class__.__name__ == "VirtualDisk":
                    backing = device.backing
                    if backing.__class__.__name__ == "VirtualDiskFlatVer1BackingInfo" or \
                       backing.__class__.__name__ == "VirtualDiskFlatVer2BackingInfo" or \
                       backing.__class__.__name__ == "VirtualDiskSparseVer1BackingInfo" or \
                       backing.__class__.__name__ == "VirtualDiskSparseVer2BackingInfo" :
                        if not 'capacityInBytes' in device:
                            device['capacityInBytes'] = device.capacityInKB * 1024
                        snapshot_devices.append(device) 
                
            snapshot_data['snapshot_devices'] = snapshot_devices
            snapshot_data['snapshot_ref'] = snapshot_ref
            snapshot_data['vm_ref'] = vm_ref
            return snapshot_data
        except Exception as ex:
            LOG.exception(ex)      
            raise  


    @autolog.log_method(Logger, 'vmwareapi.driver.get_parent_changeId')
    def get_parent_changeId(self, cntx, db, workload_id, vm_id, resource_pit_id):
        try:
            snapshots = db.snapshot_get_all_by_project_workload(cntx, cntx.project_id, workload_id)
            for snapshot in snapshots:
                if snapshot.status != "available":
                    continue
                snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_pit_id(cntx, vm_id, snapshot.id, resource_pit_id)
                return db.get_metadata_value(snapshot_vm_resource.metadata, 'changeId', default='*')                
            return '*'
        except Exception as ex:
            LOG.exception(ex)
            return '*'
        
 
    @autolog.log_method(Logger, 'vmwareapi.driver.get_vm_disk_resource_snap_backing')
    def get_vm_disk_resource_snap_backing(self, cntx, db, workload_id, vm_id, resource_pit_id):
        try: 
            snapshots = db.snapshot_get_all_by_project_workload(cntx, cntx.project_id, workload_id)
            for snapshot in snapshots:
                if snapshot.status != "available":
                    continue
                snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_pit_id(cntx, vm_id, snapshot.id, resource_pit_id)
                return db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
            return None
        except Exception as ex:
            LOG.exception(ex)
            return None
        
    @autolog.log_method(Logger, 'vmwareapi.driver.get_vmdk_snap_size')
    def get_vmdk_snap_size(self, cntx, db, instance, snapshot, snapshot_data, dev): 
        try:
            snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
            vmdk_snap_size = 0
            for idx, dev in enumerate(snapshot_data['snapshot_devices']):
                if snapshot_obj.snapshot_type == 'full':
                    changeId = '*'  
                else:              
                    changeId = self.get_parent_changeId(cntx, db, 
                                                        snapshot['workload_id'],
                                                        instance['vm_id'], 
                                                        dev.backing.uuid)
                position = 0
                while position < dev.capacityInBytes:
                    changes = self._session._call_method(self._session._get_vim(),
                                                         "QueryChangedDiskAreas", snapshot_data['vm_ref'],
                                                         snapshot=snapshot_data['snapshot_ref'],
                                                         deviceKey=dev['key'],
                                                         startOffset=position,
                                                         changeId=changeId)
               
                    if 'changedArea' in changes:
                        for change in changes.changedArea:
                            vmdk_snap_size += change.length
    
                    position = changes.startOffset + changes.length;
                        
            return vmdk_snap_size 
        except Exception as ex:
            LOG.exception(ex)      
            raise                
            
    @autolog.log_method(Logger, 'vmwareapi.driver.get_snapshot_data_size')
    def get_snapshot_data_size(self, cntx, db, instance, snapshot, snapshot_data): 
        vm_data_size = 0
        for idx, dev in enumerate(snapshot_data['snapshot_devices']):
            vm_data_size += self.get_vmdk_snap_size(cntx, db, instance, snapshot, snapshot_data, dev)
        return vm_data_size            

    @autolog.log_method(Logger, 'vmwareapi.driver.get_snapshot_disk_info')
    def get_snapshot_disk_info(self, cntx, db, instance, snapshot, snapshot_data): 
        return snapshot_data
    
    @autolog.log_method(Logger, 'vmwareapi.driver..upload_snapshot')
    def upload_snapshot(self, cntx, db, instance, snapshot, snapshot_data):
        
        def _upload_vmdk(dev):
            try:
                snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
                if snapshot_obj.snapshot_type == 'full':
                    changeId = '*'
                else:
                    changeId = self.get_parent_changeId( cntx, db, 
                                                         snapshot['workload_id'],
                                                         instance['vm_id'], 
                                                         dev.backing.uuid)
    
                vmdk_snap_size = self.get_vmdk_snap_size(cntx, db, instance, snapshot, snapshot_data, dev)
                vm_disk_resource_snap_backing = self.get_vm_disk_resource_snap_backing( cntx, db, 
                                                                                        snapshot['workload_id'],
                                                                                        instance['vm_id'], 
                                                                                        dev.backing.uuid)
                if vm_disk_resource_snap_backing:
                    vm_disk_resource_snap_backing_id = vm_disk_resource_snap_backing.id
                else:
                    vm_disk_resource_snap_backing_id = None
                
                # create an entry in the vm_disk_resource_snaps table
                vm_disk_resource_snap_id = str(uuid.uuid4())
                vm_disk_resource_snap_metadata = {} # Dictionary to hold the metadata
                vm_disk_resource_snap_metadata.setdefault('disk_format','vmdk')
                vm_disk_resource_snap_metadata.setdefault('vmware_disktype','thin')
                vm_disk_resource_snap_metadata.setdefault('vmware_adaptertype','lsiLogic')
                
                vm_disk_resource_snap_values = { 'id': vm_disk_resource_snap_id,
                                                 'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                 'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                                                 'metadata': vm_disk_resource_snap_metadata,       
                                                 'top': True,
                                                 'size': vmdk_snap_size,                                             
                                                 'status': 'creating'}     
                                                     
                vm_disk_resource_snap = db.vm_disk_resource_snap_create(cntx, vm_disk_resource_snap_values) 
        
                vault_metadata = {'workload_id': snapshot['workload_id'],
                                  'snapshot_id': snapshot['id'],
                                  'snapshot_vm_id': instance['vm_id'],
                                  'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                  'resource_name':  dev.deviceInfo.label,
                                  'vm_disk_resource_snap_id' : vm_disk_resource_snap_id,}
                
                db.snapshot_update( cntx, snapshot['id'], 
                                    {'progress_msg': 'Uploading '+ dev.deviceInfo.label + ' of VM:' + instance['vm_name'],
                                     'status': 'uploading'
                                    })            
                copy_to_file_path = vault_service.get_snapshot_file_path(vault_metadata) 
                head, tail = os.path.split(copy_to_file_path)
                fileutils.ensure_tree(head)
    
                vmxspec = 'moref=' + snapshot_data['vm_ref'].value
                vix_disk_lib_env = os.environ.copy()
                vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                # Create empty vmdk file
                try:
                    cmdline = "trilio-vix-disk-cli -create " 
                    cmdline += "-cap " + str(dev.capacityInBytes / (1024 * 1024))
                    cmdline += " " + copy_to_file_path
                    check_output(cmdline.split(" "), stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                except subprocess.CalledProcessError as ex:
                    LOG.debug(_("cmd: %s resulted in error: %s") %(cmdline, ex.output))
                    LOG.exception(ex)
                    raise
            
                totalBytesToTransfer = 0
                with open(copy_to_file_path + "-ctk", 'w') as ctkfile:
                    position = 0
                    while position < dev.capacityInBytes:
                        changes = self._session._call_method(
                                                        self._session._get_vim(),
                                                        "QueryChangedDiskAreas", snapshot_data['vm_ref'],
                                                        snapshot=snapshot_data['snapshot_ref'],
                                                        deviceKey=dev.key,
                                                        startOffset=position,
                                                        changeId=changeId)
                   
                        if 'changedArea' in changes:
                            for extent in changes.changedArea:
                                start = extent.start
                                length = extent.length
                                
                                ctkfile.write(str(start) + "," + str(length)+"\n")
                                totalBytesToTransfer += length
                        position = changes.startOffset + changes.length;
                """
                                chunksize = 64 * 1024 * 1024 
                                for chunkstart in xrange(start, start+length, chunksize):
                                    if chunkstart + chunksize > start + length:
                                        chunk = start + length - chunkstart
                                    else:
                                        chunk = chunksize 
                                    try:            
                                        cmdline = "trilio-vix-disk-cli -download".split(" ")
                                        cmdline.append(str(dev.backing.fileName))
                                        cmdline += ("-start " + str(chunkstart/512)).split(" ")
                                        cmdline += ("-count " + str(chunk/512)).split(" ")
                                        cmdline += ['-host', self._session._host_ip,]
                                        cmdline += ['-user', self._session._host_username,]
                                        cmdline += ['-password', self._session._host_password,]
                                        cmdline += ['-vm', vmxspec,]
                                        cmdline.append(copy_to_file_path)
                                        check_output(cmdline, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                                        snapshot_obj = db.snapshot_update(cntx, snapshot['id'], {'uploaded_size_incremental': chunk})
                                    except subprocess.CalledProcessError as ex:
                                        for idx, opt in enumerate(cmdline):
                                            if opt == "-password":
                                                cmdline[idx+1] = "***********"
                                                break
                                        LOG.debug(_("cmd: %s resulted in error: %s") %(" ".join(cmdline), ex.output))
                                        LOG.exception(ex)
                                        raise                            
                            
                """
                cmdspec = ["trilio-vix-disk-cli", "-downloadextents",
                           str(dev.backing.fileName),
                           "-extentfile", copy_to_file_path + "-ctk",
                           "-host", self._session._host_ip,
                           "-user", self._session._host_username,
                           "-password", "***********",
                           "-vm", vmxspec,
                           copy_to_file_path]
                cmd = " ".join(cmdspec)
                for idx, opt in enumerate(cmdspec):
                    if opt == "-password":
                        cmdspec[idx+1] = self._session._host_password
                        break

                process = subprocess.Popen(cmdspec,
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       bufsize= -1,
                                       env=vix_disk_lib_env,
                                       close_fds=True,
                                       shell=False)
                
                queue = Queue()
                read_thread = Thread(target=enqueue_output, args=(process.stdout, queue))
                read_thread.daemon = True # thread dies with the program
                read_thread.start()            
                
                uploaded_size = 0
                uploaded_size_incremental = 0
                previous_uploaded_size = 0
                while process.poll() is None:
                    try:
                        try:
                            output = queue.get(timeout=5)
                        except Empty:
                            continue 
                        except Exception as ex:
                            LOG.exception(ex)
                        totalbytes = int(re.search(r'\d+ Done',output).group().split(" ")[0])
                        uploaded_size_incremental = totalbytes - previous_uploaded_size
                        uploaded_size = totalbytes
                        snapshot_obj = db.snapshot_update(cntx, snapshot['id'], {'uploaded_size_incremental': uploaded_size_incremental})
                        previous_uploaded_size = uploaded_size                        
                    except Exception as ex:
                        LOG.exception(ex)
                
                process.stdin.close()
                _returncode = process.returncode  # pylint: disable=E1101
                if _returncode:
                    LOG.debug(_('Result was %s') % _returncode)
                    raise exception.ProcessExecutionError(
                            exit_code=_returncode,
                            stdout=output,
                            stderr=process.stderr.read(),
                            cmd=cmd)

                snapshot_obj = db.snapshot_update(cntx, snapshot['id'], {'uploaded_size_incremental': (totalBytesToTransfer - uploaded_size)})
                """
                try:            
                    cmdline = "trilio-vix-disk-cli -downloadextents".split(" ")
                    cmdline.append(str(dev.backing.fileName))
                    cmdline += ("-extentfile " + copy_to_file_path + "-ctk").split(" ")
                    cmdline += ['-host', self._session._host_ip,]
                    cmdline += ['-user', self._session._host_username,]
                    cmdline += ['-password', self._session._host_password,]
                    cmdline += ['-vm', vmxspec,]
                    cmdline.append(copy_to_file_path)
                    check_output(cmdline, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                    snapshot_obj = db.snapshot_update(cntx, snapshot['id'], {'uploaded_size_incremental': 100})
                except subprocess.CalledProcessError as ex:
                    for idx, opt in enumerate(cmdline):
                        if opt == "-password":
                            cmdline[idx+1] = "***********"
                            break
                    LOG.debug(_("cmd: %s resulted in error: %s") %(" ".join(cmdline), ex.output))
                    LOG.exception(ex)
                    raise                            
                """

                LOG.debug(_("snapshot_size: %(snapshot_size)s") %{'snapshot_size': snapshot_obj.size,})
                LOG.debug(_("uploaded_size: %(uploaded_size)s") %{'uploaded_size': snapshot_obj.uploaded_size,})
                LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': snapshot_obj.progress_percent,})
                    
                db.snapshot_update( cntx, snapshot['id'], 
                                    {'progress_msg': 'Uploaded '+ dev.deviceInfo.label + ' of VM:' + instance['vm_name'],
                                     'status': 'uploading'
                                    })
    
                # update the entry in the vm_disk_resource_snap table
                vm_disk_resource_snap_values = {'vault_service_url' : copy_to_file_path,
                                                'vault_service_metadata' : 'None',
                                                'finished_at' : timeutils.utcnow(),
                                                'status': 'available'}
                vm_disk_resource_snap = db.vm_disk_resource_snap_update(cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
                snapshot_type = 'full' if changeId == '*' else 'incremental'
                return vmdk_snap_size, snapshot_type            
                # END of inner function _upload_vmdk
            except Exception as ex:
                LOG.exception(ex)      
                raise 
        try:
            snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
            vault_service = vault.get_vault_service(cntx)
            # make sure the session cookies are upto data by calling the following api
            datacenter_name = self._get_datacenter_ref_and_name(snapshot_data['vmx_file']['datastore_ref'])[1]
            cookies = self._session._get_vim().client.options.transport.cookiejar
            #vmx file 
            vmx_file_handle = read_write_util.VMwareHTTPReadFile(
                                                    self._session._host_ip,
                                                    self._get_datacenter_ref_and_name(snapshot_data['vmx_file']['datastore_ref'])[1],
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
                
            for idx, dev in enumerate(snapshot_data['snapshot_devices']):
                vm_disk_size = 0
                disk = snapshot_data['disks'][idx]
    
                snapshot_vm_resource_metadata = {}
                snapshot_vm_resource_metadata['vmdk_controler_key'] = disk['vmdk_controler_key']
                snapshot_vm_resource_metadata['adapter_type'] = disk['adapter_type']
                snapshot_vm_resource_metadata['label'] = disk['label']
                snapshot_vm_resource_metadata['unit_number'] = disk['unit_number']
                snapshot_vm_resource_metadata['disk_type'] = disk['disk_type']
                snapshot_vm_resource_metadata['capacityInKB'] = disk['capacityInKB']
                snapshot_vm_resource_metadata['changeId'] = dev.backing.changeId
                
                snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                               'vm_id': instance['vm_id'],
                                               'snapshot_id': snapshot_obj.id,       
                                               'resource_type': 'disk',
                                               'resource_name':  disk['label'],
                                               'resource_pit_id': dev.backing.uuid,
                                               'metadata': snapshot_vm_resource_metadata,
                                               'status': 'creating'
                                              }
        
                snapshot_vm_resource = db.snapshot_vm_resource_create(cntx, snapshot_vm_resource_values)                                                
                vmdk_size, snapshot_type = _upload_vmdk(dev)
                snapshot_vm_resource = db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, {'status': 'available', 
                                                                                                      'size': vmdk_size,
                                                                                                      'snapshot_type': snapshot_type,
                                                                                                      'finished_at' : timeutils.utcnow()})

        except Exception as ex:
            LOG.exception(ex)      
            raise 
                    
    @autolog.log_method(Logger, 'vmwareapi.driver.remove_snapshot_vm')
    def remove_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_ref): 
        try:
            vm_ref = vm_util.get_vm_ref(self._session, {'uuid': instance['vm_id'],
                                                        'vm_name': instance['vm_name'],
                                                        'vmware_uuid':instance['vm_metadata']['vmware_uuid'],
                                                       })
    
            remove_snapshot_task = self._session._call_method(
                                                self._session._get_vim(),
                                                "RemoveSnapshot_Task", snapshot_ref,
                                                removeChildren=False)
            self._session._wait_for_task(instance['vm_id'], remove_snapshot_task)
        except Exception as ex:
            LOG.exception(ex)      
            raise         

    @autolog.log_method(Logger, 'vmwareapi.driver.apply_retention_policy')
    def apply_retention_policy(self, cntx, db,  instances, snapshot): 
        
        def _get_child_vm_disk_resource_snap(snap_chain, vm_disk_resource_snap_backing):
            try:
                for snap in snap_chain:
                    snapshot_vm_resources = db.snapshot_resources_get(cntx, snap.id)
                    for snapshot_vm_resource in snapshot_vm_resources:
                        if snapshot_vm_resource.resource_type != 'disk':
                            continue
                        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
                        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id == vm_disk_resource_snap_backing.id:
                            return vm_disk_resource_snap                
            except Exception as ex:
                LOG.exception(ex)      
                raise
            
        def _snapshot_disks_deleted(snap):
            try:
                snapshot_vm_resources = db.snapshot_resources_get(cntx, snap.id)
                for snapshot_vm_resource in snapshot_vm_resources:
                    if snapshot_vm_resource.resource_type != 'disk':
                        continue
                    if snapshot_vm_resource.status != 'deleted':
                        return False
                return True                 
            except exception.SnapshotVMResourcesNotFound as ex:
                LOG.Exception(ex)
                return True            

        def _snapshot_size_update(cntx, snap):
            try:
                snapshot_size = 0
                snapshot_vm_resources = db.snapshot_resources_get(cntx, snap.id)
                for snapshot_vm_resource in snapshot_vm_resources:
                    if snapshot_vm_resource.resource_type != 'disk':
                        continue
                    if snapshot_vm_resource.status != 'deleted':
                        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
                        disksize = os.path.getsize(vm_disk_resource_snap.vault_service_url)
                        db.vm_disk_resource_snap_update(cntx, vm_disk_resource_snap.id, {'size': disksize})
                        db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, {'size': disksize})
                        snapshot_size = snapshot_size + disksize
                db.snapshot_update(cntx, snap.id, {'size': snapshot_size,'uploaded_size': snapshot_size})
                return snapshot_size
            except exception.SnapshotVMResourcesNotFound as ex:
                LOG.Exception(ex)
            
                        
        try:
            db.snapshot_update( cntx, snapshot['id'],{'progress_msg': 'Applying retention policy','status': 'executing'})
            affected_snapshots = []             
            snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
            workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
            snapshots_to_keep = pickle.loads(str(workload_obj.jobschedule))['snapshots_to_keep']
            snapshots_to_keep['number'] = int(snapshots_to_keep['number'])
            snapshots_to_keep['days'] = int(snapshots_to_keep['days'])            
            #must retain at least one snapshot
            if snapshots_to_keep['number'] == 0:
                snapshots_to_keep['number'] = '1'
            #must retain at least one day snapshots
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
            snapshots_to_delete = []
            retained_snap_count = 0
            for idx, snap in enumerate(snapshots_valid):
                    if snapshots_to_keep['number'] == -1:
                        if (timeutils.utcnow() - snap.created_at).days <  snapshots_to_keep['days']:    
                            retained_snap_count = retained_snap_count + 1
                        else:
                            if snapshot_to_commit == None:
                                snapshot_to_commit = snapshots_valid[idx-1]
                            snapshots_to_delete.append(snap)
                    else:
                        if retained_snap_count < snapshots_to_keep['number']:
                            if snap.status == 'deleted':
                                continue                            
                            else:
                                retained_snap_count = retained_snap_count + 1
                        else:
                            if snapshot_to_commit == None:
                                snapshot_to_commit = snapshots_valid[idx-1]
                            snapshots_to_delete.append(snap)

            if snapshot_to_commit:
                vix_disk_lib_env = os.environ.copy()
                vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                affected_snapshots.append(snapshot_to_commit.id)
                for snap in snapshots_to_delete:
                    affected_snapshots.append(snap.id)
                    snapshot_to_commit = db.snapshot_get(cntx, snapshot_to_commit.id, read_deleted='yes')
                    if snapshot_to_commit.snapshot_type == 'full':
                        db.snapshot_delete(cntx, snap.id)
                        db.snapshot_update(cntx, snap.id, {'data_deleted':True})
                        try:
                            shutil.rmtree(vault.get_vault_service(cntx).get_snapshot_path({'workload_id': snap.workload_id, 'snapshot_id': snap.id}))
                        except Exception as ex:
                            LOG.exception(ex)    
                        continue
                    
                    snapshot_vm_resources = db.snapshot_resources_get(cntx, snapshot_to_commit.id)
                    for snapshot_vm_resource in snapshot_vm_resources:
                        if snapshot_vm_resource.resource_type != 'disk':
                            continue
                        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
                        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
                            vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(cntx, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                            with open(vm_disk_resource_snap_backing.vault_service_url + '-ctk', 'a') as backing_ctkfile:
                                with open(vm_disk_resource_snap.vault_service_url + "-ctk", 'r') as ctkfile:
                                    for line in ctkfile:
                                        start, length = line.split(',')
                                        start = int(start)
                                        length = int(length.rstrip('\n'))
                                        try:            
                                            cmdline = "trilio-vix-disk-cli -copy".split(" ")
                                            cmdline.append(vm_disk_resource_snap.vault_service_url)
                                            cmdline += ("-start " + str(start/512)).split(" ")
                                            cmdline += ("-count " + str(length/512)).split(" ")
                                            cmdline.append(vm_disk_resource_snap_backing.vault_service_url)
                                            check_output(cmdline, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                                        except subprocess.CalledProcessError as ex:
                                            LOG.debug(_("cmd: %s resulted in error: %s") %(" ".join(cmdline), ex.output))
                                            raise
                                        backing_ctkfile.write(str(start) + "," + str(length)+"\n")
    
                            try:            
                                cmdline = "vmware-vdiskmanager -R".split(" ")
                                cmdline.append(vm_disk_resource_snap_backing.vault_service_url)
                                check_output(cmdline, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                            except subprocess.CalledProcessError as ex:
                                LOG.debug(_("cmd: %s resulted in error: %s") %(" ".join(cmdline), ex.output))
                                raise
                            
                                        
                            os.remove(vm_disk_resource_snap.vault_service_url)
                            os.remove(vm_disk_resource_snap.vault_service_url + '-ctk')
                            shutil.move(vm_disk_resource_snap_backing.vault_service_url, vm_disk_resource_snap.vault_service_url)
                            shutil.move(vm_disk_resource_snap_backing.vault_service_url + '-ctk', vm_disk_resource_snap.vault_service_url + '-ctk')
                            vm_disk_resource_snap_values = {'size' : vm_disk_resource_snap_backing.size, 
                                                            'vm_disk_resource_snap_backing_id' : vm_disk_resource_snap_backing.vm_disk_resource_snap_backing_id}
                            db.vm_disk_resource_snap_update(cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
                            
                            snapshot_vm_resource_backing = db.snapshot_vm_resource_get(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                            snapshot_vm_resource_values = {'size' : snapshot_vm_resource_backing.size, 'snapshot_type' : snapshot_vm_resource_backing.snapshot_type }
                            db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, snapshot_vm_resource_values)
                            db.vm_disk_resource_snap_delete(cntx, vm_disk_resource_snap_backing.id)
                            db.snapshot_vm_resource_delete(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                            snapshot_vm_resource_backing = db.snapshot_vm_resource_get(cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                            if snapshot_vm_resource_backing.snapshot_id not in affected_snapshots:
                                affected_snapshots.append(snapshot_vm_resource_backing.snapshot_id)
                    
                    db.snapshot_type_update(cntx, snapshot_to_commit.id)
                    _snapshot_size_update(cntx, snapshot_to_commit)
    
                    if _snapshot_disks_deleted(snap):
                        db.snapshot_delete(cntx, snap.id)
                        db.snapshot_update(cntx, snap.id, {'data_deleted':True})
                        try:
                            shutil.rmtree(vault.get_vault_service(cntx).get_snapshot_path({'workload_id': snap.workload_id,
                                                                                           'snapshot_id': snap.id}))
                        except Exception as ex:
                            LOG.exception(ex)
                        
            # Upload snapshot metadata to the vault
            for snapshot_id in affected_snapshots:
                vmtasks.UploadSnapshotDBEntry(cntx, snapshot_id)                                    
            
        except Exception as ex:
            LOG.exception(ex)
            db.snapshot_update( cntx, snapshot['id'], {'warning_msg': 'Failed to apply retention policy - ' + ex.message})
            #swallow the exception                  
                        
    @autolog.log_method(Logger, 'vmwareapi.driver.post_snapshot_vm')
    def post_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_data):
        try:
            self.remove_snapshot_vm(cntx, db, instance, snapshot, snapshot_data['snapshot_ref'])
        except Exception as ex:
            LOG.exception(ex)      
            raise                     
           
    @autolog.log_method(Logger, 'vmwareapi.driver.restore_vm')
    def restore_vm(self, cntx, db, instance, restore, restored_net_resources, restored_security_groups,
                   restored_compute_flavor, restored_nics, instance_options):    
        """
        Restores the specified instance from a snapshot
        """
        try:
            restore_obj = db.restore_get(cntx, restore['id'])
            snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
            instance['uuid']= instance_uuid = instance_options['id']
            if 'name' in instance_options and instance_options['name']: 
                instance['name']= instance_name = instance_options['name']
            else:
                instance['name']= instance_name = instance_options['name'] = instance['vm_name']
        
            msg = 'Creating VM ' + instance['vm_name'] + ' from snapshot ' + snapshot_obj.id  
            db.restore_update(cntx,  restore_obj.id, {'progress_msg': msg})
            
            ds = vm_util.get_datastore_ref_and_name(self._session, datastore_moid=instance_options['datastore']['moid'])
            client_factory = self._session._get_vim().client.factory
            service_content = self._session._get_vim().get_service_content()
            cookies = self._session._get_vim().client.options.transport.cookiejar
            datastore_ref = ds[0]
            datastore_name = ds[1]
            dc_info = self._get_datacenter_ref_and_name(datastore_ref)
            datacenter_ref = dc_info[0]
            datacenter_name = dc_info[1]
            
            vm_folder_name = restore['id'] + '-' + instance_options['name']
            vm_folder_name = vm_folder_name.replace(' ', '-')
            vm_folder_path = vm_util.build_datastore_path(datastore_name, vm_folder_name)
            self._mkdir(vm_folder_path, datacenter_ref)
        
            vault_service = vault.get_vault_service(cntx)
            snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'], snapshot_obj.id)
        
            """Restore vmx file"""
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type == 'vmx':
                    vmx_name = "%s/%s" % (vm_folder_name, os.path.basename(snapshot_vm_resource.resource_name))
                    url_compatible = vmx_name.replace(" ", "%20")
                    vmdk_write_file_handle = read_write_util.VMwareHTTPWriteFile(
                                            self._session._host_ip,
                                            datacenter_name,
                                            datastore_name,
                                            cookies,
                                            url_compatible,
                                            snapshot_vm_resource.size)
                    vmx_file_data =  db.get_metadata_value(snapshot_vm_resource.metadata,'vmx_file_data')              
                    vmdk_write_file_handle.write(vmx_file_data)
                    vmdk_write_file_handle.close()    
                    
            """Register VM on ESX host."""
            LOG.debug(_("Registering VM on the ESX host"))
            # Create the VM on the ESX host
            vm_folder_ref = None
            if 'vmfolder' in instance_options:
                if 'moid' in instance_options['vmfolder']:
                    vm_folder_ref = self._get_vmfolder_ref(datacenter_ref, instance_options['vmfolder']['moid'])
            if not vm_folder_ref:
                vm_folder_ref = self._get_vmfolder_ref(datacenter_ref)    
            
            
            resourcepool_ref = None
            computeresource_ref = None
            host_ref = None
            if 'resourcepool' in instance_options and \
               instance_options['resourcepool'] and \
               'moid' in instance_options['resourcepool'] and \
               instance_options['resourcepool']['moid']:
                resourcepool_ref = self._get_res_pool_ref(instance_options['resourcepool']['moid'])
            else:
                computeresource_ref, host_ref =  self._get_computeresource_host_ref(instance_options['computeresource']['moid'])
                resourcepool_ref = self._session._call_method(vim_util, "get_dynamic_property", computeresource_ref, 
                                                              computeresource_ref._type, "resourcePool")
                
            vmx_path = vm_util.build_datastore_path(datastore_name, vmx_name)
            try:
                vm_register_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "RegisterVM_Task", 
                                        vm_folder_ref,
                                        path=vmx_path,
                                        name=instance_options['name'],
                                        asTemplate=False,
                                        pool=resourcepool_ref,
                                        host=host_ref)
                self._session._wait_for_task(instance['uuid'], vm_register_task)
            except Exception as ex:
                instance_options['name'] = instance_options['name'] + '-' + str(uuid.uuid4())
                vm_register_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "RegisterVM_Task", 
                                        vm_folder_ref,
                                        path=vmx_path,
                                        name=instance_options['name'],
                                        asTemplate=False,
                                        pool=resourcepool_ref,
                                        host=host_ref)
                self._session._wait_for_task(instance['uuid'], vm_register_task)
    
            LOG.debug(_("Registered VM on the ESX host"))
            vm_ref = self._get_vm_ref_from_name_folder(vm_folder_ref, instance_options['name'])            
            hardware_devices = self._session._call_method(vim_util,"get_dynamic_property", vm_ref,
                                                          "VirtualMachine", "config.hardware.device")
            if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
                hardware_devices = hardware_devices.VirtualDevice
            
            for device in hardware_devices:
                if device.__class__.__name__ == "VirtualDisk":
                    self._detach_disk_from_vm(vm_ref, instance, device, destroy_disk=False)
            
                  
            for device in hardware_devices:
                if hasattr(device, 'backing') and device.backing:
                    new_network_ref = None
                    if device.backing.__class__.__name__ == "VirtualEthernetCardNetworkBackingInfo":
                        if 'networks' in instance_options and instance_options['networks']:
                            for network in instance_options['networks']:
                                if device.backing.deviceName == network['network_name']:
                                    new_network_ref = self._get_network_ref(network['new_network_moid'], datacenter_ref)
                                    break                   
                    elif device.backing.__class__.__name__ == "VirtualEthernetCardDistributedVirtualPortBackingInfo":
                        if 'networks' in instance_options and instance_options['networks']:
                            for network in instance_options['networks']:
                                if device.backing.port.portgroupKey == network['network_moid']:
                                    new_network_ref = self._get_network_ref(network['new_network_moid'], datacenter_ref)
                                    break
                    else:
                        continue  
                    if new_network_ref is None:
                        # We only get into this situaltion when the vmx network settings does 
                        # not match with mob of the VM. We run into this once
                        continue
                    if new_network_ref._type == "Network":
                        device.backing = client_factory.create('ns0:VirtualEthernetCardNetworkBackingInfo') 
                        device.backing.deviceName = network['new_network_name']
                        device.backing.network = new_network_ref
                    elif new_network_ref._type == "DistributedVirtualPortgroup":
                        dvportgroup_config = self._session._call_method(vim_util,"get_dynamic_property", new_network_ref,
                                                                        "DistributedVirtualPortgroup", "config")
                        dvswitch_uuid = self._session._call_method(vim_util,"get_dynamic_property", dvportgroup_config.distributedVirtualSwitch,
                                                                   "VmwareDistributedVirtualSwitch", "uuid")
                        device.backing = client_factory.create('ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo')
                        device.backing.port.portgroupKey = dvportgroup_config.key
                        device.backing.port.switchUuid = dvswitch_uuid
                        device.backing.port.portKey = None
                         
                    virtual_device_config_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
                    virtual_device_config_spec.device = device
                    virtual_device_config_spec.operation = "edit"
                    vm_config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
                    vm_config_spec.deviceChange = [virtual_device_config_spec]
                    LOG.debug(_("Reconfiguring VM instance %(instance_name)s for nic %(nic_label)s"),{'instance_name': instance_name, 'nic_label': device.deviceInfo.label})
                    reconfig_task = self._session._call_method( self._session._get_vim(),
                                                                "ReconfigVM_Task", vm_ref,
                                                                spec=vm_config_spec)
                    self._session._wait_for_task(instance_uuid, reconfig_task)
                    LOG.debug(_("Reconfigured VM instance %(instance_name)s for nic %(nic_label)s"),
                                {'instance_name': instance_name, 'nic_label': device.deviceInfo.label})
                            
            #restore, rebase, commit & upload
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type != 'disk':
                    continue
                vmdk_name = "%s/%s.vmdk" % (vm_folder_name, snapshot_vm_resource.resource_name.replace(' ', '-'))
                vmdk_path = vm_util.build_datastore_path(instance_options['datastore']['name'], vmdk_name)
                vmdk_create_spec = vm_util.get_vmdk_create_spec(client_factory,
                                                                db.get_metadata_value(snapshot_vm_resource.metadata,'capacityInKB'),  #vmdk_file_size_in_kb, 
                                                                db.get_metadata_value(snapshot_vm_resource.metadata,'adapter_type'),  #adapter_type,
                                                                'thin'   #disk_type
                                                                )
                vmdk_create_task = self._session._call_method(self._session._get_vim(),
                                                              "CreateVirtualDisk_Task",
                                                              service_content.virtualDiskManager,
                                                              name=vmdk_path,
                                                              datacenter=datacenter_ref,
                                                              spec=vmdk_create_spec)
                if vmdk_create_task == []:
                    vmdk_create_task = self._session._call_method(self._session._get_vim(),
                                                                  "CreateVirtualDisk_Task",
                                                                  service_content.virtualDiskManager,
                                                                  name=vmdk_path,
                                                                  datacenter=datacenter_ref,
                                                                  spec=vmdk_create_spec)
    
                self._session._wait_for_task(instance['uuid'], vmdk_create_task)
    
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
    
                LOG.debug('Uploading image and volumes of instance ' + instance['vm_name'] + ' from snapshot ' + snapshot_obj.id)        
                db.restore_update(cntx,  restore['id'], 
                                  {'progress_msg': 'Uploading image and volumes of instance ' + instance['vm_name'] + ' from snapshot ' + snapshot_obj.id,
                                   'status': 'uploading' 
                                  })
                
                vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
                vm_disk_resource_snap_chain = []
                vm_disk_resource_snap_chain.insert(0,vm_disk_resource_snap)
                vdr_snap_backing_id = vm_disk_resource_snap.vm_disk_resource_snap_backing_id
                while vdr_snap_backing_id:
                    vdr_snap = db.vm_disk_resource_snap_get(cntx, vdr_snap_backing_id)
                    vm_disk_resource_snap_chain.insert(0, vdr_snap)
                    vdr_snap_backing_id = vdr_snap.vm_disk_resource_snap_backing_id
                
                vix_disk_lib_env = os.environ.copy()
                vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                vmxspec = 'moref=' + vm_ref.value                
                for vdr_snap in vm_disk_resource_snap_chain:
                    cmdspec = ["trilio-vix-disk-cli", "-uploadextents",
                               vdr_snap.vault_service_url,
                               "-extentfile", vdr_snap.vault_service_url + "-ctk",
                               "-host", self._session._host_ip,
                               "-user", self._session._host_username,
                               "-password", "***********",
                               "-vm", vmxspec,
                               vmdk_path, ]
                    cmd = " ".join(cmdspec)
                    for idx, opt in enumerate(cmdspec):
                        if opt == "-password":
                            cmdspec[idx+1] = self._session._host_password
                            break

                    process = subprocess.Popen(cmdspec,
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,
                                           bufsize= -1,
                                           env=vix_disk_lib_env,
                                           close_fds=True,
                                           shell=False)
                
                    queue = Queue()
                    read_thread = Thread(target=enqueue_output, args=(process.stdout, queue))
                    read_thread.daemon = True # thread dies with the program
                    read_thread.start()            
                
                    uploaded_size = 0
                    uploaded_size_incremental = 0
                    previous_uploaded_size = 0
                    while process.poll() is None:
                        try:
                            try:
                                output = queue.get(timeout=5)
                            except Empty:
                                continue 
                            except Exception as ex:
                                LOG.exception(ex)
                            totalbytes = int(re.search(r'\d+ Done',output).group().split(" ")[0])
                            uploaded_size_incremental = totalbytes - previous_uploaded_size
                            uploaded_size = totalbytes
                            restore_obj = db.restore_update(cntx, restore['id'], {'uploaded_size_incremental': uploaded_size_incremental})
                            previous_uploaded_size = uploaded_size                        
                        except Exception as ex:
                            LOG.exception(ex)
                
                    process.stdin.close()
                    _returncode = process.returncode  # pylint: disable=E1101
                    if _returncode:
                        LOG.debug(_('Result was %s') % _returncode)
                        raise exception.ProcessExecutionError(
                                exit_code=_returncode,
                                stdout=output,
                                stderr=process.stderr.read(),
                                cmd=cmd)
    
                restore_obj = db.restore_get(cntx, restore['id'])
                progress = "{message_color} {message} {progress_percent} {normal_color}".format(**{
                    'message_color': autolog.BROWN,
                    'message': "Restore Progress: ",
                    'progress_percent': str(restore_obj.progress_percent),
                    'normal_color': autolog.NORMAL,
                    }) 
                LOG.debug( progress)    
                # End of for loop for devices
    
            restored_instance_id = self._session._call_method(vim_util,"get_dynamic_property", vm_ref,
                                                              "VirtualMachine", "config.instanceUuid")
            
            restored_instance_name =  instance_options['name']                                                
            restored_vm_values = {'vm_id': restored_instance_id,
                                  'vm_name':  restored_instance_name,    
                                  'restore_id': restore_obj.id,
                                  'status': 'available'}
            restored_vm = db.restored_vm_create(cntx,restored_vm_values)
            
            if 'power' in instance_options and \
               instance_options['power'] and \
               'state' in instance_options['power'] and \
               instance_options['power']['state'] and \
               instance_options['power']['state'] =='on':
                db.restore_update(cntx,restore_obj.id, {'progress_msg': 'Powering on VM ' + instance['vm_name'],'status': 'executing'})        
                self.power_on(vm_ref, instance)
            
            
            
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
                              {'progress_msg': 'Created VM ' + instance['vm_name'] + ' from snapshot ' + snapshot_obj.id,
                               'status': 'executing'
                              })        

            return restored_vm
        except Exception as ex:
            LOG.exception(ex)      
            raise                   

class VMwareAPISession(object):
    """
    Sets up a session with the VC/ESX host and handles all
    the calls made to the host.
    """

    def __init__(self, host_ip=CONF.vmware.host_ip,
                 username=CONF.vmware.host_username,
                 password=CONF.vmware.host_password,
                 retry_count=CONF.vmware.api_retry_count,
                 scheme="https"):
        self._host_ip = host_ip
        self._host_username = username
        self._host_password = password
        self._api_retry_count = retry_count
        self._scheme = scheme
        self._session_id = None
        self.vim = None
        self._create_session()

    def _get_vim_object(self):
        """Create the VIM Object instance."""
        return vim.Vim(protocol=self._scheme, host=self._host_ip)

    def _create_session(self):
        """Creates a session with the VC/ESX host."""

        delay = 1

        while True:
            try:
                # Login and setup the session with the host for making
                # API calls
                self.vim = self._get_vim_object()
                session = self.vim.Login(
                               self.vim.get_service_content().sessionManager,
                               userName=self._host_username,
                               password=self._host_password)
                # Terminate the earlier session, if possible ( For the sake of
                # preserving sessions as there is a limit to the number of
                # sessions we can have )
                if self._session_id:
                    try:
                        self.vim.TerminateSession(
                                self.vim.get_service_content().sessionManager,
                                sessionId=[self._session_id])
                    except Exception as excep:
                        # This exception is something we can live with. It is
                        # just an extra caution on our side. The session may
                        # have been cleared. We could have made a call to
                        # SessionIsActive, but that is an overhead because we
                        # anyway would have to call TerminateSession.
                        LOG.debug(excep)
                self._session_id = session.key
                return
            except Exception as excep:
                LOG.critical(_("Unable to connect to server at %(server)s, "
                    "sleeping for %(seconds)s seconds"),
                    {'server': self._host_ip, 'seconds': delay})
                time.sleep(delay)
                delay = min(2 * delay, 60)

    def __del__(self):
        """Logs-out the session."""
        # Logout to avoid un-necessary increase in session count at the
        # ESX host
        try:
            # May not have been able to connect to VC, so vim is still None
            if self.vim is None:
                self.vim.Logout(self.vim.get_service_content().sessionManager)
        except Exception as excep:
            # It is just cautionary on our part to do a logout in del just
            # to ensure that the session is not left active.
            LOG.debug(excep)

    def _is_vim_object(self, module):
        """Check if the module is a VIM Object instance."""
        return isinstance(module, vim.Vim)

    def _call_method(self, module, method, *args, **kwargs):
        """
        Calls a method within the module specified with
        args provided.
        """
        args = list(args)
        retry_count = 0
        exc = None
        last_fault_list = []
        while True:
            try:
                if not self._is_vim_object(module):
                    # If it is not the first try, then get the latest
                    # vim object
                    if retry_count > 0:
                        args = args[1:]
                    args = [self.vim] + args
                retry_count += 1
                temp_module = module

                for method_elem in method.split("."):
                    temp_module = getattr(temp_module, method_elem)

                return temp_module(*args, **kwargs)
            except error_util.VimFaultException as excep:
                # If it is a Session Fault Exception, it may point
                # to a session gone bad. So we try re-creating a session
                # and then proceeding ahead with the call.
                exc = excep
                if error_util.FAULT_NOT_AUTHENTICATED in excep.fault_list:
                    # Because of the idle session returning an empty
                    # RetrievePropertiesResponse and also the same is returned
                    # when there is say empty answer to the query for
                    # VMs on the host ( as in no VMs on the host), we have no
                    # way to differentiate.
                    # So if the previous response was also am empty response
                    # and after creating a new session, we get the same empty
                    # response, then we are sure of the response being supposed
                    # to be empty.
                    if error_util.FAULT_NOT_AUTHENTICATED in last_fault_list:
                        return []
                    last_fault_list = excep.fault_list
                    self._create_session()
                else:
                    # No re-trying for errors for API call has gone through
                    # and is the caller's fault. Caller should handle these
                    # errors. e.g, InvalidArgument fault.
                    break
            except error_util.SessionOverLoadException as excep:
                # For exceptions which may come because of session overload,
                # we retry
                exc = excep
            except Exception as excep:
                # If it is a proper exception, say not having furnished
                # proper data in the SOAP call or the retry limit having
                # exceeded, we raise the exception
                exc = excep
                break
            # If retry count has been reached then break and
            # raise the exception
            if retry_count > self._api_retry_count:
                break
            time.sleep(TIME_BETWEEN_API_CALL_RETRIES)

        LOG.critical(_("In vmwareapi:_call_method, "
                     "got this exception: %s") % exc)
        raise

    def _get_vim(self):
        """Gets the VIM object reference."""
        if self.vim is None:
            self._create_session()
        return self.vim

    def _wait_for_task(self, instance_uuid, task_ref):
        """
        Return a Deferred that will give the result of the given task.
        The task is polled until it completes.
        """
        done = event.Event()
        loop = loopingcall.FixedIntervalLoopingCall(self._poll_task,
                                                    instance_uuid,
                                                    task_ref, done)
        loop.start(CONF.vmware.task_poll_interval)
        ret_val = done.wait()
        loop.stop()
        return ret_val

    def _poll_task(self, instance_uuid, task_ref, done):
        """
        Poll the given task, and fires the given Deferred if we
        get a result.
        """
        try:
            task_info = self._call_method(vim_util, "get_dynamic_property",
                            task_ref, "Task", "info")
            task_name = task_info.name
            if task_info.state in ['queued', 'running']:
                return
            elif task_info.state == 'success':
                LOG.debug(_("Task [%(task_name)s] %(task_ref)s "
                            "status: success"),
                          {'task_name': task_name, 'task_ref': task_ref})
                done.send(task_info)
            else:
                error_info = str(task_info.error.localizedMessage)
                LOG.warn(_("Task [%(task_name)s] %(task_ref)s "
                          "status: error %(error_info)s"),
                         {'task_name': task_name, 'task_ref': task_ref,
                          'error_info': error_info})
                done.send_exception(exception.WorkloadMgrException(error_info))
        except Exception as excep:
            LOG.warn(_("In vmwareapi:_poll_task, Got this error %s") % excep)
            done.send_exception(excep)
            

        
