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

from workloadmgr.workflows import vmtasks_openstack
from workloadmgr.openstack.common import timeutils
from workloadmgr.workloads import workload_utils

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
            except Exception, e:
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

            msg = _("Error from libvirt while looking up %(instance_name)s: ""[Error Code %(error_code)s] %(ex)s") % locals()
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

    @autolog.log_method(Logger, 'libvirt.driver.pre_snapshot_vm')
    def pre_snapshot_vm(self, cntx, db, instance, snapshot):

        compute_service = nova.API(production=True)
        vast_params = {'test1': 'test1','test2': 'test2'}
        compute_service.vast_prepare(cntx, instance['vm_id'], vast_params) 
        
    @autolog.log_method(Logger, 'libvirt.driver.freeze_vm')
    def freeze_vm(self, cntx, db, instance, snapshot):

        compute_service = nova.API(production=True)
        vast_params = {'test1': 'test1','test2': 'test2'}
        compute_service.vast_freeze(cntx, instance['vm_id'], vast_params)    
        
    @autolog.log_method(Logger, 'libvirt.driver.thaw_vm')
    def thaw_vm(self, cntx, db, instance, snapshot):

        compute_service = nova.API(production=True)
        vast_params = {'test1': 'test1','test2': 'test2'}
        compute_service.vast_thaw(cntx, instance['vm_id'], vast_params)               

    @autolog.log_method(Logger, 'vmwareapi.driver.enable_cbt')
    def enable_cbt(self, cntx, db, instance):
        pass

    @autolog.log_method(Logger, 'libvirt.driver.snapshot_vm')
    def snapshot_vm(self, cntx, db, instance, snapshot):
        
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        
        compute_service = nova.API(production=True)
        vast_params = {'snapshot_id': snapshot_obj.id,
                       'workload_id': workload_obj.id}
        snapshot_data = compute_service.vast_instance(cntx, instance['vm_id'], vast_params)
        return snapshot_data 
        
    @autolog.log_method(Logger, 'libvirt.driver.get_snapshot_disk_info')
    def get_snapshot_disk_info(self, cntx, db, instance, snapshot, snapshot_data): 
        compute_service = nova.API(production=True)
        disks_info = compute_service.vast_get_info(cntx, instance['vm_id'], {})['info']
        return disks_info 
    
    @autolog.log_method(Logger, 'libvirt.driver.get_snapshot_data_size')
    def get_snapshot_data_size(self, cntx, db, instance, snapshot, snapshot_data):    
    
        vm_data_size = 0;
        disks_info = self.get_snapshot_disk_info(cntx, db, instance, snapshot, snapshot_data)     
        for disk_info in disks_info:
            LOG.debug(_("    disk: %(disk)s") %{'disk': disk_info['dev'],})
            vm_disk_size = 0
            pop_backings = True
            vm_disk_resource_snap_id = None
            if snapshot['snapshot_type'] != 'full':
                vm_recent_snapshot = db.vm_recent_snapshot_get(cntx, instance['vm_id'])
                if vm_recent_snapshot:
                    try:
                        previous_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_name(
                                                                        cntx, 
                                                                        instance['vm_id'], 
                                                                        vm_recent_snapshot.snapshot_id, 
                                                                        disk_info['dev'])
                    except Exception as ex:
                        LOG.exception(ex)
                        previous_snapshot_vm_resource = None                         
                    if previous_snapshot_vm_resource and previous_snapshot_vm_resource.status == 'available':
                        previous_vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, previous_snapshot_vm_resource.id)
                        if previous_vm_disk_resource_snap and previous_vm_disk_resource_snap.status == 'available':
                            vm_disk_resource_snap_id = previous_vm_disk_resource_snap.id
                            pop_backings = False                            
                            

            if len(disk_info['backings']) > 0 and pop_backings == True:
                base_backing_path = disk_info['backings'].pop()
            else:
                base_backing_path = disk_info
            
            
            while (base_backing_path != None):
                top_backing_path = None
                if len(disk_info['backings']) > 0 and pop_backings == True:
                    top_backing_path = disk_info['backings'].pop()
                vm_disk_size = vm_disk_size + base_backing_path['size']
                base_backing_path = top_backing_path

            LOG.debug(_("    vm_data_size: %(vm_data_size)s") %{'vm_data_size': vm_data_size,})
            LOG.debug(_("    vm_disk_size: %(vm_disk_size)s") %{'vm_disk_size': vm_disk_size,})
            vm_data_size = vm_data_size + vm_disk_size
            LOG.debug(_("vm_data_size: %(vm_data_size)s") %{'vm_data_size': vm_data_size,})
        
        snapshot_data['vm_data_size'] = vm_data_size
        return snapshot_data
    
    @autolog.log_method(Logger, 'libvirt.driver.upload_snapshot')
    def upload_snapshot(self, cntx, db, instance, snapshot, snapshot_data_ex):
        snapshot_obj = db.snapshot_get(cntx, snapshot['id'])
        workload_obj = db.workload_get(cntx, snapshot_obj.workload_id)
        compute_service = nova.API(production=True)

        disks_info = self.get_snapshot_disk_info(cntx, db, instance,
                                         snapshot, snapshot_data_ex)
        for disk_info in disks_info:

            db.snapshot_get_metadata_cancel_flag(cntx, snapshot['id'])

            vm_disk_size = 0
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                           'vm_id': instance['vm_id'],
                                           'snapshot_id': snapshot_obj.id,       
                                           'resource_type': 'disk',
                                           'resource_name': disk_info['dev'],
                                           'metadata': {'snapshot_data': json.dumps(snapshot_data_ex)},
                                           'status': 'creating'}

            snapshot_vm_resource = db.snapshot_vm_resource_create(cntx,
                                            snapshot_vm_resource_values)

            pop_backings = True                
            vm_disk_resource_snap_id = None
            previous_snapshot_data = None
            if snapshot['snapshot_type'] != 'full':
                #TODO(giri): the disk can be a new disk than the previous snapshot  
                vm_recent_snapshot = db.vm_recent_snapshot_get(cntx, instance['vm_id'])
                if vm_recent_snapshot:
                    try:
                        previous_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_name(
                                                                        cntx,
                                                                        instance['vm_id'],
                                                                        vm_recent_snapshot.snapshot_id,
                                                                        disk_info['dev'])
                    except Exception as ex:
                        LOG.exception(ex)
                        previous_snapshot_vm_resource = None
                    if previous_snapshot_vm_resource and previous_snapshot_vm_resource.status == 'available':
                        for meta in previous_snapshot_vm_resource.metadata:
                            if meta['key'] == 'snapshot_data':
                                previous_snapshot_data = json.loads(meta['value'])
                        previous_vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, previous_snapshot_vm_resource.id)
                        if previous_vm_disk_resource_snap and previous_vm_disk_resource_snap.status == 'available':
                            vm_disk_resource_snap_id = previous_vm_disk_resource_snap.id
                            pop_backings = False

            if len(disk_info['backings']) > 0 and pop_backings == True:
                base_backing_path = disk_info['backings'].pop()
            else:
                base_backing_path = disk_info

            while (base_backing_path != None):
                top_backing_path = None
                if len(disk_info['backings']) > 0 and pop_backings == True:
                    top_backing_path = disk_info['backings'].pop()

                # create an entry in the vm_disk_resource_snaps table
                vm_disk_resource_snap_backing_id = vm_disk_resource_snap_id
                vm_disk_resource_snap_id = str(uuid.uuid4())
                vm_disk_resource_snap_metadata = {} # Dictionary to hold the metadata
                if(disk_info['dev'] == 'vda' and top_backing_path == None):
                    vm_disk_resource_snap_metadata.setdefault('base_image_ref','TODO')
                vm_disk_resource_snap_metadata.setdefault('disk_format','qcow2')

                top = (top_backing_path == None)
                vm_disk_resource_snap_values = { 'id': vm_disk_resource_snap_id,
                                                 'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                 'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                                                 'metadata': vm_disk_resource_snap_metadata,
                                                 'top':  top,
                                                 'size': base_backing_path['size'],                                                     
                                                 'status': 'creating'}     

                vm_disk_resource_snap = db.vm_disk_resource_snap_create(cntx, vm_disk_resource_snap_values)

                #upload to backup store
                snapshot_vm_disk_resource_metadata = {'workload_id': snapshot['workload_id'],
                                                      'workload_name': workload_obj.display_name,
                                                      'snapshot_id': snapshot['id'],
                                                      'snapshot_vm_id': instance['vm_id'],
                                                      'snapshot_vm_name': instance['vm_name'],
                                                      'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                                      'snapshot_vm_resource_name':  disk_info['dev'],
                                                      'vm_disk_resource_snap_id' : vm_disk_resource_snap_id,}

                vault_url = vault.get_snapshot_vm_disk_resource_path(snapshot_vm_disk_resource_metadata)

                compute_service.vast_data_transfer(cntx, instance['vm_id'], {'path': base_backing_path['path'],
                                                                             'urls': base_backing_path['urls'],
                                                                             'metadata': snapshot_vm_disk_resource_metadata,
                                                                             'snapshot_data': snapshot_data_ex,
                                                                             'previous_snapshot_data': previous_snapshot_data})

                snapshot_obj = db.snapshot_update(  cntx, snapshot_obj.id, 
                                                    {'progress_msg': 'Uploading '+ disk_info['dev'] + ' of VM:' + instance['vm_id'],
                                                     'status': 'uploading'
                                                    })

                LOG.debug(_('Uploading '+ disk_info['dev'] + ' of VM:' + instance['vm_id'] + \
                            '; backing file:' + os.path.basename(base_backing_path['path'])))

                start_time = timeutils.utcnow()
                data_transfer_completed = False
                while True:
                    try:
                        time.sleep(5)
                        data_transfer_status = compute_service.vast_data_transfer_status(cntx, instance['vm_id'], 
                                                                                        {'metadata': {'resource_id' : vm_disk_resource_snap_id}})
                        if data_transfer_status and 'status' in data_transfer_status and len(data_transfer_status['status']):
                            for line in data_transfer_status['status']:
                                if 'Completed' in line:
                                    data_transfer_completed = True
                                    break;
                        if data_transfer_completed:
                            break;
                    except Exception as ex:
                        LOG.exception(ex)
                        raise ex
                    now = timeutils.utcnow()
                    if (now - start_time) > datetime.timedelta(minutes=10*60):
                        raise exception.ErrorOccurred(reason='Timeout uploading data')

                snapshot_obj = db.snapshot_update(cntx, snapshot_obj.id,
                                                  {'progress_msg': 'Uploaded '+ disk_info['dev'] + ' of VM:' + instance['vm_id'],
                                                   'status': 'uploading'})
                
                # update the entry in the vm_disk_resource_snap table
                vm_disk_resource_snap_values = {'vault_url' :  vault_url.replace(vault.get_vault_local_directory(), '', 1),
                                                'vault_service_metadata' : 'None',
                                                'status': 'available'}
                db.vm_disk_resource_snap_update(cntx, vm_disk_resource_snap.id, vm_disk_resource_snap_values)
                vm_disk_size = vm_disk_size + base_backing_path['size']
                base_backing_path = top_backing_path


            snapshot_type = 'incremental'
            vm_disk_resource_snaps = db.vm_disk_resource_snaps_get(cntx, snapshot_vm_resource.id)
            for vm_disk_resource_snap in vm_disk_resource_snaps:
                if  vm_disk_resource_snap.vm_disk_resource_snap_backing_id == None:
                    snapshot_type = 'full'
                     
            db.snapshot_vm_resource_update(cntx, snapshot_vm_resource.id, 
                                           {'snapshot_type' : snapshot_type,
                                            'status': 'available',
                                            'size': vm_disk_size})

    @autolog.log_method(Logger, 'libvirt.driver.post_snapshot_vm')
    def post_snapshot_vm(self, cntx, db, instance, snapshot, snapshot_data): 
        compute_service = nova.API(production=True)
        return compute_service.vast_finalize(cntx, instance['vm_id'], {})
    
    @autolog.log_method(Logger, 'libvirt.driver.delete_restored_vm')
    def delete_restored_vm(self, cntx, db, instance, restore):
        vms = db.restored_vms_get(cntx, restore['id']) 
        compute_service = nova.API(production=True)
        for vm in vms:
            instance = compute_service.get_server_by_id(cntx, vm.vm_id, admin=True)
            compute_service.force_delete(cntx, instance)
            db.restored_vm_update( cntx, vm.vm_id, restore['id'], {'status': 'deleted'})            
    
    @autolog.log_method(Logger, 'libvirt.driver.pre_restore_vm')
    def pre_restore_vm(self, cntx, db, instance, restore):
        pass    
    
    @autolog.log_method(Logger, 'libvirt.driver.restore_vm')
    def restore_vm(self, cntx, db, instance, restore, restored_net_resources, restored_security_groups,
                   restored_compute_flavor, restored_nics, instance_options):    
        """
        Restores the specified instance from a snapshot
        """
        restore_obj = db.restore_get(cntx, restore['id'])
        snapshot_obj = db.snapshot_get(cntx, restore_obj.snapshot_id)
    
        msg = 'Creating VM ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id  
        db.restore_update(cntx,  restore_obj.id, {'progress_msg': msg}) 
    
        compute_service = nova.API(production = (restore['restore_type'] != 'test')) 
        image_service = glance.get_default_image_service(production= (restore['restore_type'] != 'test'))
        volume_service = cinder.API()

        
        test = (restore['restore_type'] == 'test')
        
   
        restored_image = None
        device_restored_volumes = {} # Dictionary that holds dev and restored volumes     
        snapshot_vm_resources = db.snapshot_vm_resources_get(cntx, instance['vm_id'], snapshot_obj.id)
    
        #restore, rebase, commit & upload
        LOG.info(_('Processing disks'))
        snapshot_vm_object_store_transfer_time = 0
        snapshot_vm_data_transfer_time = 0        
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type != 'disk':
                continue
            snapshot_vm_resource_object_store_transfer_time = workload_utils.download_snapshot_vm_resource_from_object_store(cntx, 
                                                                                                                             restore_obj.id, 
                                                                                                                             restore_obj.snapshot_id,
                                                                                                                             snapshot_vm_resource.id)
            snapshot_vm_object_store_transfer_time += snapshot_vm_resource_object_store_transfer_time                                                                                                        
            snapshot_vm_data_transfer_time  +=  snapshot_vm_resource_object_store_transfer_time
                                     
            temp_directory = os.path.join("/opt/stack/data/wlm", restore['id'], snapshot_vm_resource.id)
            try:
                shutil.rmtree( temp_directory )
            except OSError as exc:
                pass
            fileutils.ensure_tree(temp_directory)
            
            commit_queue = Queue() # queue to hold the files to be committed                 
            vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(cntx, snapshot_vm_resource.id)
            disk_format = db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format')
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
                vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(cntx, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
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
            
            LOG.debug('Uploading image and volumes of instance ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id)        
            db.restore_update(cntx,  restore['id'], 
                              {'progress_msg': 'Uploading image and volumes of instance ' + instance['vm_id'] + ' from snapshot ' + snapshot_obj.id,
                               'status': 'uploading' 
                              })                  
    
            #upload to glance
            if db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'vmdk':
                image_metadata = {'is_public': False,
                                  'status': 'active',
                                  'name': snapshot_vm_resource.id,
                                  #'disk_format' : 'ami',
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
                
            
            if snapshot_vm_resource.resource_name == 'vda' or snapshot_vm_resource.resource_name == 'Hard disk 1':
                LOG.debug('Uploading image ' + restored_file_path)
                restored_image = image_service.create(cntx, image_metadata)
                if restore['restore_type'] == 'test':
                    shutil.move(restored_file_path, os.path.join(CONF.glance_images_path, restored_image['id']))
                    restored_file_path = os.path.join(CONF.glance_images_path, restored_image['id'])
                    with file(restored_file_path) as image_file:
                        restored_image = image_service.update(cntx, restored_image['id'], image_metadata, image_file)
                else:
                    restored_image = image_service.update(cntx, 
                                                          restored_image['id'], 
                                                          image_metadata, 
                                                          utils.ChunkedFile(restored_file_path,
                                                                            {'function': db.restore_update,
                                                                             'context': cntx,
                                                                             'id':restore_obj.id}
                                                                            )
                                                      )
                restore_obj = db.restore_get(cntx, restore_obj.id)
                LOG.debug(_("restore_size: %(restore_size)s") %{'restore_size': restore_obj.size,})
                LOG.debug(_("uploaded_size: %(uploaded_size)s") %{'uploaded_size': restore_obj.uploaded_size,})
                LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': restore_obj.progress_percent,})                
            else:
                if test == False:
                    #TODO(gbasava): Request a feature in cinder to create volume from a file.
                    #As a workaround we will create the image and covert that to cinder volume
                    with file(restored_file_path) as image_file:
                        LOG.debug('Uploading image ' + image_file)
                        restored_volume_image = image_service.create(cntx, image_metadata, image_file)
                    restored_volume_name = uuid.uuid4().hex
                    LOG.debug('Creating volume from image ' + image_file)
                    restored_volume = volume_service.create(cntx, math.ceil(restored_volume_image['size']/(float)(1024*1024*1024)), restored_volume_name, 'from workloadmgr', None, restored_volume_image['id'], None, None, None)
                    device_restored_volumes.setdefault(snapshot_vm_resource.resource_name, restored_volume)
                   
                    #delete the image...it is not needed anymore
                    #TODO(gbasava): Cinder takes a while to create the volume from image... so we need to verify the volume creation is complete.
                    time.sleep(30)
                    image_service.delete(cntx, restored_volume_image['id'])
                    
                    restore_obj = db.restore_update(cntx, restore_obj.id, {'uploaded_size_incremental': restored_image['size']})
                else:
                    device_restored_volumes.setdefault(snapshot_vm_resource.resource_name, restored_file_path)                        

            progress = "{message_color} {message} {progress_percent} {normal_color}".format(**{
                'message_color': autolog.BROWN,
                'message': "Restore Progress: ",
                'progress_percent': str(restore_obj.progress_percent),
                'normal_color': autolog.NORMAL,
            }) 
            LOG.debug( progress)    
                    
        #create nova instance
        restored_instance_name = instance['vm_name'] + '_of_snapshot_' + snapshot_obj.id + '_' + uuid.uuid4().hex[:6]
        if instance_options and 'name' in instance_options:
            restored_instance_name = instance_options['name']
        restored_compute_image = compute_service.get_image(cntx, restored_image['id'])
        LOG.debug('Creating Instance ' + restored_instance_name) 
        
        if instance_options and 'availability_zone' in instance_options:
            availability_zone = instance_options['availability_zone']
        else:   
            if test == True:   
                availability_zone = CONF.default_tvault_availability_zone
            else:
                if CONF.default_production_availability_zone == 'None':
                    availability_zone = None
                else:
                    availability_zone = CONF.default_production_availability_zone
    
        restored_security_group_ids = []
        for pit_id, restored_security_group_id in restored_security_groups.iteritems():
            restored_security_group_ids.append(restored_security_group_id)
                     
        restored_instance = compute_service.create_server(cntx, restored_instance_name, 
                                                          restored_compute_image, restored_compute_flavor, 
                                                          nics=restored_nics,
                                                          security_groups=restored_security_group_ids, 
                                                          availability_zone=availability_zone)
        
        while hasattr(restored_instance,'status') == False or restored_instance.status != 'ACTIVE':
            LOG.debug('Waiting for the instance ' + restored_instance.id + ' to boot' )
            time.sleep(30)
            restored_instance =  compute_service.get_server_by_id(cntx, restored_instance.id)
            if hasattr(restored_instance,'status'):
                if restored_instance.status == 'ERROR':
                    raise Exception(_("Error creating instance " + restored_instance.id))
        

        #attach volumes 
        for device, restored_volume in device_restored_volumes.iteritems():
            if device == 'Hard disk 2':
                devname = 'sdb'
            elif device == 'Hard disk 3':
                devname = 'sdc'
            elif device == 'Hard disk 4':
                devname = 'sdd'
            elif device == 'Hard disk 5':
                devname = 'sde' 
            else:
                devname =  device
            if test == False:
                while restored_volume['status'] != 'available':
                    #TODO:(giri) need a timeout to exit
                    LOG.debug('Waiting for volume ' + restored_volume['id'] + ' to be available')
                    time.sleep(30)
                    restored_volume = volume_service.get(cntx, restored_volume['id'])
                LOG.debug('Attaching volume ' + restored_volume['id'])
                compute_service.attach_volume(cntx, restored_instance.id, restored_volume['id'], ('/dev/' + devname))
                time.sleep(15)
            else:
                params = {'path': restored_volume, 'mountpoint': '/dev/' + devname}
                compute_service.testbubble_attach_volume(cntx, restored_instance.id, params)
                
        if test == True:
            LOG.debug('Rebooting instance ' + restored_instance.id )
            compute_service.testbubble_reboot_instance(cntx, restored_instance.id, {'reboot_type':'SIMPLE'})
            time.sleep(10)
            LOG.debug(_("Test Restore Completed"))
        else:
            LOG.debug(_("Restore Completed"))
            
        restored_vm_values = {'vm_id': restored_instance.id,
                              'vm_name':  restored_instance.name,    
                              'restore_id': restore_obj.id,
                              'status': 'available'}
        restored_vm = db.restored_vm_create(cntx,restored_vm_values)    
        
        if test == True:
            LOG.debug(_("Test Restore Completed"))
        else:
            LOG.debug(_("Restore Completed"))
         
        #TODO(giri): Execuete teh following in a finally block
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

    @autolog.log_method(Logger, 'libvirt.driver.post_restore_vm')
    def post_restore_vm(self, cntx, db, instance, restore):
        pass    
    
