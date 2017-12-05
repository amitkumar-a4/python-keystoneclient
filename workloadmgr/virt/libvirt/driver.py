# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
A connection to a hypervisor through libvirt.

Supports KVM

**Related Flags**

:libvirt_type:  Libvirt domain type.  kvm for now.
:libvirt_uri:  Override for the default libvirt URI (depends on libvirt_type).
:libvirt_disk_prefix:  Override the default disk prefix for the devices
                       attached to a server.
"""


import eventlet
import os
import socket
import uuid
import time
from Queue import Queue
import cPickle as pickle
import re
import shutil
import math
import datetime
import json

from stat import *
from eventlet import greenio
from eventlet import greenthread
from eventlet import patcher
from eventlet import tpool
#from eventlet import util as eventlet_util
from lxml import etree
from oslo.config import cfg

from novaclient.exceptions import Unauthorized as nova_unauthorized
from workloadmgr import utils
from workloadmgr import exception
from workloadmgr.virt import qemuimages
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import fileutils
from workloadmgr.virt import power_state
from workloadmgr.virt import driver
from workloadmgr.image import glance
from workloadmgr.volume import cinder
from workloadmgr.compute import nova
from workloadmgr.network import neutron
from workloadmgr.vault import vault
from workloadmgr import autolog

from workloadmgr.openstack.common import timeutils
from workloadmgr.workloads import workload_utils
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB

from nbd import NbdMount as nbd
import restore_vm_flow
import restore_vm_data_flow

native_threading = patcher.original("threading")
native_Queue = patcher.original("Queue")

libvirt = None

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

libvirt_opts = [
    cfg.StrOpt('libvirt_type',
               default='kvm',
               help='Libvirt domain type (valid options are: kvm)'),
    cfg.StrOpt('libvirt_uri',
               default='',
               help='Override the default libvirt URI '
                    '(which is dependent on libvirt_type)'),
    cfg.BoolOpt('libvirt_nonblocking',
                default=True,
                help='Use a separated OS thread pool to realize non-blocking'
                     ' libvirt calls'),
    cfg.StrOpt('instances_path',
               default='/opt/stack/data/nova/instances',
               help='Location where the instances are'),
    cfg.StrOpt('libvirt_snapshots_directory',
               default='$instances_path/snapshots',
               help='Location where libvirt driver will store snapshots '
                    'before uploading them to image service'),
    cfg.StrOpt('libvirt_type',
               default='kvm',
               help='Libvirt domain type (valid options are: kvm)'),
    cfg.StrOpt('glance_images_path',
               default='/opt/stack/data/nova/instances/_base',
               help='Location of the images for: nova, glance and wlm'),
    cfg.StrOpt('default_tvault_availability_zone',
               default='tvault_az',
               help='TrilioVault availability zone'),
    cfg.StrOpt('default_production_availability_zone',
               default='None',
               help='TrilioVault availability zone'),
    cfg.IntOpt('hard_reboot_wait',
               default=30,
               help='The amount of time that snapshot mount operation'
               'should wait for the recovery manager to reboot'),
    cfg.StrOpt('vault_storage_type',
               default='none',
               help='Storage type: local, das, vault, nfs, swift-i, swift-s, s3'),
]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts)


def patch_tpool_proxy():
    """eventlet.tpool.Proxy doesn't work with old-style class in __str__()
    or __repr__() calls. See bug #962840 for details.
    We perform a monkey patch to replace those two instance methods.
    """

    def str_method(self):
        return str(self._obj)

    def repr_method(self):
        return repr(self._obj)

    tpool.Proxy.__str__ = str_method
    tpool.Proxy.__repr__ = repr_method


patch_tpool_proxy()

VIR_DOMAIN_NOSTATE = 0
VIR_DOMAIN_RUNNING = 1
VIR_DOMAIN_BLOCKED = 2
VIR_DOMAIN_PAUSED = 3
VIR_DOMAIN_SHUTDOWN = 4
VIR_DOMAIN_SHUTOFF = 5
VIR_DOMAIN_CRASHED = 6
VIR_DOMAIN_PMSUSPENDED = 7

LIBVIRT_POWER_STATE = {
    VIR_DOMAIN_NOSTATE: power_state.NOSTATE,
    VIR_DOMAIN_RUNNING: power_state.RUNNING,
    VIR_DOMAIN_BLOCKED: power_state.RUNNING,
    VIR_DOMAIN_PAUSED: power_state.PAUSED,
    VIR_DOMAIN_SHUTDOWN: power_state.SHUTDOWN,
    VIR_DOMAIN_SHUTOFF: power_state.SHUTDOWN,
    VIR_DOMAIN_CRASHED: power_state.CRASHED,
    VIR_DOMAIN_PMSUSPENDED: power_state.SUSPENDED,
}

MIN_LIBVIRT_VERSION = (0, 9, 6)
MIN_LIBVIRT_HOST_CPU_VERSION = (0, 9, 10)
# Live snapshot requirements
REQ_HYPERVISOR_LIVESNAPSHOT = "QEMU"
MIN_LIBVIRT_LIVESNAPSHOT_VERSION = (1, 0, 0)
MIN_QEMU_LIVESNAPSHOT_VERSION = (1, 3, 0)


class LibvirtDriver(driver.ComputeDriver):

    capabilities = {
        "live_snapshot": True,
    }

    def __init__(self, virtapi, read_only=False):
        super(LibvirtDriver, self).__init__(virtapi)

        global libvirt
        if libvirt is None:
            libvirt = __import__('libvirt')

        self._wrapped_conn = None
        self.read_only = read_only
        self.snaps_data = {}

    def has_min_version(self, lv_ver=None, hv_ver=None, hv_type=None):
        def _munge_version(ver):
            return ver[0] * 1000000 + ver[1] * 1000 + ver[2]

        try:
            if lv_ver is not None:
                libvirt_version = self._conn.getLibVersion()
                if libvirt_version < _munge_version(lv_ver):
                    return False

            if hv_ver is not None:
                hypervisor_version = self._conn.getVersion()
                if hypervisor_version < _munge_version(hv_ver):
                    return False

            if hv_type is not None:
                hypervisor_type = self._conn.getType()
                if hypervisor_type != hv_type:
                    return False

            return True
        except Exception:
            return False

    def _get_connection(self):
        if not self._wrapped_conn or not self._test_connection():
            LOG.debug(_('Connecting to libvirt: %s'), self.uri())
            if not CONF.libvirt_nonblocking:
                self._wrapped_conn = self._connect(self.uri(),
                                                   self.read_only)
            else:
                self._wrapped_conn = tpool.proxy_call(
                    (libvirt.virDomain, libvirt.virConnect),
                    self._connect, self.uri(), self.read_only)

            try:
                LOG.debug("Registering for lifecycle events %s" % str(self))
                self._wrapped_conn.domainEventRegisterAny(
                    None,
                    libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                    self._event_lifecycle_callback,
                    self)
            except Exception as e:
                LOG.warn(_("URI %s does not support events"),
                         self.uri())

        return self._wrapped_conn

    _conn = property(_get_connection)

    def _test_connection(self):
        try:
            self._wrapped_conn.getLibVersion()
            return True
        except libvirt.libvirtError as e:
            if (e.get_error_code() in (libvirt.VIR_ERR_SYSTEM_ERROR,
                                       libvirt.VIR_ERR_INTERNAL_ERROR) and
                e.get_error_domain() in (libvirt.VIR_FROM_REMOTE,
                                         libvirt.VIR_FROM_RPC)):
                LOG.debug(_('Connection to libvirt broke'))
                return False
            raise

    @staticmethod
    def uri():
        uri = CONF.libvirt_uri or 'qemu:///system'
        return uri

    @staticmethod
    def _connect(uri, read_only):
        def _connect_auth_cb(creds, opaque):
            if len(creds) == 0:
                return 0
            LOG.warning(
                _("Can not handle authentication request for %d credentials")
                % len(creds))
            raise exception.WorkloadMgrException(
                _("Can not handle authentication request for %d credentials")
                % len(creds))

        auth = [[libvirt.VIR_CRED_AUTHNAME,
                 libvirt.VIR_CRED_ECHOPROMPT,
                 libvirt.VIR_CRED_REALM,
                 libvirt.VIR_CRED_PASSPHRASE,
                 libvirt.VIR_CRED_NOECHOPROMPT,
                 libvirt.VIR_CRED_EXTERNAL],
                _connect_auth_cb,
                None]

        try:
            if read_only:
                return libvirt.openReadOnly(uri)
            else:
                return libvirt.openAuth(uri, auth, 0)
        except libvirt.libvirtError as ex:
            LOG.exception(_("Connection to libvirt failed: %s"), ex)
            pass

    def instance_exists(self, instance_name):
        """Efficient override of base instance_exists method."""
        try:
            self._lookup_by_name(instance_name)
            return True
        except exception.WorkloadMgrException:
            return False

    def list_instance_ids(self):
        if self._conn.numOfDomains() == 0:
            return []
        return self._conn.listDomainsID()

    def list_instances(self):
        names = []
        for domain_id in self.list_instance_ids():
            try:
                # We skip domains with ID 0 (hypervisors).
                if domain_id != 0:
                    domain = self._conn.lookupByID(domain_id)
                    names.append(domain.name())
            except libvirt.libvirtError:
                # Instance was deleted while listing... ignore it
                pass

        # extend instance list to contain also defined domains
        names.extend([vm for vm in self._conn.listDefinedDomains()
                      if vm not in names])

        return names

    def list_instance_uuids(self):
        return [self._conn.lookupByName(name).UUIDString()
                for name in self.list_instances()]

    def get_instance_name_by_uuid(self, instance_id):
        for name in self.list_instances():
            if self._conn.lookupByName(name).UUIDString() == instance_id:
                return name
        return None

    @staticmethod
    def _get_disk_xml(xml, device):
        """Returns the xml for the disk mounted at device."""
        try:
            doc = etree.fromstring(xml)
        except Exception:
            return None
        ret = doc.findall('./devices/disk')
        for node in ret:
            for child in node.getchildren():
                if child.tag == 'target':
                    if child.get('dev') == device:
                        return etree.tostring(node)

    @staticmethod
    def get_host_ip_addr():
        return CONF.my_ip

    def _lookup_by_name(self, instance_name):
        """Retrieve libvirt domain object given an instance name.

        All libvirt error handling should be handled in this method and
        relevant workloadmgr exceptions should be raised in response.

        """
        try:
            return self._conn.lookupByName(instance_name)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=instance_name)

            msg = _(
                "Error from libvirt while looking up %(instance_name)s: "
                "[Error Code %(error_code)s] %(ex)s") % locals()
            raise exception.WorkloadMgrException(msg)

    def get_info(self, instance_name):
        """Retrieve information from libvirt for a specific instance name.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        """
        virt_dom = self._lookup_by_name(instance_name)
        (state, max_mem, mem, num_cpu, cpu_time) = virt_dom.info()
        return {'state': LIBVIRT_POWER_STATE[state],
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time,
                'id': virt_dom.ID(),
                'uuid': virt_dom.ID()}

    def get_disks(self, instance_name):
        """
        Note that this function takes an instance name.
        Returns a list of all block devices( vda, vdb ....) for this domain.

        """
        domain = self._lookup_by_name(instance_name)
        xml = domain.XMLDesc(0)

        try:
            doc = etree.fromstring(xml)
        except Exception:
            return []

        return filter(bool,
                      [target.get("dev")
                       for target in doc.findall('devices/disk/target')])

    @autolog.log_method(Logger, 'libvirt.driver.snapshot_mount')
    def snapshot_mount(self, cntx, db, snapshot, diskfiles, mount_vm_id=None):

        def _reboot_fminstance():
            # reboot the file manager server
            # If the server does not exists, create a server
            fminstance = compute_service.get_server_by_id(cntx, mount_vm_id,
                                                          admin=False)
            if fminstance is None:
                raise Exception("TrilioVault File Manager does not exists")

            compute_service.reboot(cntx, fminstance, reboot_type='HARD')
            start_time = timeutils.utcnow()
            while True:
                time.sleep(1)
                fminstance = compute_service.get_server_by_id(
                    cntx, fminstance.id, admin=False)
                if not fminstance.__dict__['OS-EXT-STS:task_state']:
                    break
                now = timeutils.utcnow()
                if (now - start_time) > datetime.timedelta(minutes=5):
                    raise exception.ErrorOccurred(
                        reason='Timeout rebooting file manager instance')

            if fminstance.status.lower() != "active":
                raise Exception("File Manager VM is not rebooted successfully")

            time.sleep(CONF.hard_reboot_wait)
            return fminstance

        def _map_snapshot_images(fminstance):
            workload_obj = db.workload_get(cntx, snapshot.workload_id)
            backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                    'backup_media_target')
            metadata = {
                'resource_id': mount_vm_id + "_" + str(int(time.time())),
                'backend_endpoint': backup_endpoint,
                'snapshot_id': snapshot.id
            }
            status = self._vast_methods_call_by_function(
                compute_service.map_snapshot_files, cntx, fminstance.id, {
                    'diskfiles': diskfiles, 'metadata': metadata})
            self._wait_for_remote_nova_process(cntx, compute_service,
                                               metadata,
                                               fminstance.id,
                                               backup_endpoint)

        compute_service = nova.API(production=True)
        fminstance = _reboot_fminstance()
        _map_snapshot_images(fminstance)
        return fminstance

    @autolog.log_method(Logger, 'libvirt.driver.snapshot_dismount')
    def snapshot_dismount(self, cntx, snapshot, devpaths, mount_vm_id=None):
        def _reboot_fminstance():
            # reboot the file manager server
            # If the server does not exists, create a server
            fminstance = compute_service.get_server_by_id(cntx, mount_vm_id,
                                                          admin=False)
            if fminstance is None:
                LOG.warning("TrilioVault File Manager does not exists")
            else:

                compute_service.reboot(cntx, fminstance, reboot_type='HARD')
                start_time = timeutils.utcnow()
                while True:
                    time.sleep(1)
                    fminstance = compute_service.get_server_by_id(
                        cntx, fminstance.id, admin=False)
                    if not fminstance.__dict__['OS-EXT-STS:task_state']:
                        break
                    now = timeutils.utcnow()
                    if (now - start_time) > datetime.timedelta(minutes=4):
                        raise exception.ErrorOccurred(
                            reason='Timeout rebooting file manager instance')

                if fminstance.status.lower() != "active":
                    raise Exception(
                        "File Manager VM is not rebooted successfully")

            return fminstance
        compute_service = nova.API(production=True)
        fminstance = _reboot_fminstance()

    def rebase_vmdk(self, base, orig_base, base_descriptor,
                    top, orig_top, top_descriptor):
        """
        rebase the top to base
        """
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
                (' "' + orig_base_filename + '"'),
                (' "' + base_extent_filename + '"'))
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

    def commit_vmdk(self, file_to_commit, commit_to, test):
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
            utils.execute('qemu-img', 'convert', '-f', 'vmdk', '-O', 'raw',
                          commit_to, commit_to.replace(".vmdk",
                          ".img"), run_as_root=False)
            return commit_to.replace(".vmdk", ".img")
        else:
            return commit_to.replace(".vmdk", "-flat.vmdk")
        """

    @autolog.log_method(Logger, 'libvirt.driver.pre_snapshot_vm')
    def pre_snapshot_vm(self, cntx, db, instance, snapshot):

        compute_service = nova.API(production=True)
        vast_params = {'test1': 'test1', 'test2': 'test2'}
        compute_service.vast_prepare(cntx, instance['vm_id'], vast_params)

    @autolog.log_method(Logger, 'libvirt.driver.freeze_vm')
    def freeze_vm(self, cntx, db, instance):

        compute_service = nova.API(production=True)
        vast_params = {'test1': 'test1', 'test2': 'test2'}
        compute_service.vast_freeze(cntx, instance['vm_id'], vast_params)

    @autolog.log_method(Logger, 'libvirt.driver.thaw_vm')
    def thaw_vm(self, cntx, db, instance):

        compute_service = nova.API(production=True)
        vast_params = {'test1': 'test1', 'test2': 'test2'}
        compute_service.vast_thaw(cntx, instance['vm_id'], vast_params)

    @autolog.log_method(Logger, 'vmwareapi.driver.enable_cbt')
    def enable_cbt(self, cntx, db, instance):
        pass

    def _vast_methods_call_by_function(self, func, *args):
        status = {'result': 'retry'}
        try:
            status = func(*args)
        except nova_unauthorized as ex:
            LOG.exception(ex)
            cntx = nova._get_tenant_context(cntx)
        except Exception as ex:
            LOG.exception(ex)
            raise ex
        return status

    def _wait_for_remote_nova_process(self, cntx, compute_service,
                                      progress_tracker_metadata,
                                      instance_id, backup_endpoint,
                                      db=None, vault_url=None,
                                      calc_size=False):
        start_time = timeutils.utcnow()
        operation_completed = False
        backup_target = vault.get_backup_target(backup_endpoint)
        progress_tracking_file_path = backup_target.get_progress_tracker_path(
            progress_tracker_metadata)
        if calc_size is True:
            uploaded_size = 0
            uploaded_size_incremental = 0
            previous_uploaded_size = 0

        while True:
            try:
                if CONF.vault_storage_type == 'nfs':
                    time.sleep(10)
                else:
                    time.sleep(120)
                async_task_status = {}
                if progress_tracking_file_path:
                    try:
                        with open(progress_tracking_file_path, 'r') as progress_tracking_file:
                            async_task_status['status'] = progress_tracking_file.readlines(
                            )
                        try:
                            if calc_size is True:
                                totalbytes = backup_target.get_object_size(
                                    vault_url)
                                if totalbytes:
                                    uploaded_size_incremental = totalbytes - previous_uploaded_size
                                    uploaded_size = totalbytes
                                    snapshot_obj = db.snapshot_update(
                                        cntx, progress_tracker_metadata['snapshot_id'], {
                                            'uploaded_size_incremental': uploaded_size_incremental})
                                    previous_uploaded_size = uploaded_size
                        except Exception as ex:
                            LOG.exception(ex)

                    except Exception as ex:
                        async_task_status = compute_service.vast_async_task_status(
                            cntx, instance_id, {'metadata': progress_tracker_metadata})

                else:
                    async_task_status = compute_service.vast_async_task_status(
                        cntx, instance_id, {'metadata': progress_tracker_metadata})
                if async_task_status and 'status' in async_task_status and len(
                        async_task_status['status']):
                    for line in async_task_status['status']:
                        if 'Down' in line:
                            raise Exception(
                                "Contego service Unreachable - " + line)
                        if 'Error' in line:
                            raise Exception("Data transfer failed - " + line)
                        if 'Completed' in line:
                            operation_completed = True
                            return True

                now = timeutils.utcnow()
                if (now - start_time) > datetime.timedelta(
                        minutes=5) and CONF.vault_storage_type == 'swift-s':
                    try:
                        async_task_status_swift = compute_service.vast_async_task_status(
                            cntx, instance_id, {'metadata': progress_tracker_metadata, 'fetched': True})
                    except BaseException:
                        async_task_status_swift = None
                    start_time = timeutils.utcnow()
                    if async_task_status_swift and 'status' in async_task_status_swift and len(
                            async_task_status_swift['status']):
                        for line in async_task_status['status']:
                            if 'Completed' in line:
                                operation_completed = True
                                return True
                            if '100.0 %' in line:
                                operation_completed = True
                                return True
                    elif calc_size is False:
                        if async_task_status_swift and 'disks_info' in async_task_status_swift and len(
                                async_task_status_swift['disks_info']):
                            if len(
                                    async_task_status_swift['disks_info'][0]) > 2:
                                operation_completed = True
                                self.snaps_data[instance_id] = {
                                    'fetched': True, 'snaps': async_task_status_swift}
                                return async_task_status_swift
            except nova_unauthorized as ex:
                LOG.exception(ex)
                cntx = nova._get_tenant_context(cntx)
            except Exception as ex:
                LOG.exception(ex)
                raise ex
            now = timeutils.utcnow()
            if (now - start_time) > datetime.timedelta(minutes=10 * 60):
                raise exception.ErrorOccurred(reason='Timeout uploading data')

    @autolog.log_method(Logger, 'libvirt.driver.snapshot_vm')
    def snapshot_vm(self, cntx, db, instance, snapshot):
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)

        backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                'backup_media_target')

        compute_service = nova.API(production=True)
        vast_params = {'snapshot_id': snapshot_obj.id,
                       'workload_id': workload_obj.id,
                       'instance_vm_id': instance['vm_id'],
                       'backend_endpoint': backup_endpoint}

        status = self._vast_methods_call_by_function(
            compute_service.vast_instance, cntx, instance['vm_id'], vast_params)

        progress_tracker_metadata = {'snapshot_id': snapshot['id'],
                                     'resource_id': instance['vm_id'],
                                     'backend_endpoint': backup_endpoint}
        ret = self._wait_for_remote_nova_process(cntx, compute_service,
                                                 progress_tracker_metadata,
                                                 instance['vm_id'],
                                                 backup_endpoint)
        # if ret is not True and ret is not False:
        #   snapshot_data = ret
        if instance['vm_id'] in self.snaps_data and \
           self.snaps_data[instance['vm_id']]['fetched'] is True:

            snapshot_data = self.snaps_data[instance['vm_id']]['snaps']
            self.snaps_data.pop(instance['vm_id'])
            return snapshot_data

        try:
            snapshot_data = compute_service.vast_async_task_status(
                cntx, instance['vm_id'], {
                    'metadata': progress_tracker_metadata, 'fetched': True})
        except nova_unauthorized as ex:
            LOG.exception(ex)
            cntx = nova._get_tenant_context(cntx)
        except Exception as ex:
            LOG.exception(ex)
            raise ex

        return snapshot_data

    @autolog.log_method(Logger, 'libvirt.driver.reset_vm')
    def reset_vm(self, cntx, workload_id, instance_uuid):
        compute_service = nova.API(production=True)
        vast_params = {'workload_id': workload_id}
        compute_service.vast_reset(cntx, instance_uuid, vast_params)
        return

    @autolog.log_method(Logger, 'libvirt.driver._get_snapshot_disk_info')
    def _get_snapshot_disk_info(
            self, cntx, db, instance, snapshot, snapshot_data):
        compute_service = nova.API(production=True)
        snapshot_data_ex = compute_service.vast_get_info(
            cntx, instance['vm_id'], snapshot_data)
        return snapshot_data_ex

    @autolog.log_method(
        Logger,
        'libvirt.driver._get_backing_snapshot_vm_resource_vm_disk_resource_snap')
    def _get_backing_snapshot_vm_resource_vm_disk_resource_snap(
            self, cntx, db, instance, snapshot, disk_info):
        snapshot_vm_resource_backing = None
        vm_disk_resource_snap_backing = None
        try:
            snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
            workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
            snapshots = db.snapshot_get_all_by_project_workload(
                cntx, cntx.project_id, workload_obj.id)
            for snap in snapshots:
                if snap.status != "available" and snap.status != "mounted":
                    continue
                snapshot_vm_resource_backing = db.snapshot_vm_resource_get_by_resource_name(
                    cntx, instance['vm_id'], snap.id, disk_info['dev'])
                vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get_top(
                    cntx, snapshot_vm_resource_backing.id)
                for meta in snapshot_vm_resource_backing.metadata:
                    if meta['key'] == 'disk_info':
                        backing_disk_info = json.loads(meta['value'])
                        if disk_info['backend'] == 'qcow2':
                            if backing_disk_info['path'] != (
                                    disk_info['backings'][0]['path']):
                                return None, None
                        disk_info['prev_disk_info'] = json.loads(meta['value'])
                        break
                break
        except Exception as ex:
            LOG.exception(ex)
            return None, None
        return snapshot_vm_resource_backing, vm_disk_resource_snap_backing

    @autolog.log_method(Logger, 'libvirt.driver.get_snapshot_data_size')
    def get_snapshot_data_size(
            self, cntx, db, instance, snapshot, snapshot_data):
        vm_data_size = 0
        snapshot_data_ex = self._get_snapshot_disk_info(
            cntx, db, instance, snapshot, snapshot_data)
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)

        for disk_info in snapshot_data_ex['disks_info']:
            LOG.debug(_("    disk: %(disk)s") % {'disk': disk_info['dev'], })

            snapshot_vm_resource_backing = None
            vm_disk_resource_snap_backing = None
            disk_info['prev_disk_info'] = None

            try:
                if snapshot_obj.snapshot_type != 'full':
                    snapshot_vm_resource_backing, vm_disk_resource_snap_backing = \
                        self._get_backing_snapshot_vm_resource_vm_disk_resource_snap(
                            cntx, db, instance, snapshot, disk_info)
            except Exception as ex:
                LOG.info(_("No previous snapshots found"))

            if snapshot_vm_resource_backing:
                backings = [disk_info['backings'][0]]
            else:
                backings = disk_info['backings'][::-1]  # reverse the list

            vm_disk_size = 0
            for i, backing in enumerate(backings):
                vm_disk_size = vm_disk_size + backing['size']
                if snapshot['snapshot_type'] == 'full':
                    break
            LOG.debug(_("    vm_data_size: %(vm_data_size)s") %
                      {'vm_data_size': vm_data_size, })
            LOG.debug(_("    vm_disk_size: %(vm_disk_size)s") %
                      {'vm_disk_size': vm_disk_size, })
            vm_data_size = vm_data_size + vm_disk_size
            LOG.debug(_("vm_data_size: %(vm_data_size)s") %
                      {'vm_data_size': vm_data_size, })

        snapshot_data_ex['vm_data_size'] = vm_data_size
        return snapshot_data_ex

    @autolog.log_method(Logger, 'libvirt.driver.upload_snapshot')
    def upload_snapshot(self, cntx, db, instance, snapshot, snapshot_data_ex):
        # Always attempt with a new token to avoid timeouts

        cntx = nova._get_tenant_context(cntx)
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        compute_service = nova.API(production=True)
        image_service = glance.GlanceImageService()
        volume_service = cinder.API()

        backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                'backup_media_target')
        backup_target = vault.get_backup_target(backup_endpoint)
        nova_instance = compute_service.get_server_by_id(
            cntx, instance['vm_id'])
        cinder_volumes = []
        for volume in getattr(nova_instance,
                              'os-extended-volumes:volumes_attached'):
            cinder_volumes.append(
                volume_service.get(
                    cntx,
                    volume['id'],
                    no_translate=True))

        for disk_info in snapshot_data_ex['disks_info']:
            # Always attempt with a new token to avoid timeouts
            cntx = nova._get_tenant_context(cntx)

            snapshot_vm_resource_metadata = {
                'disk_info': json.dumps(disk_info)}
            if disk_info['dev'] in ('vda', 'sda') and nova_instance.image and len(
                    nova_instance.image) > 0:
                try:
                    glance_image = image_service.show(
                        cntx, nova_instance.image['id'])
                    snapshot_vm_resource_metadata['image_id'] = glance_image['id']
                    snapshot_vm_resource_metadata['image_name'] = glance_image['name']
                    snapshot_vm_resource_metadata['container_format'] = glance_image['container_format']
                    snapshot_vm_resource_metadata['disk_format'] = glance_image['disk_format']
                    snapshot_vm_resource_metadata['min_ram'] = glance_image['min_ram']
                    snapshot_vm_resource_metadata['min_disk'] = glance_image['min_disk']
                    if 'hw_qemu_guest_agent' in glance_image['properties'].keys():
                        snapshot_vm_resource_metadata['hw_qemu_guest_agent'] = glance_image['properties']['hw_qemu_guest_agent']
                except exception.ImageNotFound as ex:
                    snapshot_vm_resource_metadata['image_id'] = uuid.uuid4()
                    snapshot_vm_resource_metadata['image_name'] = "TrilioVault-Image-Placeholder"
                    snapshot_vm_resource_metadata['container_format'] = "bare"
                    snapshot_vm_resource_metadata['disk_format'] = "qcow2"
            else:
                snapshot_vm_resource_metadata['image_id'] = None

            for cinder_volume in cinder_volumes:
                cinder_volume = cinder_volume.__dict__
                if 'name' in cinder_volume:
                    cinder_volume['display_name'] = cinder_volume['name']

                for attachment in cinder_volume['attachments']:
                    if attachment['server_id'] == instance['vm_id']:
                        if disk_info['dev'] in attachment['device']:
                            snapshot_vm_resource_metadata['volume_id'] = cinder_volume['id']
                            snapshot_vm_resource_metadata['volume_name'] = cinder_volume['display_name'] or \
                                snapshot_vm_resource_metadata['volume_id']

                            if 'display_description' in cinder_volume.keys():
                                description = cinder_volume['display_description']
                            elif 'description' in cinder_volume.keys():
                                description = cinder_volume['description']
                            else:
                                description = ''
                            snapshot_vm_resource_metadata['volume_description'] = description
                            snapshot_vm_resource_metadata['volume_size'] = cinder_volume['size']
                            snapshot_vm_resource_metadata['volume_type'] = cinder_volume['volume_type']
                            snapshot_vm_resource_metadata['volume_mountpoint'] = attachment['device']
                            snapshot_vm_resource_metadata['availability_zone'] = cinder_volume['availability_zone']
                            break
                if 'volume_id' in snapshot_vm_resource_metadata:
                    break

            vm_disk_size = 0
            db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])
            snapshot_vm_resource_values = {
                'id': str(
                    uuid.uuid4()),
                'vm_id': instance['vm_id'],
                'snapshot_id': snapshot_obj.id,
                'resource_type': 'disk',
                'resource_name': disk_info['dev'],
                'resource_pit_id': disk_info['path'],
                'metadata': snapshot_vm_resource_metadata,
                'status': 'creating'}
            snapshot_vm_resource = db.snapshot_vm_resource_create(
                cntx, snapshot_vm_resource_values)

            snapshot_vm_resource_backing = None
            vm_disk_resource_snap_backing = None
            disk_info['prev_disk_info'] = None

            try:
                if snapshot_obj.snapshot_type != 'full':
                    snapshot_vm_resource_backing, vm_disk_resource_snap_backing = \
                        self._get_backing_snapshot_vm_resource_vm_disk_resource_snap(
                            cntx, db, instance, snapshot, disk_info)
            except Exception as ex:
                LOG.info(
                    _("No previous snapshots found. Performing full snapshot"))

            # Make sure the previous snapshot exists in cinder.
            # if not, fall back to full snapshot
            if snapshot_vm_resource_backing:
                status = compute_service.vast_check_prev_snapshot(
                    cntx, instance['vm_id'], {'disk_info': disk_info, })

                if status['result'] != 'success':
                    LOG.info(
                        _("No previous snapshots found. Performing full snapshot"))
                    snapshot_vm_resource_backing = None
                    vm_disk_resource_snap_backing = None
                    disk_info['prev_disk_info'] = None

            if snapshot_vm_resource_backing:
                backings = [disk_info['backings'][0]]
            else:
                backings = disk_info['backings'][::-1]  # reverse the list

            for i, backing in enumerate(backings):
                vm_disk_resource_snap_id = str(uuid.uuid4())
                vm_disk_resource_snap_metadata = {}  # Dictionary to hold the metadata
                vm_disk_resource_snap_metadata['disk_format'] = 'qcow2'

                if vm_disk_resource_snap_backing:
                    vm_disk_resource_snap_backing_id = vm_disk_resource_snap_backing.id
                else:
                    vm_disk_resource_snap_backing_id = None

                vm_disk_resource_snap_values = {
                    'id': vm_disk_resource_snap_id,
                    'snapshot_vm_resource_id': snapshot_vm_resource.id,
                    'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                    'metadata': vm_disk_resource_snap_metadata,
                    'top': (
                        (i + 1) == len(backings)),
                    'size': backing['size'],
                    'status': 'creating'}

                vm_disk_resource_snap = db.vm_disk_resource_snap_create(
                    cntx, vm_disk_resource_snap_values)
                progress_tracker_metadata = {
                    'backup_endpoint': backup_endpoint,
                    'snapshot_id': snapshot['id'],
                    'resource_id': vm_disk_resource_snap_id
                }
                progress_tracking_file_path = backup_target.get_progress_tracker_path(
                    progress_tracker_metadata)

                # upload to backup store
                snapshot_vm_disk_resource_metadata = {
                    'workload_id': snapshot['workload_id'],
                    'workload_name': workload_obj.display_name,
                    'snapshot_id': snapshot['id'],
                    'snapshot_vm_id': instance['vm_id'],
                    'snapshot_vm_name': instance['vm_name'],
                    'snapshot_vm_resource_id': snapshot_vm_resource.id,
                    'snapshot_vm_resource_name': disk_info['dev'],
                    'vm_disk_resource_snap_id': vm_disk_resource_snap_id,
                    'progress_tracking_file_path': progress_tracking_file_path,
                    'backend_endpoint': backup_endpoint}

                vault_url = backup_target.get_snapshot_vm_disk_resource_path(
                    snapshot_vm_disk_resource_metadata)

                snapshot_obj = db.snapshot_update(
                    cntx,
                    snapshot_obj.id,
                    {
                        'progress_msg': 'Waiting for Uploading ' + disk_info['dev'] + ' of VM:' + instance['vm_id'],
                        'status': 'wait_to_be_uploading'})

                status = {'result': 'retry'}
                while status['result'] == 'retry':
                    status = self._vast_methods_call_by_function(
                        compute_service.vast_data_transfer, cntx, instance['vm_id'], {
                            'path': backing['path'], 'metadata': snapshot_vm_disk_resource_metadata, 'disk_info': disk_info})
                    if status['result'] == 'retry':
                        LOG.debug(
                            _('tvault-contego returned "retry". Waiting for 60 seconds before retry'))
                        time.sleep(60)

                snapshot_obj = db.snapshot_update(
                    cntx,
                    snapshot_obj.id,
                    {
                        'progress_msg': 'Uploading ' + disk_info['dev'] + ' of VM:' + instance['vm_id'],
                        'status': 'uploading'})

                LOG.debug(_('Uploading ' +
                            disk_info['dev'] +
                            ' of VM:' +
                            instance['vm_id'] +
                            '; backing file:' +
                            os.path.basename(backing['path'])))

                progress_tracker_metadata = {
                    'snapshot_id': snapshot['id'],
                    'backup_endpoint': backup_endpoint,
                    'resource_id': vm_disk_resource_snap_id}
                self._wait_for_remote_nova_process(cntx, compute_service,
                                                   progress_tracker_metadata,
                                                   instance['vm_id'],
                                                   backup_endpoint,
                                                   db=db, vault_url=vault_url,
                                                   calc_size=True)

                snapshot_obj = db.snapshot_update(
                    cntx,
                    snapshot_obj.id,
                    {
                        'progress_msg': 'Uploaded ' + disk_info['dev'] + ' of VM:' + instance['vm_id'],
                        'status': 'uploading'})

                # update the entry in the vm_disk_resource_snap table
                vm_disk_resource_snap_values = {
                    'vault_url': vault_url.replace(
                        backup_target.mount_path,
                        '',
                        1),
                    'vault_service_metadata': 'None',
                    'finished_at': timeutils.utcnow(),
                    'time_taken': int(
                        (timeutils.utcnow() - vm_disk_resource_snap.created_at).total_seconds()),
                    'size': backing['size'],
                    'status': 'available'}
                vm_disk_resource_snap = db.vm_disk_resource_snap_update(
                    cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
                if vm_disk_resource_snap_backing:
                    vm_disk_resource_snap_backing = db.vm_disk_resource_snap_update(
                        cntx, vm_disk_resource_snap_backing.id,
                        {'vm_disk_resource_snap_child_id': vm_disk_resource_snap.id})
                    # Upload snapshot metadata to the vault
                    snapshot_vm_resource_backing = db.snapshot_vm_resource_get(
                        cntx, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                    workload_utils.upload_snapshot_db_entry(
                        cntx, snapshot_vm_resource_backing.snapshot_id)
                    # Update the qcow2 backings
                    # Give enough time for the backend to settle down
                    time.sleep(20)
                    resource_snap_backing_path = os.path.join(
                        backup_target.mount_path,
                        vm_disk_resource_snap_backing.vault_url.strip(os.sep))
                    resource_snap_path = os.path.join(
                        backup_target.mount_path,
                        vm_disk_resource_snap.vault_url.strip(os.sep))
                    try:
                        """os.listdir(os.path.join(backup_target.mount_path, 'workload_'+snapshot_obj.workload_id,
                                   'snapshot_'+snapshot_obj.id))"""
                        os.listdir(os.path.split(resource_snap_path)[0])
                    except Exception as ex:
                        pass
                    qemuimages.rebase_qcow2(resource_snap_backing_path,
                                            resource_snap_path)

                vm_disk_size = vm_disk_size + backing['size']
                vm_disk_resource_snap_backing = vm_disk_resource_snap

            snapshot_type = 'incremental'
            vm_disk_resource_snaps = db.vm_disk_resource_snaps_get(
                cntx, snapshot_vm_resource.id)
            for vm_disk_resource_snap in vm_disk_resource_snaps:
                if vm_disk_resource_snap.vm_disk_resource_snap_backing_id is None:
                    snapshot_type = 'full'

            db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id,
                                           {'snapshot_type': snapshot_type,
                                            'status': 'available',
                                            'size': vm_disk_size})

    @autolog.log_method(Logger, 'libvirt.driver.post_snapshot_vm')
    def post_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_data):
        compute_service = nova.API(production=True)
        self.vast_finalize(cntx, compute_service, db,
                           instance, snapshot,
                           snapshot_data)

    @autolog.log_method(Logger, 'libvirt.driver.revert_snapshot_vm')
    def revert_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_data):
        compute_service = nova.API(production=True)
        self.vast_finalize(cntx, compute_service, db,
                           instance, snapshot,
                           snapshot_data, failed=True)

    @autolog.log_method(Logger, 'libvirt.driver.delete_restored_vm')
    def delete_restored_vm(self, cntx, db, instance, restore):
        vms = db.restored_vms_get(cntx, restore['id'])
        compute_service = nova.API(production=True)
        for vm in vms:
            instance = compute_service.get_server_by_id(
                cntx, vm.vm_id, admin=False)
            compute_service.force_delete(cntx, instance)
            db.restored_vm_update(
                cntx, vm.vm_id, restore['id'], {
                    'status': 'deleted'})

    @autolog.log_method(Logger, 'libvirt.driver.pre_restore_vm')
    def pre_restore_vm(self, cntx, db, instance, restore):
        pass

    @autolog.log_method(Logger, 'libvirt.driver.restore_vm')
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
            restore_obj = db.restore_get(cntx, restore['id'])
            result = restore_vm_flow.restore_vm(
                cntx,
                db,
                instance,
                restore,
                restored_net_resources,
                restored_security_groups,
                restored_compute_flavor,
                restored_nics,
                instance_options)
            return result
        except Exception as ex:
            LOG.exception(ex)
            raise
        finally:
            try:
                #workload_utils.purge_snapshot_vm_from_staging_area(cntx, restore_obj.snapshot_id, instance['vm_id'])
                pass
            except Exception as ex:
                LOG.exception(ex)
            try:
                workload_utils.purge_restore_vm_from_staging_area(
                    cntx, restore_obj.id, restore_obj.snapshot_id, instance['vm_id'])
            except Exception as ex:
                LOG.exception(ex)

    @autolog.log_method(Logger, 'libvirt.driver.restore_vm_data')
    def restore_vm_data(self, cntx, db, instance, restore, instance_options):
        """
        Inplace restore specified instance from a snapshot
        """
        try:
            restore_obj = db.restore_get(cntx, restore['id'])
            result = restore_vm_data_flow.restore_vm_data(
                cntx, db, instance, restore, instance_options)
            return result
        except Exception as ex:
            LOG.exception(ex)
            raise
        finally:
            pass

    @autolog.log_method(Logger, 'libvirt.driver.vast_finalize')
    def vast_finalize(self, cntx, compute_service, db,
                      instance, snapshot,
                      snapshot_data_ex, failed=False):
        cntx = nova._get_tenant_context(cntx)

        workload_obj = db.workload_get(cntx, snapshot['workload_id'])
        backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                'backup_media_target')
        snapshot_data_ex['metadata'] = {'snapshot_id': snapshot['id'],
                                        'snapshot_vm_id': instance['vm_id'],
                                        'backend_endpoint': backup_endpoint}
        snapshot_data_ex['workload_failed'] = failed

        while True:
            try:
                result = self._vast_methods_call_by_function(
                    compute_service.vast_finalize,
                    cntx, instance['vm_id'],
                    snapshot_data_ex)
                if type(result).__name__ == 'BadRequest':
                    if compute_service.get_server_by_id(
                            cntx, instance['vm_id'], admin=False) is not None:
                        continue
                break
            except Exception as ex:
                time.sleep(10)
                pass

        progress_tracker_metadata = {'snapshot_id': snapshot['id'],
                                     'backup_endpoint': backup_endpoint,
                                     'resource_id': instance['vm_id']}
        self._wait_for_remote_nova_process(cntx, compute_service,
                                           progress_tracker_metadata,
                                           instance['vm_id'],
                                           backup_endpoint)

        LOG.debug(_('VAST finalize completed for ' + instance['vm_id']))

    @autolog.log_method(Logger, 'libvirt.driver.post_restore_vm')
    def post_restore_vm(self, cntx, db, instance, restore):
        pass

    @autolog.log_method(Logger, 'libvirt.driver.apply_retention_policy')
    def apply_retention_policy(self, cntx, db, instances, snapshot):

        def _add_to_commit_list(
                vm_disk_resource_snap_to_commit,
                vm_disk_resource_snap_to_commit_backing):
            vault_path = os.path.join(
                backup_target.mount_path,
                vm_disk_resource_snap_to_commit.vault_url.lstrip(
                    os.sep))
            backing_vault_path = os.path.join(
                backup_target.mount_path,
                vm_disk_resource_snap_to_commit_backing.vault_url.lstrip(
                    os.sep))
            commit_image_list.append((vault_path, backing_vault_path))

        try:
            compute_service = nova.API(production=True)
            (snapshot_to_commit,
             snapshots_to_delete,
             affected_snapshots,
             workload_obj,
             snapshot_obj,
             swift) = workload_utils.common_apply_retention_policy(cntx,
                                                                   instances,
                                                                   snapshot)

            backup_endpoint = db.get_metadata_value(workload_obj.metadata,
                                                    'backup_media_target')
            backup_target = vault.get_backup_target(backup_endpoint)
            instance_ids = [instance['vm_id'] for instance in instances]
            if snapshot_to_commit and snapshot_to_commit.snapshot_type == 'full':
                for snap in snapshots_to_delete:
                    workload_utils.common_apply_retention_snap_delete(
                        cntx, snap, workload_obj)
            elif snapshot_to_commit:
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

                        snap_to_del = []  # Hold list of snapshot id's to delete
                        commit_image_list = []  # Hold the list of images need to commit with their backing image

                        vm_disk_resource_snap = vm_disk_resource_snap_to_commit = db.vm_disk_resource_snap_get_bottom(
                            cntx, snapshot_vm_resource.id)
                        if vm_disk_resource_snap_to_commit and vm_disk_resource_snap_to_commit.vm_disk_resource_snap_backing_id:
                            vm_disk_resource_snap_to_commit_backing = db.vm_disk_resource_snap_get(
                                cntx, vm_disk_resource_snap_to_commit.vm_disk_resource_snap_backing_id)
                            if vm_disk_resource_snap_to_commit_backing.snapshot_vm_resource_id != \
                                    vm_disk_resource_snap_to_commit.snapshot_vm_resource_id:

                                _add_to_commit_list(
                                    vm_disk_resource_snap_to_commit,
                                    vm_disk_resource_snap_to_commit_backing)
                                snap_to_del.append(
                                    vm_disk_resource_snap_to_commit.id)
                                vm_disk_resource_snap_to_commit = vm_disk_resource_snap_to_commit_backing
                                while vm_disk_resource_snap_to_commit and vm_disk_resource_snap_to_commit.vm_disk_resource_snap_backing_id:
                                    if vm_disk_resource_snap_to_commit.snapshot_vm_resource_id == \
                                            db.vm_disk_resource_snap_get_snapshot_vm_resource_id(cntx,
                                                                                                 vm_disk_resource_snap_to_commit.vm_disk_resource_snap_backing_id):
                                        vm_disk_resource_snap_to_commit_backing = db.vm_disk_resource_snap_get(
                                            cntx, vm_disk_resource_snap_to_commit.vm_disk_resource_snap_backing_id)

                                        _add_to_commit_list(
                                            vm_disk_resource_snap_to_commit, vm_disk_resource_snap_to_commit_backing)
                                        snap_to_del.append(
                                            vm_disk_resource_snap_to_commit.id)
                                        vm_disk_resource_snap_to_commit = vm_disk_resource_snap_to_commit_backing
                                    else:
                                        break

                                metadata = {
                                    'resource_id': snapshot_vm_resource['vm_id'] + '_' + str(int(time.time())),
                                    'backend_endpoint': backup_endpoint,
                                    'snapshot_id': snapshot_to_commit.id
                                }

                                # After one click restore snapshot_vm_resource['vm_id'] would be addressing to
                                # old vm_id which doesn't exist in Nova DB. So it will give ServerNotFound error
                                # To overcome this issue creating a check for vm_id. if it's not existing then
                                # passing a existing vm_id.
                                server_id = snapshot_vm_resource['vm_id']
                                if server_id not in instance_ids:
                                    server_id = instance_ids[0]

                                status = {'result': 'retry'}
                                while status['result'] == 'retry':
                                    status = self._vast_methods_call_by_function(
                                        compute_service.vast_commit_image, cntx, server_id, {
                                            'commit_image_list': commit_image_list, 'metadata': metadata})
                                    if status['result'] == 'retry':
                                        LOG.debug(
                                            _('tvault-contego returned "retry". Waiting for 60 seconds before retry.'))
                                        db.snapshot_update(
                                            cntx,
                                            snapshot['id'],
                                            {
                                                'progress_msg': 'Applying retention policy on vm:%s.' % server_id,
                                                'status': 'wait_to_apply_retention'})
                                        time.sleep(60)
                                db.snapshot_update(
                                    cntx,
                                    snapshot['id'],
                                    {
                                        'progress_msg': 'Applying retention policy on vm:%s.' % server_id,
                                        'status': 'applying_retention'})
                                self._wait_for_remote_nova_process(
                                    cntx, compute_service, metadata, snapshot_vm_resource['vm_id'], backup_endpoint)
                                for snapshot_del in snap_to_del:
                                    db.vm_disk_resource_snap_delete(
                                        cntx, snapshot_del)

                                if vm_disk_resource_snap_to_commit_backing:
                                    backing_vault_path = os.path.join(
                                        backup_target.mount_path,
                                        vm_disk_resource_snap_to_commit_backing.vault_url.lstrip(
                                            os.sep))
                                    vault_path = os.path.join(
                                        backup_target.mount_path,
                                        vm_disk_resource_snap.vault_url.lstrip(
                                            os.sep))
                                    shutil.move(backing_vault_path, vault_path)
                                    affected_snapshots = workload_utils.common_apply_retention_db_backing_update(
                                        cntx,
                                        snapshot_vm_resource,
                                        vm_disk_resource_snap,
                                        vm_disk_resource_snap_to_commit_backing,
                                        affected_snapshots)

                    #workload_utils.common_apply_retention_disk_check(cntx, snapshot_to_commit, snap, workload_obj)
            for snapshot_id in affected_snapshots:
                workload_utils.upload_snapshot_db_entry(cntx, snapshot_id)

            for snap in snapshots_to_delete:
                db.snapshot_update(
                    cntx, snap.id, {
                        'metadata': {
                            'deleted_by': 'retention'}})
                workload_utils.common_apply_retention_disk_check(
                    cntx, snapshot_to_commit, snap, workload_obj)

        except Exception as ex:
            msg = ''
            LOG.exception(ex)
            if hasattr(ex, 'kwargs'):
                if 'reason' in ex.kwargs:
                    msg = ex.kwargs['reason']
            elif hasattr(ex, 'message') and ex.message != '':
                msg = ex.message
            elif hasattr(ex, 'strerror') and ex.strerror != '':
                msg = ex.strerror

            db.snapshot_update(
                cntx, snapshot['id'], {
                    'warning_msg': 'Failed to apply retention policy - ' + msg})
