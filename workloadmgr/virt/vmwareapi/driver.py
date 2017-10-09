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
import datetime
from os import remove, close
from Queue import Queue, Empty
from threading import Thread
from subprocess import call
from subprocess import check_call
from subprocess import check_output
from tempfile import mkstemp

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
from workloadmgr.virt.vmwareapi import volumeops
from workloadmgr.virt.vmwareapi import read_write_util
from workloadmgr.virt.vmwareapi.thickcopy import thickcopyextents
from workloadmgr.virt.vmwareapi import thickcopy
from workloadmgr.virt.vmwareapi import vmdkmount
from workloadmgr.vault import vault
from workloadmgr.virt import qemuimages
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import utils
from workloadmgr import exception
from workloadmgr import autolog
from workloadmgr import settings
from workloadmgr.workloads import workload_utils

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

    @autolog.log_method(Logger, 'VMwareESXDriver.__init__')
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

    @autolog.log_method(Logger, 'VMwareESXDriver.pause')
    def pause(self, cntx, db, instance):
        """Pause VM instance."""
        msg = _("pause not supported for vmwareapi")
        raise NotImplementedError(msg)

    @autolog.log_method(Logger, 'VMwareESXDriver.unpause')
    def unpause(self, cntx, db, instance):
        """Unpause paused VM instance."""
        msg = _("unpause not supported for vmwareapi")
        raise NotImplementedError(msg)

    @autolog.log_method(Logger, 'VMwareESXDriver.suspend')
    def suspend(self, cntx, db, instance):
        """Suspend the specified instance."""
        instance['uuid'] = instance['vm_id']
        vm_ref = vm_util.get_vm_ref(self._session,
                                    {'uuid': instance['vm_id'],
                                     'vm_name': instance['vm_name'],
                                        'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                     })

        pwr_state = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            vm_ref,
            "VirtualMachine",
            "runtime.powerState")
        # Only PoweredOn VMs can be suspended.
        if pwr_state == "poweredOn":
            LOG.info(_("Suspending the VM %s") % instance['vm_name'])
            suspend_task = self._session._call_method(self._session._get_vim(),
                                                      "SuspendVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], suspend_task)
            LOG.info(_("Suspended the VM %s") % instance['vm_name'])
        # Raise Exception if VM is poweredOff
        elif pwr_state == "poweredOff":
            LOG.info(_("%s is powered off and cannot be suspended. So returning "
                       "without doing anything") % instance['vm_name'])
        else:
            LOG.info(_("%s is already in suspended state. So returning "
                       "without doing anything") % instance['vm_name'])

    @autolog.log_method(Logger, 'VMwareESXDriver.resume')
    def resume(self, cntx, db, instance):
        """Resume the specified instance."""
        instance['uuid'] = instance['vm_id']
        vm_ref = vm_util.get_vm_ref(self._session,
                                    {'uuid': instance['vm_id'],
                                     'vm_name': instance['vm_name'],
                                        'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                     })

        pwr_state = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            vm_ref,
            "VirtualMachine",
            "runtime.powerState")
        if pwr_state.lower() == "suspended":
            LOG.info(_("Resuming the VM %s") % instance['vm_name'])
            suspend_task = self._session._call_method(
                self._session._get_vim(),
                "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], suspend_task)
            LOG.info(_("Resumed the VM %s") % instance['vm_name'])
        else:
            LOG.info(_("%s is not in suspended state. So returning "
                       "without doing anything") % instance['vm_name'])

    @autolog.log_method(Logger, 'VMwareESXDriver.power_off')
    def power_off(self, vm_ref, instance):
        """Power off the specified instance."""
        pwr_state = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            vm_ref,
            "VirtualMachine",
            "runtime.powerState")
        # Only PoweredOn VMs can be powered off.
        if pwr_state == "poweredOn":
            LOG.info(_("Powering off the VM %s") % instance['vm_name'])
            poweroff_task = self._session._call_method(
                self._session._get_vim(),
                "PowerOffVM_Task", vm_ref)
            self._session._wait_for_task(instance['uuid'], poweroff_task)
            LOG.info(_("Powered off the VM %s") % instance['vm_name'])
        # Raise Exception if VM is suspended
        elif pwr_state == "suspended":
            reason = _(
                instance['vm_name'] +
                " is suspended and cannot be powered off.")
            raise exception.InstancePowerOffFailure(reason=reason)
        else:
            LOG.info(_("%s is already in powered off state. So returning "
                       "without doing anything") % instance['vm_name'])

    @autolog.log_method(Logger, 'VMwareESXDriver.power_on')
    def power_on(self, vm_ref, instance):
        """Power on the specified instance."""
        pwr_state = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            vm_ref,
            "VirtualMachine",
            "runtime.powerState")
        if pwr_state == "poweredOn":
            LOG.info(_("%s is already in powered on state. So returning "
                       "without doing anything") % instance['vm_name'])
        # Only PoweredOff and Suspended VMs can be powered on.
        else:
            LOG.info(_("Powering on the VM %s") % instance['vm_name'])
            poweron_task = self._session._call_method(
                self._session._get_vim(),
                "PowerOnVM_Task", vm_ref)

            vmSummary = self._session._call_method(
                vim_util, "get_dynamic_property", vm_ref, "VirtualMachine", "summary")

            while vmSummary.runtime.powerState != "poweredOn":
                question_answered = False
                start = timeutils.utcnow()
                if hasattr(vmSummary.runtime,
                           'question') and vmSummary.runtime.question:
                    if "i copied it" in vmSummary.runtime.question.text.lower():
                        for choiceInfo in vmSummary.runtime.question.choice.choiceInfo:
                            if "copied" in choiceInfo.label.lower():
                                self._session._call_method(
                                    self._session._get_vim(),
                                    "AnswerVM",
                                    vm_ref,
                                    questionId=vmSummary.runtime.question.id,
                                    answerChoice=choiceInfo.key)
                                question_answered = True
                                break
                if question_answered:
                    break
                vmSummary = self._session._call_method(
                    vim_util, "get_dynamic_property", vm_ref, "VirtualMachine", "summary")
                end = timeutils.utcnow()
                delay = CONF.vmware.task_poll_interval - \
                    timeutils.delta_seconds(start, end)
                if delay <= 0:
                    LOG.warn(
                        _('timeout waiting for a question during poweron'))
                time.sleep(delay if delay > 0 else 0)

            self._session._wait_for_task(instance['uuid'], poweron_task)
            LOG.info(_("Powered on the VM %s") % instance['vm_name'])

    @autolog.log_method(Logger, 'VMwareESXDriver.get_host_ip_addr')
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

    @autolog.log_method(Logger, 'VMwareVCDriver.__init__')
    def __init__(self, virtapi, read_only=False, scheme="https"):
        super(VMwareVCDriver, self).__init__(virtapi)

        # Get the list of clusters to be used
        self._virtapi = virtapi

    @autolog.log_method(Logger, 'VMwareVCDriver._mkdir')
    def _mkdir(self, ds_path, datacenter_ref):
        """
        Creates a directory at the path specified. If it is just "NAME",
        then a directory with this name is created at the topmost level of the
        DataStore.
        """
        LOG.info(_("Creating directory with path %s") % ds_path)
        self._session._call_method(
            self._session._get_vim(),
            "MakeDirectory",
            self._session._get_vim().get_service_content().fileManager,
            name=ds_path,
            datacenter=datacenter_ref,
            createParentDirectories=False)
        LOG.info(_("Created directory with path %s") % ds_path)

    @autolog.log_method(
        Logger, 'VMwareVCDriver._get_values_from_object_properties')
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

    @autolog.log_method(Logger, 'VMwareVCDriver._replace_last')
    def _replace_last(self, source_string, replace_what, replace_with):
        head, sep, tail = source_string.rpartition(replace_what)
        return head + replace_with + tail

    @autolog.log_method(Logger, 'VMwareVCDriver._get_datacenter_ref_and_name')
    def _get_datacenter_ref_and_name(self, datastore_ref):
        """Get the datacenter name and the reference."""
        datacenter_ref = None
        datacenter_name = None

        datacenters = self._session._call_method(
            vim_util, "get_objects", "Datacenter", [
                "datastore", "name"])
        while datacenters:
            token = vm_util._get_token(datacenters)
            for obj_content in datacenters.objects:
                if obj_content.propSet[0].val == "":
                    continue
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
                datacenters = self._session._call_method(
                    vim_util, "continue_to_get_objects", token)
            else:
                break
        raise exception.DatacenterNotFound()

    @autolog.log_method(Logger, 'VMwareVCDriver._get_host_ref_and_name')
    def _get_host_ref_and_name(self, datastore_ref):
        """
        Get the host name and the reference from datastore.
        This gives the first hostmount. TODO: handle multiple host mounts
        """
        datastore_host_mounts = self._session._call_method(
            vim_util, "get_dynamic_property", datastore_ref, "Datastore", "host")
        for datastore_host_mount in datastore_host_mounts:
            host_ref = datastore_host_mount[1][0].key
            host_name = self._session._call_method(
                vim_util, "get_dynamic_property", host_ref, "HostSystem", "name")
            return host_ref, host_name
        raise exception.HostNotFound(host='none')

    @autolog.log_method(
        Logger, 'VMwareVCDriver._get_root_disk_path_from_vm_ref')
    def _get_root_disk_path_from_vm_ref(self, vm_ref):

        # Get the vmdk file name that the VM is pointing to
        virtual_disks = self._session._call_method(
            vim_util, "get_dynamic_property", vm_ref, "VirtualMachine", "layout.disk")
        return virtual_disks[0][0].diskFile[0]

    @autolog.log_method(Logger, 'VMwareVCDriver._get_vm_ref_from_name_folder')
    def _get_vm_ref_from_name_folder(self, vmfolder_ref, name):
        obj_refs = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            vmfolder_ref,
            "Folder",
            "childEntity")
        for obj_ref in obj_refs.ManagedObjectReference:
            if obj_ref._type != "VirtualMachine":
                continue
            vm_name = self._session._call_method(
                vim_util, "get_dynamic_property", obj_ref, "VirtualMachine", "name")
            if vm_name == name:
                return obj_ref
        raise exception.VMNotFound()

    @autolog.log_method(
        Logger, 'VMwareVCDriver._get_vmfolder_ref_from_parent_folder')
    def _get_vmfolder_ref_from_parent_folder(
            self, vmfolder_ref_parent, vmfolder_moid):
        vmfolder_refs = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            vmfolder_ref_parent,
            "Folder",
            "childEntity")
        if not len(vmfolder_refs):
            return None
        for vmfolder_ref in vmfolder_refs.ManagedObjectReference:
            if vmfolder_ref.value == vmfolder_moid:
                return vmfolder_ref
            if vmfolder_ref._type == "Folder":
                result = self._get_vmfolder_ref_from_parent_folder(
                    vmfolder_ref, vmfolder_moid)
                if result:
                    return result
        return None

    @autolog.log_method(Logger, 'VMwareVCDriver._get_vmfolder_ref')
    def _get_vmfolder_ref(self, datacenter_ref, vmfolder_moid=None):
        vmfolder_ref = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            datacenter_ref,
            "Datacenter",
            "vmFolder")
        if vmfolder_moid is None or vmfolder_ref.value == vmfolder_moid:
            return vmfolder_ref
        result = self._get_vmfolder_ref_from_parent_folder(
            vmfolder_ref, vmfolder_moid)
        if result:
            return result
        else:
            raise exception.VMFolderNotFound()

    @autolog.log_method(Logger, 'VMwareVCDriver._get_computeresource_host_ref')
    def _get_computeresource_host_ref(self, computeresource_moid):
        computeresource_ref = None
        computeresources = self._session._call_method(
            vim_util, "get_objects", "ComputeResource")
        while computeresources:
            token = vm_util._get_token(computeresources)
            for obj_content in computeresources.objects:
                if obj_content.obj.value == computeresource_moid:
                    computeresource_ref = obj_content.obj
            if computeresource_ref:
                if token:
                    self._session._call_method(vim_util,
                                               "cancel_retrieve",
                                               token)
                return computeresource_ref, None
            if token:
                computeresources = self._session._call_method(
                    vim_util, "continue_to_get_objects", token)
            else:
                break

        computeresources = self._session._call_method(
            vim_util, "get_objects", "ClusterComputeResource")
        while computeresources:
            token = vm_util._get_token(computeresources)
            for obj_content in computeresources.objects:
                if obj_content.obj.value == computeresource_moid:
                    computeresource_ref = obj_content.obj
            if computeresource_ref:
                if token:
                    self._session._call_method(vim_util,
                                               "cancel_retrieve",
                                               token)
                return computeresource_ref, None
            if token:
                computeresources = self._session._call_method(
                    vim_util, "continue_to_get_objects", token)
            else:
                break

        hosts = self._session._call_method(
            vim_util, "get_objects", "HostSystem")
        while hosts:
            token = vm_util._get_token(hosts)
            for obj_content in hosts.objects:
                if obj_content.obj.value == computeresource_moid:
                    host_ref = obj_content.obj
                    computeresource_ref = self._session._call_method(
                        vim_util, "get_dynamic_property", host_ref, "HostSystem", "parent")
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

    @autolog.log_method(Logger, 'VMwareVCDriver._get_res_pool_ref')
    def _get_res_pool_ref(self, resourcepool_moid):
        res_pool_ref = None
        resourcepools = self._session._call_method(
            vim_util, "get_objects", "ResourcePool")
        while resourcepools:
            token = vm_util._get_token(resourcepools)
            for obj_content in resourcepools.objects:
                if obj_content.obj.value == resourcepool_moid:
                    res_pool_ref = obj_content.obj
            if res_pool_ref:
                if token:
                    self._session._call_method(vim_util,
                                               "cancel_retrieve",
                                               token)
                return res_pool_ref
            if token:
                resourcepools = self._session._call_method(
                    vim_util, "continue_to_get_objects", token)
            else:
                break
        raise exception.ResourcePoolNotFound()

    @autolog.log_method(Logger, 'VMwareVCDriver._get_network_ref')
    def _get_network_ref(self, network_moid, dc_ref):
        network_folder_ref = self._session._call_method(
            vim_util, "get_dynamic_property", dc_ref, "Datacenter", "networkFolder")
        network_refs = self._session._call_method(
            vim_util,
            "get_dynamic_property",
            network_folder_ref,
            "Folder",
            "childEntity")
        for network_ref in network_refs.ManagedObjectReference:
            if network_ref._type == "Network" or network_ref._type == "DistributedVirtualPortgroup":
                if network_ref.value == network_moid:
                    return network_ref
        raise exception.NetworkNotFound()

    @autolog.log_method(Logger, 'VMwareVCDriver._detach_disk_from_vm')
    def _detach_disk_from_vm(self, vm_ref, instance,
                             device, destroy_disk=False):
        """
        Detach disk from VM by reconfiguration.
        """
        instance_name = instance['name']
        instance_uuid = instance['uuid']
        client_factory = self._session._get_vim().client.factory
        vmdk_detach_config_spec = vm_util.get_vmdk_detach_config_spec(
            client_factory, device, destroy_disk)
        disk_key = device.key
        LOG.info(_("Reconfiguring VM instance %(instance_name)s to detach "
                   "disk %(disk_key)s"), {'instance_name': instance_name, 'disk_key': disk_key})
        reconfig_task = self._session._call_method(
            self._session._get_vim(),
            "ReconfigVM_Task", vm_ref,
            spec=vmdk_detach_config_spec)
        self._session._wait_for_task(instance_uuid, reconfig_task)
        LOG.info(_("Reconfigured VM instance %(instance_name)s to detach "
                   "disk %(disk_key)s"), {'instance_name': instance_name, 'disk_key': disk_key})

    @autolog.log_method(Logger, 'VMwareVCDriver._adjust_vmdk_content_id')
    def _adjust_vmdk_content_id(self, base_vmdk, top_vmdk):
        try:
            cmdline = []
            cmdline.append('dd')
            cmdline.append('if=' + base_vmdk)
            cmdline.append('of=' + base_vmdk + '.des')
            cmdline.append('bs=1')
            cmdline.append('skip=512')
            cmdline.append('count=1024')
            check_output(cmdline, stderr=subprocess.STDOUT)
            with open(base_vmdk + '.des', "r") as base_descriptor_file:
                base_descriptor = base_descriptor_file.read()
            baseCID = re.search('\nCID=(\w+)', base_descriptor).group(1)
            os.remove(base_vmdk + '.des')

            cmdline = []
            cmdline.append('dd')
            cmdline.append('if=' + top_vmdk)
            cmdline.append('of=' + top_vmdk + '.des')
            cmdline.append('bs=1')
            cmdline.append('skip=512')
            cmdline.append('count=1024')
            check_output(cmdline, stderr=subprocess.STDOUT)
            with open(top_vmdk + '.des', "r") as top_descriptor_file:
                top_descriptor = top_descriptor_file.read()
            top_descriptor = re.sub(
                r'(parentCID=)(\w+)', "parentCID=%s" %
                baseCID, top_descriptor)
            with open(top_vmdk + '.des', "w") as top_descriptor_file:
                top_descriptor_file.write("%s" % top_descriptor)

            cmdline = []
            cmdline.append('dd')
            cmdline.append('conv=notrunc,nocreat')
            cmdline.append('if=' + top_vmdk + '.des')
            cmdline.append('of=' + top_vmdk)
            cmdline.append('bs=1')
            cmdline.append('seek=512')
            cmdline.append('count=1024')
            check_output(cmdline, stderr=subprocess.STDOUT)
            os.remove(top_vmdk + '.des')
        except subprocess.CalledProcessError as ex:
            LOG.critical(
                _("cmd: %s resulted in error: %s") %
                (" ".join(cmdline), ex.output))
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver._get_vmdk_content_id')
    def _get_vmdk_content_id(self, vmdk):
        try:
            cmdline = []
            cmdline.append('dd')
            cmdline.append('if=' + vmdk)
            cmdline.append('of=' + vmdk + '.des')
            cmdline.append('bs=1')
            cmdline.append('skip=512')
            cmdline.append('count=1024')
            check_output(cmdline, stderr=subprocess.STDOUT)
            with open(vmdk + '.des', "r") as descriptor_file:
                descriptor = descriptor_file.read()
            content_id = re.search('\nCID=(\w+)', descriptor).group(1)
            os.remove(vmdk + '.des')
            return content_id
        except subprocess.CalledProcessError as ex:
            LOG.critical(
                _("cmd: %s resulted in error: %s") %
                (" ".join(cmdline), ex.output))
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver._set_parent_content_id')
    def _set_parent_content_id(self, vmdk, content_id):
        try:
            cmdline = []
            cmdline.append('dd')
            cmdline.append('if=' + vmdk)
            cmdline.append('of=' + vmdk + '.des')
            cmdline.append('bs=1')
            cmdline.append('skip=512')
            cmdline.append('count=1024')
            check_output(cmdline, stderr=subprocess.STDOUT)
            with open(vmdk + '.des', "r") as descriptor_file:
                descriptor = descriptor_file.read()
            descriptor = re.sub(
                r'(parentCID=)(\w+)',
                "parentCID=%s" %
                content_id,
                descriptor)
            with open(vmdk + '.des', "w") as descriptor_file:
                descriptor_file.write("%s" % descriptor)

            cmdline = []
            cmdline.append('dd')
            cmdline.append('conv=notrunc,nocreat')
            cmdline.append('if=' + vmdk + '.des')
            cmdline.append('of=' + vmdk)
            cmdline.append('bs=1')
            cmdline.append('seek=512')
            cmdline.append('count=1024')
            check_output(cmdline, stderr=subprocess.STDOUT)
            os.remove(vmdk + '.des')
        except subprocess.CalledProcessError as ex:
            LOG.critical(
                _("cmd: %s resulted in error: %s") %
                (" ".join(cmdline), ex.output))
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver._rebase_vmdk')
    def _rebase_vmdk(
            self,
            base,
            orig_base,
            base_descriptor,
            base_monolithicsparse,
            top,
            orig_top,
            top_descriptor,
            top_monolithicsparse):
        """
        rebase the top to base
        """
        if not base_monolithicsparse:
            base_path, base_filename = os.path.split(base)
            orig_base_path, orig_base_filename = os.path.split(orig_base)
            base_extent_path = base_path
            base_extent_filename = base_filename + '.extent'
            if(os.path.isfile(os.path.join(base_extent_path, base_extent_filename)) == False):
                os.rename(
                    base,
                    os.path.join(
                        base_extent_path,
                        base_extent_filename))
                base_descriptor = base_descriptor.replace(
                    (' "' + orig_base_filename + '"'), (' "' + base_extent_filename + '"'))
                if top_descriptor is not None:
                    top_parentCID = re.search(
                        'parentCID=(\w+)', top_descriptor).group(1)
                    base_descriptor = re.sub(
                        r'(^CID=)(\w+)', "CID=%s" %
                        top_parentCID, base_descriptor)
                with open(base, "w") as base_descriptor_file:
                    base_descriptor_file.write("%s" % base_descriptor)

        if top_descriptor is not None:
            top_path, top_filename = os.path.split(top)
            orig_top_path, orig_top_filename = os.path.split(orig_top)
            top_extent_path = top_path
            top_extent_filename = top_filename + '.extent'
            if(os.path.isfile(os.path.join(top_extent_path, top_extent_filename))):
                with open(top, "r") as top_descriptor_file:
                    top_descriptor = top_descriptor_file.read()
            else:
                os.rename(
                    top,
                    os.path.join(
                        top_extent_path,
                        top_extent_filename))
                top_descriptor = top_descriptor.replace(
                    (' "' + orig_top_filename + '"'),
                    (' "' + top_extent_filename + '"'))

            top_descriptor = re.sub(
                r'parentFileNameHint="([^"]*)"',
                "parentFileNameHint=\"%s\"" %
                base,
                top_descriptor)
            with open(top, "w") as top_descriptor_file:
                top_descriptor_file.write("%s" % top_descriptor)

    @autolog.log_method(Logger, 'VMwareVCDriver._commit_vmdk')
    def _commit_vmdk(self, file_to_commit, commit_to, test):
        """rebase the backing_file_top to backing_file_base
         :param backing_file_top: top file to commit from to its base
        """
        # due to a bug in Nova VMware Driver (https://review.openstack.org/#/c/43994/) we will create a preallocated disk
        #utils.execute( 'vmware-vdiskmanager', '-r', file_to_commit, '-t 0',  commit_to, run_as_root=False)
        if test:
            utils.execute(
                'env',
                'LD_LIBRARY_PATH=/usr/lib/vmware-vix-disklib/lib64',
                'vmware-vdiskmanager',
                '-r',
                file_to_commit,
                '-t 2',
                commit_to,
                run_as_root=False)
        else:
            utils.execute(
                'env',
                'LD_LIBRARY_PATH=/usr/lib/vmware-vix-disklib/lib64',
                'vmware-vdiskmanager',
                '-r',
                file_to_commit,
                '-t 4',
                commit_to,
                run_as_root=False)

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

    @autolog.log_method(Logger, 'VMwareVCDriver._delete_datastore_file')
    def _delete_datastore_file(self, instance, datastore_path, dc_ref):
        LOG.debug(_("Deleting the datastore file %s") % datastore_path)
        vim = self._session._get_vim()
        file_delete_task = self._session._call_method(
            self._session._get_vim(),
            "DeleteDatastoreFile_Task",
            vim.get_service_content().fileManager,
            name=datastore_path,
            datacenter=dc_ref)
        self._session._wait_for_task(instance['uuid'],
                                     file_delete_task)
        LOG.debug(_("Deleted the datastore file %s") % datastore_path)

    @autolog.log_method(Logger, 'VMwareVCDriver.pre_snapshot_vm')
    def pre_snapshot_vm(self, cntx, db, instance, snapshot):
        db.snapshot_update(
            cntx, snapshot['id'], {
                'progress_msg': 'Enabling changed block tracking on ' + instance['vm_name']})
        self.enable_cbt(cntx, db, instance)

    @autolog.log_method(Logger, 'VMwareVCDriver.freeze_vm')
    def freeze_vm(self, cntx, db, instance, snapshot):
        pass

    @autolog.log_method(Logger, 'VMwareVCDriver.thaw_vm')
    def thaw_vm(self, cntx, db, instance, snapshot):
        pass

    @autolog.log_method(Logger, 'VMwareVCDriver.enable_cbt')
    def enable_cbt(self, cntx, db, instance):
        vm_ref = vm_util.get_vm_ref(self._session,
                                    {'uuid': instance['vm_id'],
                                     'vm_name': instance['vm_name'],
                                        'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                     })

        # set the change block tracking for VM and for virtual disks
        # make this part of workload create so if there are outstanding
        # snapshots on any VM, we can error out
        if self._session._call_method(vim_util, "get_dynamic_property",
                                      vm_ref, "VirtualMachine",
                                      "capability.changeTrackingSupported"):
            if not self._session._call_method(vim_util, "get_dynamic_property",
                                              vm_ref, "VirtualMachine",
                                              "config.changeTrackingEnabled"):
                rootsnapshot = self._session._call_method(
                    vim_util, "get_dynamic_property", vm_ref, "VirtualMachine", "rootSnapshot")
                if not rootsnapshot:
                    client_factory = self._session._get_vim().client.factory
                    config_spec = client_factory.create(
                        'ns0:VirtualMachineConfigSpec')
                    config_spec.changeTrackingEnabled = True
                    reconfig_task = self._session._call_method(
                        self._session._get_vim(), "ReconfigVM_Task", vm_ref, spec=config_spec)
                    self._session._wait_for_task(
                        instance['vm_metadata']['vmware_uuid'], reconfig_task)
                    if not self._session._call_method(
                        vim_util,
                        "get_dynamic_property",
                        vm_ref,
                        "VirtualMachine",
                            "config.changeTrackingEnabled"):
                        raise Exception(
                            _("VM '%s(%s)' changeTracking is not enabled") %
                            (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))
                else:
                    raise Exception(_("Since VM '%s(%s)' has existing snapshots, "
                                      "changed block tracking feature can't be enabled. "
                                      "Remove snapshots and try again") %
                                    (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))
        else:
            raise Exception(
                _("VM '%s(%s)' does not support changed block tracking") %
                (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))

    @autolog.log_method(Logger, 'VMwareVCDriver.snapshot_vm')
    def snapshot_vm(self, cntx, db, instance, snapshot):
        try:
            vm_ref = vm_util.get_vm_ref(self._session,
                                        {'uuid': instance['vm_id'],
                                         'vm_name': instance['vm_name'],
                                            'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                         })

            # set the change block tracking for VM and for virtual disks
            # make this part of workload create so if there are outstanding
            # snapshots on any VM, we can error out
            if self._session._call_method(
                vim_util,
                "get_dynamic_property",
                vm_ref,
                "VirtualMachine",
                    "capability.changeTrackingSupported"):
                if not self._session._call_method(
                    vim_util,
                    "get_dynamic_property",
                    vm_ref,
                    "VirtualMachine",
                        "config.changeTrackingEnabled"):
                    raise Exception(
                        _("VM '%s(%s)' does not have changeTracking enabled") %
                        (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))
            else:
                raise Exception(
                    _("VM '%s(%s)' does not support changeTracking") %
                    (instance['vm_name'], instance['vm_metadata']['vmware_uuid']))

            hardware_devices = self._session._call_method(
                vim_util,
                "get_dynamic_property",
                vm_ref,
                "VirtualMachine",
                "config.hardware.device")
            disks = vm_util.get_disks(hardware_devices)

            lst_properties = ["config.files.vmPathName", "runtime.powerState"]
            props = self._session._call_method(
                vim_util,
                "get_object_properties",
                None,
                vm_ref,
                "VirtualMachine",
                lst_properties)
            query = {'config.files.vmPathName': None}

            self._get_values_from_object_properties(props, query)
            vmx_file_path = query['config.files.vmPathName']
            if vmx_file_path:
                datastore_name, vmx_file_name = vm_util.split_datastore_path(
                    vmx_file_path)
            datastores = self._session._call_method(
                vim_util, "get_dynamic_property", vm_ref, "VirtualMachine", "datastore")
            for datastore in datastores[0]:
                name = self._session._call_method(
                    vim_util, "get_dynamic_property", datastore, "Datastore", "name")
                if name == datastore_name:
                    datastore_ref = datastore
                    break

            vmx_file = {'vmx_file_path': vmx_file_path,
                        'vmx_datastore_name': datastore_name,
                        'vmx_datastore_ref': datastore_ref,
                        'vmx_file_name': vmx_file_name}
            db.snapshot_update(
                cntx, snapshot['id'], {
                    'progress_msg': 'Creating Snapshot of Virtual Machine ' + instance['vm_name']})
            snapshot_task = self._session._call_method(
                self._session._get_vim(),
                "CreateSnapshot_Task", vm_ref,
                name="snapshot_id:%s" % snapshot['id'],
                description="TrilioVault VAST Snapshot",
                memory=False,
                quiesce=True)
            task_info = self._session._wait_for_task(
                instance['vm_id'], snapshot_task)
            snapshot_ref = task_info.result
            snapshot_data = {'disks': disks, 'vmx_file': vmx_file}
            hardware = self._session._call_method(
                vim_util,
                "get_dynamic_property",
                snapshot_ref,
                "VirtualMachineSnapshot",
                "config.hardware")
            snapshot_devices = []
            for device in hardware.device:
                if device.__class__.__name__ == "VirtualDisk":
                    backing = device.backing
                    if backing.__class__.__name__ == "VirtualDiskFlatVer1BackingInfo" or \
                       backing.__class__.__name__ == "VirtualDiskFlatVer2BackingInfo" or \
                       backing.__class__.__name__ == "VirtualDiskSparseVer1BackingInfo" or \
                       backing.__class__.__name__ == "VirtualDiskSparseVer2BackingInfo":
                        if 'capacityInBytes' not in device:
                            device['capacityInBytes'] = device.capacityInKB * 1024
                        snapshot_devices.append(device)

            snapshot_data['snapshot_devices'] = snapshot_devices
            snapshot_data['snapshot_ref'] = snapshot_ref
            snapshot_data['vm_ref'] = vm_ref
            return snapshot_data
        except Exception as ex:
            LOG.exception(ex)
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver.get_parent_changeId')
    def get_parent_changeId(self, cntx, db, workload_id,
                            vm_id, resource_pit_id):
        try:
            snapshots = db.snapshot_get_all_by_project_workload(
                cntx, cntx.project_id, workload_id)
            for snapshot in snapshots:
                if snapshot.status != "available":
                    continue
                snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_pit_id(
                    cntx, vm_id, snapshot.id, resource_pit_id)
                changeId = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'changeId', default='*')
                vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(
                    cntx, snapshot_vm_resource.id)
                content_id = db.get_metadata_value(
                    vm_disk_resource_snap.metadata, 'content_id', default='ffffffff')
                vault_path = vm_disk_resource_snap.vault_path
                return vault_path, changeId, content_id
            return None, '*', None
        except Exception as ex:
            LOG.exception(ex)
            return None, '*', None

    @autolog.log_method(Logger, 'VMwareVCDriver.get_top_vm_disk_resource_snap')
    def get_top_vm_disk_resource_snap(
            self, cntx, db, workload_id, vm_id, resource_pit_id):
        try:
            snapshots = db.snapshot_get_all_by_project_workload(
                cntx, cntx.project_id, workload_id)
            for snapshot in snapshots:
                if snapshot.status != "available":
                    continue
                snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_pit_id(
                    cntx, vm_id, snapshot.id, resource_pit_id)
                return db.vm_disk_resource_snap_get_top(
                    cntx, snapshot_vm_resource.id)
            return None
        except Exception as ex:
            LOG.exception(ex)
            return None

    @autolog.log_method(Logger, 'VMwareVCDriver.get_vmdk_snap_size')
    def get_vmdk_snap_size(self, cntx, db, instance,
                           snapshot, snapshot_data, dev):
        try:
            snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
            vmdk_snap_size = 0

            if snapshot_obj.snapshot_type == 'full':
                parent_changeId = '*'
            else:
                parent_vault_path, parent_changeId, parent_content_id = self.get_parent_changeId(
                    cntx, db, snapshot['workload_id'], instance['vm_id'], dev.backing.uuid)
            position = 0
            while position < dev.capacityInBytes:
                changes = self._session._call_method(
                    self._session._get_vim(),
                    "QueryChangedDiskAreas",
                    snapshot_data['vm_ref'],
                    snapshot=snapshot_data['snapshot_ref'],
                    deviceKey=dev['key'],
                    startOffset=position,
                    changeId=parent_changeId)
                if changes == []:
                    changes = self._session._call_method(
                        self._session._get_vim(),
                        "QueryChangedDiskAreas",
                        snapshot_data['vm_ref'],
                        snapshot=snapshot_data['snapshot_ref'],
                        deviceKey=dev['key'],
                        startOffset=position,
                        changeId=parent_changeId)

                if 'changedArea' in changes:
                    for change in changes.changedArea:
                        vmdk_snap_size += change.length

                position = changes.startOffset + changes.length

            return vmdk_snap_size
        except Exception as ex:
            LOG.exception(ex)
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver.get_snapshot_data_size')
    def get_snapshot_data_size(
            self, cntx, db, instance, snapshot, snapshot_data):
        snapshot_data['vm_data_size'] = 0
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])

        turbo_thick_disk_backup = settings.get_settings(
            cntx).get('turbo_thick_disk_backup', 'False')
        runthickcopy = False
        for idx, dev in enumerate(snapshot_data['snapshot_devices']):
            if snapshot_obj.snapshot_type == 'full':
                parent_vault_path = None
                parent_changeId = '*'
                parent_content_id = None
            else:
                parent_vault_path, parent_changeId, parent_content_id = self.get_parent_changeId(
                    cntx, db, snapshot['workload_id'], instance['vm_id'], dev.backing.uuid)
            dev['parent_vault_path'] = parent_vault_path
            dev['parent_changeId'] = parent_changeId
            dev['parent_content_id'] = parent_content_id

            if (not hasattr(dev.backing, 'thinProvisioned') or
                    not dev.backing.thinProvisioned) and \
                    dev['parent_changeId'] == '*':
                runthickcopy = True

            dev['disk_data_size'] = 0
            dev['extentsfile'] = None
            dev['totalblocks'] = 0

        if turbo_thick_disk_backup.lower() == 'true' and \
           runthickcopy:
            try:
                devicemap = []
                for idx, dev in enumerate(snapshot_data['snapshot_devices']):

                    vmxspec = 'moref=' + snapshot_data['vm_ref'].value
                    vix_disk_lib_env = os.environ.copy()
                    vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                    # Create empty vmdk file
                    fileh, copy_to_file_path = mkstemp()
                    close(fileh)
                    os.remove(copy_to_file_path)
                    try:
                        cmdline = "trilio-vix-disk-cli -create "
                        cmdline += "-cap " + \
                            str(dev.capacityInBytes / (1024 * 1024))
                        cmdline += " " + copy_to_file_path
                        check_output(
                            cmdline.split(" "),
                            stderr=subprocess.STDOUT,
                            env=vix_disk_lib_env)
                        devicemap.append(
                            {'dev': dev, 'localvmdkpath': copy_to_file_path})
                    except subprocess.CalledProcessError as ex:
                        LOG.critical(
                            _("cmd: %s resulted in error: %s") %
                            (cmdline, ex.output))
                        LOG.critical(_("fallback to cbt based upload"))
                        LOG.exception(ex)
                        raise

                extentsinfo = thickcopyextents(
                    self._session._host_ip,
                    self._session._host_username,
                    self._session._host_password,
                    vmxspec,
                    devicemap)
                if extentsinfo:
                    extentsfiles = extentsinfo['extentsfiles']
                    totalblocks = extentsinfo['totalblocks']
                    for idx, dev in enumerate(
                            snapshot_data['snapshot_devices']):
                        dev['extentsfile'] = extentsfiles[dev['backing']['fileName']]
                        dev['totalblocks'] = totalblocks[dev['backing']['fileName']]

            except Exception as ex:
                LOG.exception(ex)
            finally:
                for dmap in devicemap:
                    try:
                        os.remove(dmap['localvmdkpath'])
                    except BaseException:
                        pass

        for idx, dev in enumerate(snapshot_data['snapshot_devices']):
            if 'extentsfile' not in dev or not dev['extentsfile'] or \
                (hasattr(dev.backing, 'thinProvisioned') and
                 dev.backing.thinProvisioned) or \
                    dev['parent_changeId'] != '*':

                try:
                    if 'extentsfile' in dev and dev['extentsfile'] and \
                            os.path.isfile(dev['extentsfile']):
                        os.remove(dev['extentsfile'])
                except BaseException:
                    pass

                parent_vault_path = dev['parent_vault_path']
                parent_changeId = dev['parent_changeId']
                parent_content_id = dev['parent_content_id']

                fileh, dev['extentsfile'] = mkstemp()
                close(fileh)
                with open(dev['extentsfile'], 'w') as ctkfile:
                    position = 0
                    while position < dev.capacityInBytes:
                        changes = self._session._call_method(
                            self._session._get_vim(),
                            "QueryChangedDiskAreas", snapshot_data['vm_ref'],
                            snapshot=snapshot_data['snapshot_ref'],
                            deviceKey=dev.key,
                            startOffset=position,
                            changeId=parent_changeId)
                        if changes == []:
                            changes = self._session._call_method(
                                self._session._get_vim(),
                                "QueryChangedDiskAreas",
                                snapshot_data['vm_ref'],
                                snapshot=snapshot_data['snapshot_ref'],
                                deviceKey=dev['key'],
                                startOffset=position,
                                changeId=parent_changeId)

                        if 'changedArea' in changes:
                            for extent in changes.changedArea:
                                start = extent.start
                                length = extent.length

                                ctkfile.write(
                                    str(start) + "," + str(length) + "\n")
                                dev['disk_data_size'] += length
                        position = changes.startOffset + changes.length
            else:
                dev['disk_data_size'] += dev['totalblocks'] * \
                    4096  # Use blocksize later

        for idx, dev in enumerate(snapshot_data['snapshot_devices']):
            snapshot_data['vm_data_size'] += dev['disk_data_size']

        return snapshot_data

    @autolog.log_method(Logger, 'VMwareVCDriver.upload_snapshot')
    def upload_snapshot(self, cntx, db, instance, snapshot, snapshot_data_ex):

        @autolog.log_method(
            Logger, 'VMwareVCDriver.upload_snapshot._upload_vmdk')
        def _upload_vmdk(dev):
            try:
                totalBytesToTransfer = dev['disk_data_size']
                snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
                if snapshot_obj.snapshot_type == 'full':
                    parent_vault_path = None
                    parent_changeId = '*'
                    parent_content_id = None
                else:
                    parent_vault_path, parent_changeId, parent_content_id = self.get_parent_changeId(
                        cntx, db, snapshot['workload_id'], instance['vm_id'], dev.backing.uuid)

                vm_disk_resource_snap_backing = self.get_top_vm_disk_resource_snap(
                    cntx, db, snapshot['workload_id'], instance['vm_id'], dev.backing.uuid)
                if vm_disk_resource_snap_backing:
                    vm_disk_resource_snap_backing_id = vm_disk_resource_snap_backing.id
                else:
                    vm_disk_resource_snap_backing_id = None

                if snapshot_obj.snapshot_type == 'full':
                    vm_disk_resource_snap_backing_id = None

                # create an entry in the vm_disk_resource_snaps table
                vm_disk_resource_snap_id = str(uuid.uuid4())
                vm_disk_resource_snap_metadata = {}  # Dictionary to hold the metadata
                vm_disk_resource_snap_metadata.setdefault(
                    'disk_format', 'vmdk')
                if hasattr(
                        dev.backing,
                        'thinProvisioned') and dev.backing.thinProvisioned:
                    vm_disk_resource_snap_metadata.setdefault(
                        'vmware_disktype', 'thin')
                else:
                    vm_disk_resource_snap_metadata.setdefault(
                        'vmware_disktype', 'thick')
                if hasattr(dev.backing,
                           'eagerlyScrub') and dev.backing.eagerlyScrub:
                    vm_disk_resource_snap_metadata.setdefault(
                        'vmware_eagerlyScrub', 'True')
                else:
                    vm_disk_resource_snap_metadata.setdefault(
                        'vmware_eagerlyScrub', 'False')
                vm_disk_resource_snap_metadata.setdefault(
                    'vmware_adaptertype', 'lsiLogic')

                vm_disk_resource_snap_values = {
                    'id': vm_disk_resource_snap_id,
                    'snapshot_vm_resource_id': snapshot_vm_resource.id,
                    'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                    'metadata': vm_disk_resource_snap_metadata,
                    'top': True,
                    'size': dev['disk_data_size'],
                    'status': 'creating'}

                vm_disk_resource_snap = db.vm_disk_resource_snap_create(
                    cntx, vm_disk_resource_snap_values)

                snapshot_vm_disk_resource_metadata = {
                    'workload_id': snapshot['workload_id'],
                    'snapshot_id': snapshot['id'],
                    'snapshot_vm_id': instance['vm_id'],
                    'snapshot_vm_resource_id': snapshot_vm_resource.id,
                    'snapshot_vm_resource_name': dev.deviceInfo.label,
                    'vm_disk_resource_snap_id': vm_disk_resource_snap_id,
                }

                copy_to_file_path = vault.get_snapshot_vm_disk_resource_path(
                    snapshot_vm_disk_resource_metadata)
                head, tail = os.path.split(copy_to_file_path)
                fileutils.ensure_tree(head)

                vmxspec = 'moref=' + snapshot_data_ex['vm_ref'].value
                vix_disk_lib_env = os.environ.copy()
                vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                # Create empty vmdk file
                if parent_vault_path is None:
                    try:
                        cmdline = "trilio-vix-disk-cli -create "
                        cmdline += "-cap " + \
                            str(dev.capacityInBytes / (1024 * 1024))
                        cmdline += " " + copy_to_file_path
                        check_output(
                            cmdline.split(" "),
                            stderr=subprocess.STDOUT,
                            env=vix_disk_lib_env)
                    except subprocess.CalledProcessError as ex:
                        LOG.critical(
                            _("cmd: %s resulted in error: %s") %
                            (cmdline, ex.output))
                        LOG.exception(ex)
                        raise
                elif os.path.isfile(parent_vault_path) == False:
                    try:
                        head, tail = os.path.split(parent_vault_path)
                        fileutils.ensure_tree(head)
                        cmdline = "trilio-vix-disk-cli -create "
                        cmdline += "-cap " + \
                            str(dev.capacityInBytes / (1024 * 1024))
                        cmdline += " " + parent_vault_path
                        check_output(
                            cmdline.split(" "),
                            stderr=subprocess.STDOUT,
                            env=vix_disk_lib_env)
                    except subprocess.CalledProcessError as ex:
                        LOG.critical(
                            _("cmd: %s resulted in error: %s") %
                            (cmdline, ex.output))
                        LOG.exception(ex)
                        raise

                shutil.copyfile(dev['extentsfile'], copy_to_file_path + "-ctk")
                os.remove(dev['extentsfile'])

                if parent_vault_path:
                    cmdspec = ["trilio-vix-disk-cli", "-downloadextents",
                               str(dev.backing.fileName),
                               "-extentfile", copy_to_file_path + "-ctk",
                               "-parentPath", parent_vault_path,
                               "-host", self._session._host_ip,
                               "-user", self._session._host_username,
                               "-password", "***********",
                               "-vm", vmxspec,
                               copy_to_file_path]
                else:
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
                        cmdspec[idx + 1] = self._session._host_password
                        break

                process = subprocess.Popen(cmdspec,
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,
                                           bufsize=-1,
                                           env=vix_disk_lib_env,
                                           close_fds=True,
                                           shell=False)

                queue = Queue()
                read_thread = Thread(
                    target=enqueue_output, args=(
                        process.stdout, queue))
                read_thread.daemon = True  # thread dies with the program
                read_thread.start()

                uploaded_size = 0
                uploaded_size_incremental = 0
                previous_uploaded_size = 0
                while process.poll() is None:
                    try:
                        db.snapshot_get_metadata_cancel_flag(
                            cntx, snapshot['id'], 0, process)
                        try:
                            output = queue.get(timeout=5)
                        except Empty:
                            continue
                        except Exception as ex:
                            LOG.exception(ex)
                        done_bytes = re.search(r'\d+ Done', output)
                        if done_bytes:
                            totalbytes = int(done_bytes.group().split(" ")[0])
                            uploaded_size_incremental = totalbytes - previous_uploaded_size
                            uploaded_size = totalbytes
                            snapshot_obj = db.snapshot_update(
                                cntx, snapshot['id'], {
                                    'uploaded_size_incremental': uploaded_size_incremental})
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

                snapshot_obj = db.snapshot_update(
                    cntx, snapshot['id'], {
                        'uploaded_size_incremental': (
                            totalBytesToTransfer - uploaded_size)})

                LOG.debug(_("snapshot_size: %(snapshot_size)s") %
                          {'snapshot_size': snapshot_obj.size, })
                LOG.debug(_("uploaded_size: %(uploaded_size)s") %
                          {'uploaded_size': snapshot_obj.uploaded_size, })
                LOG.debug(_("progress_percent: %(progress_percent)s") %
                          {'progress_percent': snapshot_obj.progress_percent, })

                try:
                    cmdline = "vmware-vdiskmanager -R".split(" ")
                    cmdline.append(copy_to_file_path)
                    check_output(
                        cmdline,
                        stderr=subprocess.STDOUT,
                        env=vix_disk_lib_env)
                except subprocess.CalledProcessError as ex:
                    LOG.critical(
                        _("cmd: %s resulted in error: %s") %
                        (" ".join(cmdline), ex.output))
                    raise

                if parent_content_id:
                    self._set_parent_content_id(
                        copy_to_file_path, parent_content_id)
                content_id = self._get_vmdk_content_id(copy_to_file_path)

                vm_disk_resource_snap_size = vault.get_size(copy_to_file_path)
                if getattr(dev.backing, 'thinProvisioned', False):
                    disk_type = "thin"
                else:
                    if getattr(dev.backing, 'eagerlyScrub', False):
                        disk_type = "eagerZeroedThick"
                    else:
                        disk_type = "preallocated"
                vm_disk_resource_snap_restore_size = vault.get_restore_size(
                    copy_to_file_path, 'vmdk', disk_type)

                # update the entry in the vm_disk_resource_snap table
                vm_disk_resource_snap_values = {
                    'vault_url': copy_to_file_path.replace(
                        vault.get_vault_data_directory(),
                        '',
                        1),
                    'vault_service_metadata': 'None',
                    'finished_at': timeutils.utcnow(),
                    'time_taken': int(
                        (timeutils.utcnow() - vm_disk_resource_snap.created_at).total_seconds()),
                    'metadata': {
                        'content_id': content_id},
                    'size': vm_disk_resource_snap_size,
                    'restore_size': vm_disk_resource_snap_restore_size,
                    'status': 'available'}
                vm_disk_resource_snap = db.vm_disk_resource_snap_update(
                    cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
                if vm_disk_resource_snap_backing:
                    vm_disk_resource_snap_backing = db.vm_disk_resource_snap_update(
                        cntx, vm_disk_resource_snap_backing.id, {
                            'vm_disk_resource_snap_child_id': vm_disk_resource_snap.id})
                    # Upload snapshot metadata to the vault
                    snapshot_vm_resource_backing = db.snapshot_vm_resource_get(
                        cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                    workload_utils.upload_snapshot_db_entry(
                        cntx, snapshot_vm_resource_backing.snapshot_id)

                snapshot_type = 'full' if parent_changeId == '*' else 'incremental'
                return vm_disk_resource_snap_size, snapshot_type
                # END of inner function _upload_vmdk
            except Exception as ex:
                LOG.exception(ex)
                raise
        try:
            snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
            workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
            # make sure the session cookies are upto data by calling the
            # following api
            datacenter_name = self._get_datacenter_ref_and_name(
                snapshot_data_ex['vmx_file']['vmx_datastore_ref'])[1]
            cookies = self._session._get_vim().client.options.transport.cookiejar
            # vmx file
            vmx_file_handle = read_write_util.VMwareHTTPReadFile(
                self._session._host_ip,
                self._get_datacenter_ref_and_name(
                    snapshot_data_ex['vmx_file']['vmx_datastore_ref'])[1],
                snapshot_data_ex['vmx_file']['vmx_datastore_name'],
                cookies,
                snapshot_data_ex['vmx_file']['vmx_file_name'])
            vmx_file_size = int(vmx_file_handle.get_size())
            # TODO(giri): throw exception if the size is more than 65536
            vmx_file_data = vmx_file_handle.read(vmx_file_size)
            vmx_file_handle.close()
            metadata = snapshot_data_ex['vmx_file']
            metadata['vmx_file_data'] = vmx_file_data
            snapshot_vm_resource_values = {
                'id': str(
                    uuid.uuid4()),
                'vm_id': instance['vm_id'],
                'snapshot_id': snapshot_obj.id,
                'resource_type': 'vmx',
                'resource_name': snapshot_data_ex['vmx_file']['vmx_file_name'],
                'metadata': metadata,
                'status': 'creating'}

            snapshot_vm_resource = db.snapshot_vm_resource_create(
                cntx, snapshot_vm_resource_values)
            db.snapshot_vm_resource_update(
                cntx, snapshot_vm_resource.id, {
                    'status': 'available', 'size': vmx_file_size})

            for idx, dev in enumerate(snapshot_data_ex['snapshot_devices']):

                db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

                vm_disk_size = 0
                disk = snapshot_data_ex['disks'][idx]

                snapshot_vm_resource_metadata = {}
                snapshot_vm_resource_metadata['vmdk_controler_key'] = disk['vmdk_controler_key']
                snapshot_vm_resource_metadata['adapter_type'] = disk['adapter_type']
                snapshot_vm_resource_metadata['label'] = disk['label']
                snapshot_vm_resource_metadata['unit_number'] = disk['unit_number']
                snapshot_vm_resource_metadata['disk_type'] = disk['disk_type']
                snapshot_vm_resource_metadata['capacityInKB'] = disk['capacityInKB']
                snapshot_vm_resource_metadata['changeId'] = dev.backing.changeId

                snapshot_vm_resource_values = {
                    'id': str(
                        uuid.uuid4()),
                    'vm_id': instance['vm_id'],
                    'snapshot_id': snapshot_obj.id,
                    'resource_type': 'disk',
                    'resource_name': disk['label'],
                    'resource_pit_id': dev.backing.uuid,
                    'metadata': snapshot_vm_resource_metadata,
                    'status': 'creating'}

                snapshot_vm_resource = db.snapshot_vm_resource_create(
                    cntx, snapshot_vm_resource_values)
                db.snapshot_update(
                    cntx,
                    snapshot_obj.id,
                    {
                        'progress_msg': "Uploading '" + dev.deviceInfo.label + "' of '" + instance['vm_name'] + "'",
                        'status': 'uploading'})
                vmdk_size, snapshot_type = _upload_vmdk(dev)
                object_store_transfer_time = vault.upload_snapshot_vm_resource_to_object_store(
                    cntx,
                    {
                        'workload_id': snapshot_obj.workload_id,
                        'workload_name': workload_obj.display_name,
                        'snapshot_id': snapshot_obj.id,
                        'snapshot_vm_id': instance['vm_id'],
                        'snapshot_vm_resource_id': snapshot_vm_resource.id,
                        'snapshot_vm_resource_name': dev.deviceInfo.label,
                        'snapshot_vm_name': instance['vm_name']})
                workload_utils.purge_snapshot_vm_resource_from_staging_area(
                    cntx, snapshot_obj.id, snapshot_vm_resource.id)

                db.snapshot_update(
                    cntx,
                    snapshot_obj.id,
                    {
                        'progress_msg': "Uploaded '" + dev.deviceInfo.label + "' of '" + instance['vm_name'] + "'",
                        'status': 'uploading'})

                snapshot_vm_resource = db.snapshot_vm_resource_update(
                    cntx,
                    snapshot_vm_resource.id,
                    {
                        'status': 'available',
                        'size': vmdk_size,
                        'snapshot_type': snapshot_type,
                        'finished_at': timeutils.utcnow(),
                        'time_taken': int(
                            (timeutils.utcnow() - snapshot_vm_resource.created_at).total_seconds()),
                        'metadata': {
                            'object_store_transfer_time': object_store_transfer_time},
                    })
        except Exception as ex:
            LOG.exception(ex)
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver.remove_snapshot_vm')
    def remove_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_ref):
        try:
            vm_ref = vm_util.get_vm_ref(self._session,
                                        {'uuid': instance['vm_id'],
                                         'vm_name': instance['vm_name'],
                                            'vmware_uuid': instance['vm_metadata']['vmware_uuid'],
                                         })
            db.snapshot_update(
                cntx, snapshot['id'], {
                    'progress_msg': 'Removing Snapshot of Virtual Machine ' + instance['vm_name']})
            remove_snapshot_task = self._session._call_method(
                self._session._get_vim(),
                "RemoveSnapshot_Task", snapshot_ref,
                removeChildren=False)
            self._session._wait_for_task(
                instance['vm_id'], remove_snapshot_task)
        except Exception as ex:
            LOG.exception(ex)
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver.repair_vm_disk_resource_snap')
    def repair_vm_disk_resource_snap(
            self, cntx, db, snapshot_vm_resource, current_snapshot):
        top_snapshot_vm_resource = None
        if current_snapshot:
            try:
                top_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_pit_id(
                    cntx,
                    snapshot_vm_resource.vm_id,
                    current_snapshot['id'],
                    snapshot_vm_resource.resource_pit_id)
            except Exception as ex:
                LOG.exception(ex)

        if top_snapshot_vm_resource is None:
            snapshots = db.snapshot_get_all_by_project_workload(
                cntx, cntx.project_id, current_snapshot['workload_id'])
            for snapshot in snapshots:
                if snapshot.status != "available":
                    continue
                try:
                    top_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_pit_id(
                        cntx, snapshot_vm_resource.vm_id, snapshot.id, snapshot_vm_resource.resource_pit_id)
                    break
                except Exception as ex:
                    LOG.exception(ex)

        if top_snapshot_vm_resource is None:
            raise exception.ErrorOccurred(
                reason='Failed to identify the parent snapshot resource')

        vm_disk_resource_snap_chain = []

        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(
            cntx, top_snapshot_vm_resource.id)
        while vm_disk_resource_snap:
            vm_disk_resource_snap_chain.insert(0, vm_disk_resource_snap)
            if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
                vm_disk_resource_snap = db.vm_disk_resource_snap_get(
                    cntx, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
            else:
                vm_disk_resource_snap = None

        vix_disk_lib_env = os.environ.copy()
        vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
        for vm_disk_resource_snap in vm_disk_resource_snap_chain:
            try:
                cmdline = "vmware-vdiskmanager -R".split(" ")
                cmdline.append(vm_disk_resource_snap.vault_path)
                output = check_output(
                    cmdline,
                    stderr=subprocess.STDOUT,
                    env=vix_disk_lib_env)
                LOG.info(" ".join(cmdline))
                LOG.info(output)
            except subprocess.CalledProcessError as ex:
                LOG.critical(
                    _("cmd: %s resulted in error: %s") %
                    (" ".join(cmdline), ex.output))
                raise

    @autolog.log_method(Logger, 'VMwareVCDriver.apply_retention_policy')
    def apply_retention_policy(self, cntx, db, instances, snapshot):
        try:
            (snapshot_to_commit,
             snapshots_to_delete,
             affected_snapshots,
             workload_obj,
             snapshot_obj,
             swift) = workload_utils.common_apply_retention_policy(cntx,
                                                                   instances,
                                                                   snapshot)

            if swift == 0:
                return

            # if commited snapshot is full delete all snapshots below it
            if snapshot_to_commit and snapshot_to_commit.snapshot_type == 'full':
                for snap in snapshots_to_delete:
                    workload_utils.common_apply_retention_snap_delete(
                        cntx, snap, workload_obj)

            elif snapshot_to_commit:
                vix_disk_lib_env = os.environ.copy()
                vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                affected_snapshots.append(snapshot_to_commit.id)
                for snap in snapshots_to_delete:
                    affected_snapshots.append(snap.id)
                    snapshot_to_commit = db.snapshot_get(
                        cntx, snapshot_to_commit.id, read_deleted='yes')
                    if snapshot_to_commit.snapshot_type == 'full':
                        workload_utils.common_apply_retention_snap_delete(
                            cntx, snap, workload_obj)
                        continue

                    snapshot_vm_resources = db.snapshot_resources_get(
                        cntx, snapshot_to_commit.id)
                    for snapshot_vm_resource in snapshot_vm_resources:
                        if snapshot_vm_resource.resource_type != 'disk':
                            continue
                        vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(
                            cntx, snapshot_vm_resource.id)
                        if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
                            vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(
                                cntx, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                            with open(vm_disk_resource_snap_backing.vault_path + '-ctk', 'a') as backing_ctkfile:
                                with open(vm_disk_resource_snap.vault_path + "-ctk", 'r') as ctkfile:
                                    for line in ctkfile:
                                        start, length = line.split(',')
                                        start = int(start)
                                        length = int(length.rstrip('\n'))
                                        try:
                                            cmdline = "trilio-vix-disk-cli -copy".split(
                                                " ")
                                            cmdline.append(
                                                vm_disk_resource_snap.vault_path)
                                            cmdline += ("-start " +
                                                        str(start / 512)).split(" ")
                                            cmdline += ("-count " +
                                                        str(length / 512)).split(" ")
                                            cmdline.append(
                                                vm_disk_resource_snap_backing.vault_path)
                                            check_output(
                                                cmdline, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                                        except subprocess.CalledProcessError as ex:
                                            LOG.critical(
                                                _("cmd: %s resulted in error: %s") %
                                                (" ".join(cmdline), ex.output))
                                            raise
                                        backing_ctkfile.write(
                                            str(start) + "," + str(length) + "\n")

                            os.remove(vm_disk_resource_snap.vault_path)
                            os.remove(
                                vm_disk_resource_snap.vault_path + '-ctk')
                            shutil.move(
                                vm_disk_resource_snap_backing.vault_path,
                                vm_disk_resource_snap.vault_path)
                            shutil.move(
                                vm_disk_resource_snap_backing.vault_path + '-ctk',
                                vm_disk_resource_snap.vault_path + '-ctk')
                            affected_snapshots = workload_utils.common_apply_retention_db_backing_update(
                                cntx,
                                snapshot_vm_resource,
                                vm_disk_resource_snap,
                                vm_disk_resource_snap_backing,
                                affected_snapshots)

                            try:
                                vm_disk_resource_snap_child = db.vm_disk_resource_snap_get(
                                    cntx, vm_disk_resource_snap.vm_disk_resource_snap_child_id)
                            except Exception as ex:
                                LOG.exception(ex)
                                vm_disk_resource_snap_child = None

                            if vm_disk_resource_snap_child:
                                self._adjust_vmdk_content_id(
                                    vm_disk_resource_snap.vault_path, vm_disk_resource_snap_child.vault_path)

                            self.repair_vm_disk_resource_snap(
                                cntx, db, snapshot_vm_resource, snapshot)

                    workload_utils.common_apply_retention_disk_check(
                        cntx, snapshot_to_commit, snap, workload_obj)

            # Upload snapshot metadata to the vault
            for snapshot_id in affected_snapshots:
                workload_utils.upload_snapshot_db_entry(cntx, snapshot_id)

        except Exception as ex:
            LOG.exception(ex)
            db.snapshot_update(
                cntx, snapshot['id'], {
                    'warning_msg': 'Failed to apply retention policy - ' + ex.message})
            # swallow the exception

    @autolog.log_method(Logger, 'VMwareVCDriver.post_snapshot_vm')
    def post_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_data):
        try:
            if 'snapshot_ref' in snapshot_data:
                self.remove_snapshot_vm(
                    cntx, db, instance, snapshot, snapshot_data['snapshot_ref'])
        except Exception as ex:
            LOG.exception(ex)
            raise

    @autolog.log_method(Logger, 'VMwareVCDriver.delete_restored_vm')
    def delete_restored_vm(self, cntx, db, instance, restore):
        vms = db.restored_vms_get(cntx, restore['id'])
        for vm in vms:
            uuid = None
            for meta in vm.metadata:
                if meta.key == 'uuid':
                    uuid = meta.value

            vm_ref = vm_util.get_vm_ref(self._session, {'uuid': vm.vm_id,
                                                        'vm_name': vm.vm_name,
                                                        'vmware_uuid': uuid,
                                                        })

            delete_task = self._session._call_method(self._session._get_vim(),
                                                     "Destroy_Task", vm_ref)
            self._session._wait_for_task(vm.vm_id, delete_task)

            db.restored_vm_update(
                cntx, vm.vm_id, restore['id'], {
                    'status': 'deleted'})

    @autolog.log_method(Logger, 'VMwareVCDriver.restore_vm')
    def restore_vm(
            self,
            cntx,
            db,
            instance,
            restore,
            restored_net_resources,
            restored_security_groups,
            restored_compute_flavor,
            restored_nics,
            instance_options):
        """
        Restores the specified instance from a snapshot
        """
        try:
            LOG.info(_('Restore Options: %s') % str(instance_options))
            restore_obj = db.restore_get(cntx, restore['id'])
            snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
            instance['uuid'] = instance_uuid = instance_options['id']
            if 'name' in instance_options and instance_options['name']:
                instance['name'] = instance_name = instance_options['name']
            else:
                instance['name'] = instance_name = instance_options['name'] = instance['vm_name']

            msg = 'Creating VM ' + \
                instance['vm_name'] + ' from snapshot ' + snapshot_obj.id
            db.restore_update(cntx, restore_obj.id, {'progress_msg': msg})
            LOG.info(msg)

            client_factory = self._session._get_vim().client.factory
            service_content = self._session._get_vim().get_service_content()
            cookies = self._session._get_vim().client.options.transport.cookiejar

            # get datacenter name and reference
            datastore_info = vm_util.get_datastore_ref_and_name(
                self._session, datastore_moid=instance_options['datastores'][0]['moid'])
            datastore_ref = datastore_info[0]
            datacenter = self._get_datacenter_ref_and_name(datastore_ref)
            datacenter_ref = datacenter[0]
            datacenter_name = datacenter[1]

            # create folders for vmx and vmdks
            for datastore in instance_options['datastores']:
                datastore_name = datastore['name'].replace('[', '')
                datastore_name = datastore['name'].replace(']', '')
                try:
                    folder_name = instance_options['name']
                    folder_path = vm_util.build_datastore_path(
                        datastore['name'], folder_name)
                    self._mkdir(folder_path, datacenter_ref)
                except Exception as ex:
                    LOG.exception(ex)
                    folder_name = instance_options['name'] + \
                        '-' + restore['id']
                    folder_path = vm_util.build_datastore_path(
                        datastore['name'], folder_name)
                    self._mkdir(folder_path, datacenter_ref)
                datastore['folder_name'] = folder_name

            """Restore vmx file"""
            vmx_datastore_name = instance_options['vmxpath']['datastore']
            vmx_datastore_name = vmx_datastore_name.replace('[', '')
            vmx_datastore_name = vmx_datastore_name.replace(']', '')
            folder_name = None
            for datastore in instance_options['datastores']:
                if datastore['name'] == vmx_datastore_name:
                    folder_name = datastore['folder_name']
                    break

            snapshot_vm_resources = db.snapshot_vm_resources_get(
                cntx, instance['vm_id'], snapshot_obj.id)
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type == 'vmx':
                    vmx_name = "%s/%s" % (folder_name,
                                          os.path.basename(
                                              snapshot_vm_resource.resource_name))
                    url_compatible = vmx_name.replace(" ", "%20")
                    temp_session = None
                    try:
                        LOG.info(
                            _('Restoring vmx: %s %s') %
                            (vmx_datastore_name, vmx_name))
                        temp_session = VMwareAPISession(
                            scheme=self._session._scheme)
                        temp_cookies = temp_session._get_vim().client.options.transport.cookiejar
                        vmdk_write_file_handle = read_write_util.VMwareHTTPWriteFile(
                            temp_session._host_ip,
                            datacenter_name,
                            vmx_datastore_name,
                            temp_cookies,
                            url_compatible,
                            snapshot_vm_resource.size)
                        vmx_file_data = db.get_metadata_value(
                            snapshot_vm_resource.metadata, 'vmx_file_data')
                        vmdk_write_file_handle.write(vmx_file_data)
                        vmdk_write_file_handle.close()
                        LOG.info(
                            _('Restored vmx: %s %s') %
                            (vmx_datastore_name, vmx_name))
                    except Exception as ex:
                        LOG.exception(ex)
                        if temp_session:
                            temp_session.__del__()
                        temp_session = VMwareAPISession(
                            scheme=self._session._scheme)
                        temp_cookies = temp_session._get_vim().client.options.transport.cookiejar
                        vmdk_write_file_handle = read_write_util.VMwareHTTPWriteFile(
                            temp_session._host_ip,
                            datacenter_name,
                            vmx_datastore_name,
                            temp_cookies,
                            url_compatible,
                            snapshot_vm_resource.size)
                        vmx_file_data = db.get_metadata_value(
                            snapshot_vm_resource.metadata, 'vmx_file_data')
                        vmdk_write_file_handle.write(vmx_file_data)
                        vmdk_write_file_handle.close()
                        LOG.info(
                            _('Restored vmx: %s %s') %
                            (vmx_datastore_name, vmx_name))
                    if temp_session:
                        temp_session.__del__()
                    break

            """Register VM on ESX host."""
            LOG.info(_("Registering VM %s") % instance_name)
            # Create the VM on the ESX host
            vm_folder_ref = None
            if 'vmfolder' in instance_options:
                if 'moid' in instance_options['vmfolder']:
                    vm_folder_ref = self._get_vmfolder_ref(
                        datacenter_ref, instance_options['vmfolder']['moid'])
            if not vm_folder_ref:
                vm_folder_ref = self._get_vmfolder_ref(datacenter_ref)

            resourcepool_ref = None
            computeresource_ref = None
            host_ref = None
            if 'resourcepool' in instance_options and \
               instance_options['resourcepool'] and \
               'moid' in instance_options['resourcepool'] and \
               instance_options['resourcepool']['moid']:
                resourcepool_ref = self._get_res_pool_ref(
                    instance_options['resourcepool']['moid'])
            else:
                computeresource_ref, host_ref = self._get_computeresource_host_ref(
                    instance_options['computeresource']['moid'])
                resourcepool_ref = self._session._call_method(
                    vim_util,
                    "get_dynamic_property",
                    computeresource_ref,
                    computeresource_ref._type,
                    "resourcePool")

            vmx_path = vm_util.build_datastore_path(
                vmx_datastore_name, vmx_name)
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
                self._session._wait_for_task(
                    instance['uuid'], vm_register_task)
            except Exception as ex:
                instance_options['name'] = instance_options['name'] + \
                    '-' + restore['id']
                instance_options['name'] = instance_options['name'][0:78]
                vm_register_task = self._session._call_method(
                    self._session._get_vim(),
                    "RegisterVM_Task",
                    vm_folder_ref,
                    path=vmx_path,
                    name=instance_options['name'],
                    asTemplate=False,
                    pool=resourcepool_ref,
                    host=host_ref)
                self._session._wait_for_task(
                    instance['uuid'], vm_register_task)

            LOG.info(_("Registered VM %s") % instance_name)
            vm_ref = self._get_vm_ref_from_name_folder(
                vm_folder_ref, instance_options['name'])
            hardware_devices = self._session._call_method(
                vim_util,
                "get_dynamic_property",
                vm_ref,
                "VirtualMachine",
                "config.hardware.device")
            if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
                hardware_devices = hardware_devices.VirtualDevice

            LOG.info(_('Detaching disks'))
            for device in hardware_devices:
                if device.__class__.__name__ == "VirtualDisk":
                    self._detach_disk_from_vm(
                        vm_ref, instance, device, destroy_disk=False)

            LOG.info(_('Reconfiguring networks'))
            for device in hardware_devices:
                if hasattr(device, 'backing') and device.backing:
                    new_network_ref = None
                    if device.backing.__class__.__name__ == "VirtualEthernetCardNetworkBackingInfo":
                        if 'networks' in instance_options and instance_options['networks']:
                            for network in instance_options['networks']:
                                if device.backing.deviceName == network['network_name']:
                                    new_network_ref = self._get_network_ref(
                                        network['new_network_moid'], datacenter_ref)
                                    break
                    elif device.backing.__class__.__name__ == "VirtualEthernetCardDistributedVirtualPortBackingInfo":
                        if 'networks' in instance_options and instance_options['networks']:
                            for network in instance_options['networks']:
                                if device.backing.port.portgroupKey == network['network_moid']:
                                    new_network_ref = self._get_network_ref(
                                        network['new_network_moid'], datacenter_ref)
                                    break
                    else:
                        continue
                    if new_network_ref is None:
                        # We only get into this situaltion when the vmx network settings does
                        # not match with mob of the VM. We run into this once
                        continue
                    if new_network_ref._type == "Network":
                        device.backing = client_factory.create(
                            'ns0:VirtualEthernetCardNetworkBackingInfo')
                        device.backing.deviceName = network['new_network_name']
                        device.backing.network = new_network_ref
                    elif new_network_ref._type == "DistributedVirtualPortgroup":
                        dvportgroup_config = self._session._call_method(
                            vim_util,
                            "get_dynamic_property",
                            new_network_ref,
                            "DistributedVirtualPortgroup",
                            "config")
                        dvswitch_uuid = self._session._call_method(
                            vim_util,
                            "get_dynamic_property",
                            dvportgroup_config.distributedVirtualSwitch,
                            "VmwareDistributedVirtualSwitch",
                            "uuid")
                        device.backing = client_factory.create(
                            'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo')
                        device.backing.port.portgroupKey = dvportgroup_config.key
                        device.backing.port.switchUuid = dvswitch_uuid
                        device.backing.port.portKey = None

                    virtual_device_config_spec = client_factory.create(
                        'ns0:VirtualDeviceConfigSpec')
                    virtual_device_config_spec.device = device
                    virtual_device_config_spec.operation = "edit"
                    vm_config_spec = client_factory.create(
                        'ns0:VirtualMachineConfigSpec')
                    vm_config_spec.deviceChange = [virtual_device_config_spec]
                    LOG.info(_("Reconfiguring VM instance %(instance_name)s for nic %(nic_label)s"), {
                             'instance_name': instance_name, 'nic_label': device.deviceInfo.label})
                    reconfig_task = self._session._call_method(
                        self._session._get_vim(), "ReconfigVM_Task", vm_ref, spec=vm_config_spec)
                    self._session._wait_for_task(instance_uuid, reconfig_task)
                    LOG.info(_("Reconfigured VM instance %(instance_name)s for nic %(nic_label)s"),
                             {'instance_name': instance_name, 'nic_label': device.deviceInfo.label})

            #restore, rebase, commit & upload
            LOG.info(_('Processing disks'))
            snapshot_vm_object_store_transfer_time = 0
            snapshot_vm_data_transfer_time = 0
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type != 'disk':
                    continue
                snapshot_vm_resource_object_store_transfer_time = workload_utils.download_snapshot_vm_resource_from_object_store(
                    cntx, restore_obj.id, restore_obj.snapshot_id, snapshot_vm_resource.id)
                snapshot_vm_object_store_transfer_time += snapshot_vm_resource_object_store_transfer_time
                snapshot_vm_data_transfer_time += snapshot_vm_resource_object_store_transfer_time

                for vdisk in instance_options['vdisks']:
                    if vdisk['label'] == snapshot_vm_resource.resource_name:
                        vdisk_datastore_name = vdisk['datastore']
                        break

                folder_name = None
                vdisk_datastore_name = vdisk_datastore_name.replace('[', '')
                vdisk_datastore_name = vdisk_datastore_name.replace(']', '')
                for datastore in instance_options['datastores']:
                    if datastore['name'] == vdisk_datastore_name:
                        folder_name = datastore['folder_name']
                        break

                vmdk_name = "%s/%s.vmdk" % (folder_name,
                                            snapshot_vm_resource.resource_name.replace(
                                                ' ',
                                                '-'))
                vmdk_path = vm_util.build_datastore_path(
                    vdisk_datastore_name, vmdk_name)
                vmdk_create_spec = vm_util.get_vmdk_create_spec(client_factory,
                                                                db.get_metadata_value(
                                                                    snapshot_vm_resource.metadata, 'capacityInKB'),  # vmdk_file_size_in_kb,
                                                                db.get_metadata_value(
                                                                    snapshot_vm_resource.metadata, 'adapter_type'),  # adapter_type,
                                                                db.get_metadata_value(
                                                                    snapshot_vm_resource.metadata, 'disk_type')  # disk_type
                                                                )
                vmdk_create_task = self._session._call_method(
                    self._session._get_vim(),
                    "CreateVirtualDisk_Task",
                    service_content.virtualDiskManager,
                    name=vmdk_path,
                    datacenter=datacenter_ref,
                    spec=vmdk_create_spec)
                if vmdk_create_task == []:
                    vmdk_create_task = self._session._call_method(
                        self._session._get_vim(),
                        "CreateVirtualDisk_Task",
                        service_content.virtualDiskManager,
                        name=vmdk_path,
                        datacenter=datacenter_ref,
                        spec=vmdk_create_spec)

                self._session._wait_for_task(
                    instance['uuid'], vmdk_create_task)

                adapter_type = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'adapter_type')
                capacityInKB = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'capacityInKB')
                vmdk_controler_key = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'vmdk_controler_key')
                unit_number = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'unit_number')
                disk_type = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'disk_type')
                device_name = db.get_metadata_value(
                    snapshot_vm_resource.metadata, 'label')

                self._volumeops.attach_disk_to_vm(
                    vm_ref,
                    instance,
                    adapter_type,
                    disk_type,
                    vmdk_path,
                    capacityInKB,
                    linked_clone=False,
                    controller_key=vmdk_controler_key,
                    unit_number=unit_number,
                    device_name=device_name)

                LOG.info(
                    "Uploading '" +
                    device_name +
                    "' of '" +
                    instance['vm_name'] +
                    "'" +
                    " from snapshot " +
                    snapshot_obj.id)
                db.restore_update(
                    cntx,
                    restore['id'],
                    {
                        'progress_msg': "Uploading '" + device_name + "' of '" + instance['vm_name'] + "'",
                        'status': 'uploading'})

                vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(
                    cntx, snapshot_vm_resource.id)

                vix_disk_lib_env = os.environ.copy()
                vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'

                space_for_clone = 0
                try:
                    cmdspec = [
                        "trilio-vix-disk-cli",
                        "-spaceforclone",
                        disk_type,
                        vm_disk_resource_snap.vault_path,
                    ]
                    cmd = " ".join(cmdspec)
                    for idx, opt in enumerate(cmdspec):
                        if opt == "-password":
                            cmdspec[idx + 1] = self._session._host_password
                            break

                    output = check_output(
                        cmdspec, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                    space_for_clone_str = re.search(
                        r'\d+ Bytes Required for Cloning', output)
                    space_for_clone = int(
                        space_for_clone_str.group().split(" ")[0])
                except subprocess.CalledProcessError as ex:
                    LOG.critical(
                        _("cmd: %s resulted in error: %s") %
                        (cmd, ex.output))
                    LOG.exception(ex)
                    raise

                start_time = timeutils.utcnow()
                vmxspec = 'moref=' + vm_ref.value
                cmdspec = ["trilio-vix-disk-cli", "-clone",
                           vm_disk_resource_snap.vault_path,
                           "-host", self._session._host_ip,
                           "-user", self._session._host_username,
                           "-password", "***********",
                           "-vm", vmxspec,
                           vmdk_path, ]
                cmd = " ".join(cmdspec)
                for idx, opt in enumerate(cmdspec):
                    if opt == "-password":
                        cmdspec[idx + 1] = self._session._host_password
                        break

                process = subprocess.Popen(cmdspec,
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,
                                           bufsize=-1,
                                           env=vix_disk_lib_env,
                                           close_fds=True,
                                           shell=False)

                queue = Queue()
                read_thread = Thread(
                    target=enqueue_output, args=(
                        process.stdout, queue))
                read_thread.daemon = True  # thread dies with the program
                read_thread.start()

                uploaded_size = 0
                uploaded_size_incremental = 0
                previous_uploaded_size = 0
                while process.poll() is None:
                    try:
                        db.restore_get_metadata_cancel_flag(
                            cntx, restore['id'], 0, process)
                        try:
                            output = queue.get(timeout=5)
                        except Empty:
                            continue
                        except Exception as ex:
                            LOG.exception(ex)
                        done_percentage_str = re.search(r'\d+% Done', output)
                        if done_percentage_str:
                            done_percentage = int(
                                done_percentage_str.group().split(" ")[0].strip('%'))
                            totalbytes = (
                                space_for_clone * done_percentage) / 100
                            uploaded_size_incremental = totalbytes - previous_uploaded_size
                            uploaded_size = totalbytes
                            restore_obj = db.restore_update(
                                cntx, restore['id'], {
                                    'uploaded_size_incremental': uploaded_size_incremental})
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

                snapshot_vm_data_transfer_time += int(
                    (timeutils.utcnow() - start_time).total_seconds())
                """
                Repair is not working for remote disks
                try:
                    cmdspec = [ "trilio-vix-disk-cli", "-check", "1",
                               "-host", self._session._host_ip,
                               "-user", self._session._host_username,
                               "-password", "***********",
                               "-vm", vmxspec,
                               vmdk_path,]
                    cmd = " ".join(cmdspec)
                    for idx, opt in enumerate(cmdspec):
                        if opt == "-password":
                            cmdspec[idx+1] = self._session._host_password
                            break

                    check_output(cmdspec, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                except subprocess.CalledProcessError as ex:
                    LOG.critical(_("cmd: %s resulted in error: %s") %(cmd, ex.output))
                    LOG.exception(ex)
                    raise
                """

                restore_obj = db.restore_get(cntx, restore['id'])
                progress = "{message_color} {message} {progress_percent} {normal_color}".format(**{
                    'message_color': autolog.BROWN,
                    'message': "Restore Progress: ",
                    'progress_percent': str(restore_obj.progress_percent),
                    'normal_color': autolog.NORMAL,
                })
                LOG.debug(progress)
                workload_utils.purge_snapshot_vm_resource_from_staging_area(
                    cntx, restore_obj.snapshot_id, snapshot_vm_resource.id)
                # End of for loop for devices

            restored_instance_id = self._session._call_method(
                vim_util, "get_dynamic_property", vm_ref, "VirtualMachine", "config.instanceUuid")

            restored_instance_name = instance_options['name']
            restored_vm_values = {
                'vm_id': restored_instance_id,
                'vm_name': restored_instance_name,
                'restore_id': restore_obj.id,
                'metadata': {
                    'data_transfer_time': snapshot_vm_data_transfer_time,
                    'object_store_transfer_time': snapshot_vm_object_store_transfer_time,
                },
                'status': 'available'}
            restored_vm = db.restored_vm_create(cntx, restored_vm_values)

            LOG.info(_("RestoreVM %s Completed") % instance_name)

            # TODO(giri): Execuete the following in a finally block
            for snapshot_vm_resource in snapshot_vm_resources:
                if snapshot_vm_resource.resource_type != 'disk':
                    continue
                temp_directory = os.path.join(
                    "/var/triliovault", restore['id'], snapshot_vm_resource.id)
                try:
                    shutil.rmtree(temp_directory)
                except OSError as exc:
                    pass

            db.restore_update(
                cntx,
                restore_obj.id,
                {
                    'progress_msg': 'Created VM ' + instance['vm_name'] + ' from snapshot ' + snapshot_obj.id,
                    'status': 'executing'})

            return restored_vm
        except Exception as ex:
            LOG.exception(ex)
            raise
        finally:
            try:
                workload_utils.purge_snapshot_vm_from_staging_area(
                    cntx, restore_obj.snapshot_id, instance_options['id'])
            except Exception as ex:
                LOG.exception(ex)

    @autolog.log_method(Logger, 'VMwareVCDriver.poweron_vm')
    def poweron_vm(self, cntx, instance, restore, restored_instance):
        db = WorkloadMgrDB().db
        restore_obj = db.restore_get(cntx, restore['id'])
        restore_options = pickle.loads(str(restore_obj.pickle))
        instance_options = utils.get_instance_restore_options(
            restore_options, instance['vm_id'], 'vmware')
        vm_ref = vm_util.get_vm_ref_from_vmware_uuid(
            self._session, restored_instance['uuid'])
        if 'power' in instance_options and \
           instance_options['power'] and \
           'state' in instance_options['power'] and \
           instance_options['power']['state'] and \
           instance_options['power']['state'] == 'on':
            db.restore_update(
                cntx, restore_obj.id, {
                    'progress_msg': 'Powering on VM ' + restored_instance['vm_name'], 'status': 'executing'})
            self.power_on(vm_ref, instance)

    @autolog.log_method(Logger, 'VMwareVCDriver.mount_instance_root_device')
    def mount_instance_root_device(self, cntx, instance, restore):
        vm_ref = vm_util.get_vm_ref_from_vmware_uuid(
            self._session, instance['uuid'])
        db = WorkloadMgrDB().db
        restore_obj = db.restore_get(cntx, restore['id'])

        msg = 'Reconfiguring application on ' + instance['vm_name']
        db.restore_update(cntx, restore_obj.id, {'progress_msg': msg})

        root_disk_path = self._get_root_disk_path_from_vm_ref(vm_ref)
        vix_disk_lib_env = os.environ.copy()
        vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
        vmxspec = 'moref=' + vm_ref.value

        # cmdspec = ["sudo",
        # "LD_LIBRARY_PATH=/usr/lib/vmware-vix-disklib/lib64/",
        cmdspec = ["trilio-vix-disk-cli", "-mount",
                   "-host", self._session._host_ip,
                   "-user", self._session._host_username,
                   "-password", "***********",
                   "-vm", vmxspec,
                   root_disk_path, ]

        cmd = " ".join(cmdspec)
        for idx, opt in enumerate(cmdspec):
            if opt == "-password":
                cmdspec[idx + 1] = self._session._host_password
                break

        process = subprocess.Popen(cmdspec,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   bufsize=-1,
                                   env=vix_disk_lib_env,
                                   close_fds=True,
                                   shell=False)

        queue = Queue()
        read_thread = Thread(
            target=enqueue_output, args=(
                process.stdout, queue))
        read_thread.daemon = True  # thread dies with the program
        read_thread.start()

        mountpath = None
        while process.poll() is None:
            try:
                try:
                    output = queue.get(timeout=5)
                except Empty:
                    continue
                except Exception as ex:
                    LOG.exception(ex)
                if output.startswith("The root partition is mounted at"):
                    mountpath = output[len(
                        "The root partition is mounted at"):].strip()
                    break
            except Exception as ex:
                LOG.exception(ex)

        if not process.poll() is None:
            _returncode = process.returncode  # pylint: disable=E1101
            if _returncode:
                LOG.debug(_('Result was %s') % _returncode)
                raise exception.ProcessExecutionError(
                    exit_code=_returncode,
                    stderr=process.stderr.read(),
                    cmd=cmd)
        process.stdin.close()
        return process, mountpath

    @autolog.log_method(Logger, 'VMwareVCDriver.umount_instance_root_device')
    def umount_instance_root_device(self, process):
        process.send_signal(18)
        process.wait()

        _returncode = process.returncode  # pylint: disable=E1101

        if _returncode != 0:
            LOG.debug(_('Result was %s') % _returncode)
            raise exception.ProcessExecutionError(
                exit_code=_returncode,
                stderr=process.stderr.read())

    @autolog.log_method(Logger, 'VMwareVCDriver.snapshot_mount')
    def snapshot_mount(self, cntx, snapshot, diskfiles):

        db = WorkloadMgrDB().db
        processes = []
        mountpoints = {}
        devpaths = {}

        try:
            processes, mountpaths = vmdkmount.mount_local_vmdk(
                diskfiles, diskonly=True)

            snapshot_metadata = {'mountprocesses': "", }
            for process in processes:
                snapshot_metadata['mountprocesses'] += str(process.pid) + ";"
            db.snapshot_update(
                cntx, snapshot['id'], {
                    'metadata': snapshot_metadata})

            devpaths = vmdkmount.assignloopdevices(mountpaths)
        except Exception as ex:
            vmdkmount.unassignloopdevices(devpaths)
            vmdkmount.umount_local_vmdk(processes)
            LOG.exception(ex)
            raise

        return devpaths

    @autolog.log_method(Logger, 'VMwareVCDriver.snapshot_dismount')
    def snapshot_dismount(self, cntx, snapshot, devpaths):
        db = WorkloadMgrDB().db

        mountprocesses = db.get_metadata_value(
            snapshot.metadata, 'mountprocesses')
        vmdkmount.unassignloopdevices(devpaths)

        if mountprocesses:
            for mountprocess in mountprocesses.split(";"):
                if mountprocess != '':
                    try:
                        os.kill(int(mountprocess), 18)
                    except Exception as ex:
                        LOG.exception(ex)

        snapshot_metadata = {'mountprocesses': '', }
        db.snapshot_update(
            cntx, snapshot['id'], {
                'metadata': snapshot_metadata})


class VMwareAPISession(object):
    """
    Sets up a session with the VC/ESX host and handles all
    the calls made to the host.
    """

    @autolog.log_method(Logger, 'VMwareAPISession.__init__')
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

    @autolog.log_method(
        Logger, 'VMwareAPISession._get_vim_object', log_retval=False)
    def _get_vim_object(self):
        """Create the VIM Object instance."""
        return vim.Vim(protocol=self._scheme, host=self._host_ip)

    @autolog.log_method(Logger, 'VMwareAPISession._create_session')
    def _create_session(self):
        """Creates a session with the VC/ESX host."""
        delay = 1
        start_time = timeutils.utcnow()
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
                LOG.exception(excep)
                LOG.critical(_("Unable to connect to server at %(server)s, "
                               "sleeping for %(seconds)s seconds"),
                             {'server': self._host_ip, 'seconds': delay})
                time.sleep(delay)
                delay = min(2 * delay, 60)

            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=2):
                raise exception.ErrorOccurred(
                    reason='Timeout while establishing connection to vCenter Server %s' %
                    self._host_ip)

    @autolog.log_method(Logger, 'VMwareAPISession.__del__')
    def __del__(self):
        """Logs-out the session."""
        # Logout to avoid un-necessary increase in session count at the
        # ESX host
        try:
            # May not have been able to connect to VC, so vim is still None
            if self._session_id:
                self.vim.Logout(self.vim.get_service_content().sessionManager)
                self._session_id = None
        except Exception as excep:
            # It is just cautionary on our part to do a logout in del just
            # to ensure that the session is not left active.
            LOG.debug(excep)

    def _is_vim_object(self, module):
        """Check if the module is a VIM Object instance."""
        return isinstance(module, vim.Vim)

    @autolog.log_method(
        Logger, 'VMwareAPISession._call_method', log_retval=False)
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
                LOG.exception(exc)
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
                LOG.exception(exc)
            except Exception as excep:
                # If it is a proper exception, say not having furnished
                # proper data in the SOAP call or the retry limit having
                # exceeded, we raise the exception
                exc = excep
                LOG.exception(exc)
                break
            # If retry count has been reached then break and
            # raise the exception
            if retry_count > self._api_retry_count:
                break
            time.sleep(TIME_BETWEEN_API_CALL_RETRIES)

        LOG.critical(
            _("In VMwareAPISession:_call_method, got this exception: %s") %
            exc)
        raise

    @autolog.log_method(Logger, 'VMwareAPISession._get_vim', log_retval=False)
    def _get_vim(self):
        """Gets the VIM object reference."""
        if self.vim is None:
            self._create_session()
        return self.vim

    @autolog.log_method(
        Logger, 'VMwareAPISession._wait_for_task', log_retval=False)
    def _wait_for_task(self, instance_uuid, task_ref):
        """
        Return a Deferred that will give the result of the given task.
        The task is polled until it completes.
        """
        loop = loopingcall.FixedIntervalLoopingCall(
            self._poll_task, instance_uuid, task_ref)
        evt = loop.start(CONF.vmware.task_poll_interval)
        LOG.debug("Waiting for the task: %s to complete.", task_ref)
        return evt.wait()

    @autolog.log_method(
        Logger, 'VMwareAPISession._poll_task', log_retval=False)
    def _poll_task(self, instance_uuid, task_ref):
        """
        Poll the given task, and fires the given Deferred if we
        get a result.
        """
        try:
            task_info = self._call_method(
                vim_util, "get_dynamic_property", task_ref, "Task", "info")
        except Exception as excep:
            LOG.info(_("In vmwareapi:_poll_task, Got this error %s") % excep)
            raise
        else:

            if hasattr(task_info, 'name'):
                task_name = task_info.name
            else:
                task_name = task_info.descriptionId

            if task_info.state in ['queued', 'running']:
                if hasattr(task_info, 'progress'):
                    LOG.info("Task: %(task)s progress is %(progress)s%%.", {
                             'task': task_ref, 'progress': task_info.progress})
                return
            elif task_info.state == 'success':
                LOG.info(_("Task [%(task_name)s] %(task_ref)s status: success"), {
                         'task_name': task_name, 'task_ref': task_ref})
                raise loopingcall.LoopingCallDone(task_info)
            else:
                error_info = str(task_info.error.localizedMessage)
                LOG.info(_("Task [%(task_name)s] %(task_ref)s status: error %(error_info)s"), {
                         'task_name': task_name, 'task_ref': task_ref, 'error_info': error_info})
                raise exception
