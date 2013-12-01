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

from stat import *
from eventlet import greenio
from eventlet import greenthread
from eventlet import patcher
from eventlet import tpool
from eventlet import util as eventlet_util
from lxml import etree
from oslo.config import cfg

from workloadmgr import utils
from workloadmgr import exception
from workloadmgr.virt import event as virtevent
from workloadmgr.virt.libvirt import utils as libvirt_utils
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import fileutils
from workloadmgr.virt import power_state
from workloadmgr.virt import driver
from workloadmgr.image import glance
from workloadmgr.volume import cinder
from workloadmgr.compute import nova
from workloadmgr.network import neutron

native_threading = patcher.original("threading")
native_Queue = patcher.original("Queue")

libvirt = None

LOG = logging.getLogger(__name__)

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
        self._event_queue = None


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

    def _native_thread(self):
        """
        Receives async events coming in from libvirtd.
        """
        while True:
            libvirt.virEventRunDefaultImpl()

    def _dispatch_thread(self):
        """
        Dispatches async events coming in from libvirtd.
        """

        while True:
            self._dispatch_events()

    @staticmethod
    def _event_lifecycle_callback(conn, dom, event, detail, opaque):
        """
        Receives lifecycle events from libvirt.
        """

        self = opaque

        uuid = dom.UUIDString()
        transition = None
        if event == libvirt.VIR_DOMAIN_EVENT_STOPPED:
            transition = virtevent.EVENT_LIFECYCLE_STOPPED
        elif event == libvirt.VIR_DOMAIN_EVENT_STARTED:
            transition = virtevent.EVENT_LIFECYCLE_STARTED
        elif event == libvirt.VIR_DOMAIN_EVENT_SUSPENDED:
            transition = virtevent.EVENT_LIFECYCLE_PAUSED
        elif event == libvirt.VIR_DOMAIN_EVENT_RESUMED:
            transition = virtevent.EVENT_LIFECYCLE_RESUMED

        if transition is not None:
            self._queue_event(virtevent.LifecycleEvent(uuid, transition))

    def _queue_event(self, event):
        """
        Puts an event on the queue for dispatch.
        """

        if self._event_queue is None:
            LOG.debug("Event loop thread is not active, "
                      "discarding event %s" % event)
            return

        # Queue the event...
        self._event_queue.put(event)

        # ...then wakeup the green thread to dispatch it
        c = ' '.encode()
        self._event_notify_send.write(c)
        self._event_notify_send.flush()

    def _dispatch_events(self):
        """
        Wait for & dispatch events from native thread
        """

        # Wait to be notified that there are some
        # events pending
        try:
            _c = self._event_notify_recv.read(1)
            assert _c
        except ValueError:
            return  # will be raised when pipe is closed

        # Process as many events as possible without
        # blocking
        while not self._event_queue.empty():
            try:
                event = self._event_queue.get(block=False)
                self.emit_event(event)
            except native_Queue.Empty:
                pass

    def _init_events_pipe(self):
        """
        Create a self-pipe for the native thread to synchronize on.
        """

        self._event_queue = native_Queue.Queue()
        try:
            rpipe, wpipe = os.pipe()
            self._event_notify_send = greenio.GreenPipe(wpipe, 'wb', 0)
            self._event_notify_recv = greenio.GreenPipe(rpipe, 'rb', 0)
        except (ImportError, NotImplementedError):
            # This is Windows compatibility -- use a socket instead
            #  of a pipe because pipes don't really exist on Windows.
            sock = eventlet_util.__original_socket__(socket.AF_INET,
                                                     socket.SOCK_STREAM)
            sock.bind(('localhost', 0))
            sock.listen(50)
            csock = eventlet_util.__original_socket__(socket.AF_INET,
                                                      socket.SOCK_STREAM)
            csock.connect(('localhost', sock.getsockname()[1]))
            nsock, addr = sock.accept()
            self._event_notify_send = nsock.makefile('wb', 0)
            gsock = greenio.GreenSocket(csock)
            self._event_notify_recv = gsock.makefile('rb', 0)

    def _init_events(self):
        """
        Initializes the libvirt events subsystem.
        """

        self._init_events_pipe()

        LOG.debug("Starting native event thread")
        event_thread = native_threading.Thread(target=self._native_thread)
        event_thread.setDaemon(True)
        event_thread.start()

        LOG.debug("Starting green dispatch thread")
        dispatch_thread = eventlet.spawn(self._dispatch_thread)

    def init_host(self, host):
        libvirt.virEventRegisterDefaultImpl()

        if not self.has_min_version(MIN_LIBVIRT_VERSION):
            major = MIN_LIBVIRT_VERSION[0]
            minor = MIN_LIBVIRT_VERSION[1]
            micro = MIN_LIBVIRT_VERSION[2]
            LOG.error(_('Nova requires libvirt version '
                        '%(major)i.%(minor)i.%(micro)i or greater.') %
                        locals())

        self._init_events()

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
            payload = dict(ip=LibvirtDriver.get_host_ip_addr(),
                           method='_connect',
                           reason=ex)
            notifier.notify(nova_context.get_admin_context(),
                            notifier.publisher_id('compute'),
                            'compute.libvirt.error',
                            notifier.ERROR,
                            payload)
            pass

    def get_num_instances(self):
        """Efficient override of base instance_exists method."""
        return self._conn.numOfDomains()

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

    def _get_existing_domain_xml(self, instance, network_info,
                                 block_device_info=None):
        try:
            virt_dom = self._lookup_by_name(instance['name'])
            xml = virt_dom.XMLDesc(0)
        except exception.InstanceNotFound:
            disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                                instance,
                                                block_device_info)
            xml = self.to_xml(instance, network_info, disk_info,
                              block_device_info=block_device_info)
        return xml


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

            msg = _("Error from libvirt while looking up %(instance_name)s: "
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

        Returns a list of all block devices for this domain.
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

    def snapshot_create_as(self, instance_name, snapshot_name, snapshot_description, dev_snapshot_disk_paths):
        """Atomic disk only external snapshots of an instance
        Todo: use virDomainSnapshotCreateXML instead of virsh

        :param instance: instance to snapshot
        :param snapshot_name: Name of snapshot
        :param snapshot_description: Description of snapshot
        :param snapshot_disk_paths: list of the new snapshot_disk_paths
        """
        diskspecs = []
        for dev, snapshot in dev_snapshot_disk_paths.iteritems():
            diskspecs = diskspecs + ['--diskspec', dev + ',snapshot=external,file=' + snapshot]

        virsh_cmd = ['virsh', 'snapshot-create-as', 
                     instance_name, snapshot_name, 
                     snapshot_description, 
                     '--disk-only', '--atomic'] + diskspecs

        utils.execute(*virsh_cmd, run_as_root=True)


    def snapshot_delete(self, instance_name, snapshot_name, metadata = False):
        """delete the snapshot
        Todo: use virDomainXXX instead of virsh

        :param instance: instance of snapshot
        :param snapshot_name: Name of snapshot
        :param metadata: If True, delete the metadata only
        """
        virsh_cmd = ['virsh', 'snapshot-delete', instance_name, snapshot_name] 
        if metadata :
            virsh_cmd = virsh_cmd + ['--metadata']
        utils.execute(*virsh_cmd, run_as_root=True)
  
    def rebase_qcow2(self, backing_file_base, backing_file_top):
        """rebase the backing_file_top to backing_file_base using unsafe mode
        :param backing_file_base: backing file to rebase to
        :param backing_file_top: top file to rebase
        """
        utils.execute('qemu-img', 'rebase', '-u', '-b', backing_file_base, backing_file_top, run_as_root=True)   

    def commit_qcow2(self, backing_file_top):
        """rebase the backing_file_top to backing_file_base
         :param backing_file_top: top file to commit from to its base
        """
        utils.execute('qemu-img', 'commit', backing_file_top, run_as_root=True)        

    def rebase_vmdk(self, base, orig_base, base_descriptor, top, orig_top, top_descriptor):
        """
        rebase the top to base
        """
        base_path, base_filename = os.path.split(base)
        orig_base_path, orig_base_filename = os.path.split(orig_base)
        os.rename(base, os.path.join(base_path,orig_base_filename))
        top_parentCID =  re.search('parentCID=(\w+)', top_descriptor).group(1)
        base_descriptor = re.sub(r'(^CID=)(\w+)', "CID=%s"%top_parentCID, base_descriptor)
        with open(base, "w") as base_descriptor_file:
            base_descriptor_file.write("%s"%base_descriptor)
        
        top_path, top_filename = os.path.split(top)
        orig_top_path, orig_top_filename = os.path.split(orig_top)
        if(os.path.isfile(os.path.join(top_path,orig_top_filename))):
            with open(top, "r") as top_descriptor_file:
                top_descriptor =  top_descriptor_file.read() 
        else:
            os.rename(top, os.path.join(top_path,orig_top_filename))
        top_descriptor = re.sub(r'parentFileNameHint="([^"]*)"', "parentFileNameHint=\"%s\""%base, top_descriptor)
        with open(top, "w") as top_descriptor_file:
            top_descriptor_file.write("%s"%top_descriptor)            
 
    def commit_vmdk(self, file_to_commit, commit_to):
        """rebase the backing_file_top to backing_file_base
         :param backing_file_top: top file to commit from to its base
        """
        #due to a bug in Nova VMware Driver (https://review.openstack.org/#/c/43994/) we will create a preallocated disk
        #utils.execute( 'vmware-vdiskmanager', '-r', file_to_commit, '-t 0',  commit_to, run_as_root=False)
        utils.execute( 'vmware-vdiskmanager', '-r', file_to_commit, '-t 4',  commit_to, run_as_root=False)
        return commit_to.replace(".vmdk", "-flat.vmdk")      

                     
    def blockcommit(self, instance, dev, backing_file_base, backing_file_top):
        """block commit the changes from top to base
        Todo: use virDomainXXX instead of virsh

        :param instance: instance to blockcommit
        :param dev: block device name
        :param backing_file_base: base to commit into
        :param backing_file_top: top file to commit from
        """

        virsh_cmd = ['virsh', 'blockcommit', '--domain', 
                     instance, dev, '--wait', '--base', backing_file_base, 
                     '--top', backing_file_top]

        utils.execute(*virsh_cmd, run_as_root=True)
        
    def snapshot(self, workload, snapshot, snapshot_vm, vault_service, db, context, update_task_state = None): 
        if snapshot['snapshot_type'] == 'full' :
            return self._snapshot_full(workload, snapshot, snapshot_vm, vault_service, db, context, update_task_state)
        else:
            return self._snapshot_incremental(workload, snapshot, snapshot_vm, vault_service, db, context, update_task_state)
                  

    def _snapshot_full(self, workload, snapshot, snapshot_vm, vault_service, db, context, update_task_state = None):
        """
        Prepares the backsup for the instance specified in snapshot_vm

        :param workload: 
        :param snapshot: 
        :param snapshot_vm: 
        """
        # Todo - Check the min supported version of the QEMU and Libvirt 
        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_PREPARE)    
            
        instance_name = self.get_instance_name_by_uuid(snapshot_vm.vm_id)
        snapshot_directory = os.path.join(CONF.instances_path, snapshot_vm.vm_id)
        fileutils.ensure_tree(snapshot_directory)
        snapshot_name = uuid.uuid4().hex
        snapshot_description = "Snapshot " + snapshot.id + "of WorkloadMgr " + workload.id
        dev_snapshot_disk_paths = {} # Dictionary that holds dev and snapshot_disk_path
        devices = self.get_disks(instance_name)
        for device in devices:
            dev_snapshot_disk_paths.setdefault(device, 
                        snapshot_directory + '/' + snapshot_name + '_' + device + '.qcow2' )

        # we may have to powerdown/suspend until the permissions issue is resolved
        #self.suspend(instance_name)
        self.snapshot_create_as(instance_name, snapshot_name, 
                                snapshot_description, dev_snapshot_disk_paths)
        # Todo - handle the failure of snapshot_create_as
        self.snapshot_delete(instance_name, snapshot_name, True)
        
        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_SNAPSHOT_CREATED)

        # stream the backing files of the new snapshots
        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_UPLOAD_INPROGESS)
        
        
        for dev, snapshot_disk_path in dev_snapshot_disk_paths.iteritems():    
            src_backing_path = libvirt_utils.get_disk_backing_file(snapshot_disk_path, basename=False)        
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                           'vm_id': snapshot_vm.vm_id,
                                           'snapshot_id': snapshot.id,       
                                           'resource_type': 'disk',
                                           'resource_name':  dev,
                                           'status': 'creating'}

            snapshot_vm_resource = db.snapshot_vm_resource_create(context, 
                                                snapshot_vm_resource_values)                                                
            
            src_backings = [] # using list as a stack for the disk backings
            while (src_backing_path != None):
                src_backings.append(src_backing_path)
                mode = os.stat(src_backing_path).st_mode
                if S_ISREG(mode) :
                    src_backing_path = libvirt_utils.get_disk_backing_file(src_backing_path, basename=False)      
                else:
                    src_backing_path = None
            
            base_backing_path = None
            vm_disk_resource_snap_id = None
            if(len(src_backings) > 0):
                base_backing_path = src_backings.pop() 
            while (base_backing_path != None):
                top_backing_path = None
                if(len(src_backings) > 0):
                    top_backing_path = src_backings.pop()
                    
                # create an entry in the vm_disk_resource_snaps table
                vm_disk_resource_snap_backing_id = vm_disk_resource_snap_id
                vm_disk_resource_snap_id = str(uuid.uuid4())
                vm_disk_resource_snap_metadata = {} # Dictionary to hold the metadata
                if(dev == 'vda' and top_backing_path == None):
                    vm_disk_resource_snap_metadata.setdefault('base_image_ref','TODO')                    
                vm_disk_resource_snap_metadata.setdefault('disk_format','qcow2')
                vm_disk_resource_snap_values = {'id': vm_disk_resource_snap_id,
                                             'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                             'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                                             'metadata': vm_disk_resource_snap_metadata,       
                                             'top':  (top_backing_path == None),
                                             'vault_service_id' : '1',
                                             'status': 'creating'}     
                                                             
                vm_disk_resource_snap = db.vm_disk_resource_snap_create(context, vm_disk_resource_snap_values)                
                #upload to vault service
                vault_service_url = None
                with utils.temporary_chown(base_backing_path):
                    vault_metadata = {'metadata': vm_disk_resource_snap_metadata,
                                      'vm_disk_resource_snap_id' : vm_disk_resource_snap_id,
                                      'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                      'resource_name':  dev,
                                      'snapshot_vm_id': snapshot_vm.vm_id,
                                      'snapshot_id': snapshot.id}
                    vault_service_url = vault_service.store(vault_metadata, base_backing_path); 
                # update the entry in the vm_disk_resource_snap table
                vm_disk_resource_snap_values = {'vault_service_url' :  vault_service_url ,
                                             'vault_service_metadata' : 'None',
                                             'status': 'completed'} 
                vm_disk_resource_snap.update(vm_disk_resource_snap_values)
                base_backing_path = top_backing_path

            if dev == 'vda': 
                #TODO(gbasava): Base image can be shared by multiple instances...should leave a minimum of 
                # two qcow2 files in front of the base image
                continue
            
            state = self.get_info(instance_name)['state']    
            #TODO(gbasava): Walk the qcow2 for each disk device and commit and intermediate qcow2 files into base
            with utils.temporary_chown(snapshot_disk_path):
                backing_file = libvirt_utils.get_disk_backing_file(snapshot_disk_path, basename=False)
            with utils.temporary_chown(backing_file):
                backing_file_backing = libvirt_utils.get_disk_backing_file(backing_file, basename=False)
            #with utils.temporary_chown(backing_file_backing):
            
            if (backing_file_backing != None and backing_file_backing != backing_file):
                if state == power_state.RUNNING: 
                    # if the instance is running we will do a blockcommit
                    self.blockcommit(instance_name, dev, backing_file_backing, backing_file)
                    utils.delete_if_exists(backing_file)
                elif (state == power_state.SHUTDOWN or  state == power_state.SUSPENDED ): #commit and rebase
                    self.commit_qcow2(backing_file)
                    utils.delete_if_exists(backing_file)                     
                    self.rebase_qcow2(backing_file_backing, snapshot_disk_path)
                #else: TODO(gbasava): investigate and handle other powerstates     

        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_UPLOADING_FINISH)
            update_task_state(task_state=task_states.SNAPSHOT_COMPLETE)
            
    def _snapshot_incremental(self, workload, snapshot, snapshot_vm, vault_service, db, context, update_task_state = None):
        """
        Incremental snapshot of the instance specified in snapshot_vm

        :param workload: 
        :param snapshot: 
        :param snapshot_vm: 
        """
        
        #TODO(gbasava): Check if the previous full snapshot exists by calling vm_recent_snapshot_get
        
        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_START)    
            
        instance_name = self.get_instance_name_by_uuid(snapshot_vm.vm_id)
        snapshot_directory = os.path.join(CONF.instances_path, snapshot_vm.vm_id)
        fileutils.ensure_tree(snapshot_directory)
 
        snapshot_name = uuid.uuid4().hex
        snapshot_description = "Snapshot " + snapshot.id + "of WorkloadMgr " + workload.id
        dev_snapshot_disk_paths = {} # Dictionary that holds dev and snapshot_disk_path
        devices = self.get_disks(instance_name)
        for device in devices:
            dev_snapshot_disk_paths.setdefault(device, 
                        snapshot_directory + '/' + snapshot_name + '_' + device + '.qcow2' )

        #TODo(gbasava): snapshot_create_as is failing with permissions issue while the VM is running
        #Need
        self.snapshot_create_as(instance_name, snapshot_name, 
                                snapshot_description, dev_snapshot_disk_paths)
        #TODo(gbasava): Handle the failure of snapshot_create_as
        self.snapshot_delete(instance_name, snapshot_name, True)
        
        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_SNAPSHOT_CREATED)
        
        
        vm_recent_snapshot = db.vm_recent_snapshot_get(context, snapshot_vm.vm_id)  
         
                    
        for dev, snapshot_disk_path in dev_snapshot_disk_paths.iteritems():
            previous_snapshot_vm_resource = db.snapshot_vm_resource_get_by_resource_name(
                                                            context, 
                                                            snapshot_vm.vm_id, 
                                                            vm_recent_snapshot.snapshot_id, 
                                                            dev)
            previous_vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(context, 
                                                                        previous_snapshot_vm_resource.id)
                 
            
            src_backing_path = libvirt_utils.get_disk_backing_file(snapshot_disk_path, basename=False)        
            snapshot_vm_resource_values = {'id': str(uuid.uuid4()),
                                               'vm_id': snapshot_vm.vm_id,
                                               'snapshot_id': snapshot.id,       
                                               'resource_type': 'disk',
                                               'resource_name':  dev,
                                               'status': 'creating'}

            snapshot_vm_resource = db.snapshot_vm_resource_create(context, 
                                                snapshot_vm_resource_values)                                                
            # create an entry in the vm_disk_resource_snaps table
            vm_disk_resource_snap_backing_id = previous_vm_disk_resource_snap.id
            vm_disk_resource_snap_id = str(uuid.uuid4())
            vm_disk_resource_snap_metadata = {} # Dictionary to hold the metadata
            vm_disk_resource_snap_metadata.setdefault('disk_format','qcow2')
            vm_disk_resource_snap_values = {'id': vm_disk_resource_snap_id,
                                         'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                         'vm_disk_resource_snap_backing_id': vm_disk_resource_snap_backing_id,
                                         'metadata': vm_disk_resource_snap_metadata,       
                                         'top':  True,
                                         'vault_service_id' : '1',
                                         'status': 'creating'}     
                                                         
            vm_disk_resource_snap = db.vm_disk_resource_snap_create(context, vm_disk_resource_snap_values)                
            #upload to vault service
            vault_service_url = None
            with utils.temporary_chown(src_backing_path):
                vault_metadata = {'metadata': vm_disk_resource_snap_metadata,
                                  'vm_disk_resource_snap_id' : vm_disk_resource_snap_id,
                                  'snapshot_vm_resource_id': snapshot_vm_resource.id,
                                  'resource_name':  dev,
                                  'snapshot_vm_id': snapshot_vm.vm_id,
                                  'snapshot_id': snapshot.id}
                vault_service_url = vault_service.store(vault_metadata, src_backing_path); 
                
            # update the entry in the vm_disk_resource_snap table
            vm_disk_resource_snap_values = {'vault_service_url' :  vault_service_url ,
                                         'vault_service_metadata' : 'None',
                                         'status': 'completed'} 
            vm_disk_resource_snap.update(vm_disk_resource_snap_values)

                
        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_UPLOADING_FINISH)

        # do a block commit. 
        # TODO(gbasava): Consider the case of a base image shared by multiple instances
        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_BLOCKCOMMIT_INPROGRESS)

        state = self.get_info(instance_name)['state']
        
        for dev, snapshot_disk_path in dev_snapshot_disk_paths.iteritems():    
            with utils.temporary_chown(snapshot_disk_path):
                backing_file = libvirt_utils.get_disk_backing_file(snapshot_disk_path, basename=False)
            with utils.temporary_chown(backing_file):
                backing_file_backing = libvirt_utils.get_disk_backing_file(backing_file, basename=False)
            #with utils.temporary_chown(backing_file_backing):
            # if the instance is running we will do a blockcommit
            if (backing_file_backing != None and backing_file_backing != backing_file):
                if state == power_state.RUNNING:
                    self.blockcommit(instance_name, dev, backing_file_backing, backing_file)
                    utils.delete_if_exists(backing_file)
                elif (state == power_state.SHUTDOWN or  state == power_state.SUSPENDED ): #commit and rebase
                    self.commit_qcow2(backing_file)
                    utils.delete_if_exists(backing_file)                     
                    self.rebase_qcow2(backing_file_backing, snapshot_disk_path)
                #else: TODO(gbasava): investigate and handle other powerstates     

        if update_task_state:
            update_task_state(task_state=task_states.SNAPSHOT_BLOCKCOMMIT_FINISH)
            update_task_state(task_state=task_states.SNAPSHOT_COMPLETE)
            
    def _get_pit_resource_id(self, vm_network_resource_snap, key):
        for metadata in vm_network_resource_snap.metadata:
            if metadata['key'] == key:
                pit_id = metadata['value']
                return pit_id
    
    def snapshot_restore(self, workload, snapshot, snapshot_vm, vault_service, new_net_resources, db, context, update_task_state = None):
        """
        Restores the specified instance from a snapshot
        """  
        restored_image = None
        device_restored_volumes = {} # Dictionary that holds dev and restored volumes     
        snapshot_vm_resources = db.snapshot_vm_resources_get(context, snapshot_vm.vm_id, snapshot.id)        

        #network resources
        nics = []
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type == 'nic':
                vm_nic_snapshot = db.vm_network_resource_snap_get(context, snapshot_vm_resource.id)
                #private network
                pit_id = self._get_pit_resource_id(vm_nic_snapshot, 'network_id')
                new_network = new_net_resources[pit_id]
                nic_info = {}
                nic_info.setdefault('net-id', new_network['id']) 
                nic_info.setdefault('v4-fixed-ip', db.get_metadata_value(vm_nic_snapshot.metadata, 'ip_address'))
                nics.append(nic_info)                        
                               
        #restore, rebase, commit & upload
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type != 'disk':
                continue
            temp_directory = os.path.join("/tmp", snapshot_vm_resource.id)
            try:
                shutil.rmtree( temp_directory )
            except OSError as exc:
                pass
            fileutils.ensure_tree(temp_directory)
            
            commit_queue = Queue() # queue to hold the files to be committed                 
            vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(context, snapshot_vm_resource.id)
            disk_filename_extention = db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format')
            restored_file_path =temp_directory + '/' + vm_disk_resource_snap.id + \
                                '_' + snapshot_vm_resource.resource_name + '.' \
                                + disk_filename_extention
            restored_file_path = restored_file_path.replace(" ", "")
            vault_metadata = {'vault_service_url' : vm_disk_resource_snap.vault_service_url,
                              'vault_service_metadata' : vm_disk_resource_snap.vault_service_metadata,
                              'vm_disk_resource_snap_id' : vm_disk_resource_snap.id,
                              'snapshot_vm_resource_id': snapshot_vm_resource.id,
                              'resource_name':  snapshot_vm_resource.resource_name,
                              'snapshot_vm_id': snapshot_vm_resource.vm_id,
                              'snapshot_id': snapshot_vm_resource.snapshot_id}
            vault_service.restore(vault_metadata, restored_file_path)                            
            while vm_disk_resource_snap.vm_disk_resource_snap_backing_id is not None:
                vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                snapshot_vm_resource_backing = db.snapshot_vm_resource_get(context, vm_disk_resource_snap_backing.snapshot_vm_resource_id)
                restored_file_path_backing =temp_directory + '/' + vm_disk_resource_snap_backing.id + \
                                            '_' + snapshot_vm_resource_backing.resource_name + '.' \
                                            + disk_filename_extention
                restored_file_path_backing = restored_file_path_backing.replace(" ", "")
                vault_metadata = {'vault_service_url' : vm_disk_resource_snap_backing.vault_service_url,
                                  'vault_service_metadata' : vm_disk_resource_snap_backing.vault_service_metadata,
                                  'vm_disk_resource_snap_id' : vm_disk_resource_snap_backing.id,
                                  'snapshot_vm_resource_id': snapshot_vm_resource_backing.id,
                                  'resource_name':  snapshot_vm_resource_backing.resource_name,
                                  'snapshot_vm_id': snapshot_vm_resource_backing.vm_id,
                                  'snapshot_id': snapshot_vm_resource_backing.snapshot_id}
                vault_service.restore(vault_metadata, restored_file_path_backing)     
                #rebase
                if(db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'qcow2'):
                    self.rebase_qcow2(restored_file_path_backing, restored_file_path)
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
                    self.commit_qcow2(file_to_commit)
                    if restored_file_path != file_to_commit:
                        utils.delete_if_exists(file_to_commit)
            elif(db.get_metadata_value(vm_disk_resource_snap.metadata,'disk_format') == 'vmdk'):
                if commit_queue.empty() is not True:
                    commit_queue.put(restored_file_path)
                    file_to_commit = commit_queue.get_nowait()
                    commit_to = temp_directory + '/' + vm_disk_resource_snap.id + '_Restored_' + snapshot_vm_resource.resource_name + '.' + disk_filename_extention
                    commit_to = commit_to.replace(" ", "")
                    restored_file_path = self.commit_vmdk(file_to_commit, commit_to)

            #upload to glance
            with file(restored_file_path) as image_file:
                image_metadata = {'is_public': False,
                                  'status': 'active',
                                  'name': snapshot_vm_resource.id,
                                  #'disk_format' : 'ami',
                                  'disk_format' : 'vmdk', 
                                  'container_format' : 'bare',
                                  'properties': {
                                                 'vmware_adaptertype' : 'ide',
                                                 'vmware_disktype': 'preallocated',
                                                 'image_location': 'TODO',
                                                 'image_state': 'available',
                                                 'owner_id': context.project_id}
                                  }
                #if 'architecture' in base.get('properties', {}):
                #    arch = base['properties']['architecture']
                #    image_metadata['properties']['architecture'] = arch
                
                image_service = glance.get_default_image_service()
                if snapshot_vm_resource.resource_name == 'vda' or snapshot_vm_resource.resource_name == 'Hard disk 1':
                    restored_image = image_service.create(context, image_metadata, image_file)
                else:
                    #TODO(gbasava): Request a feature in cinder to create volume from a file.
                    #As a workaround we will create the image and covert that to cinder volume

                    restored_volume_image = image_service.create(context, image_metadata, image_file)
                    restored_volume_name = uuid.uuid4().hex
                    volume_service = cinder.API()
                    restored_volume = volume_service.create(context, max(restored_volume_image['size']/(1024*1024*1024), 1), restored_volume_name, 
                                                        'from workloadmgr', None, restored_volume_image['id'], None, None, None)
                    device_restored_volumes.setdefault(snapshot_vm_resource.resource_name, restored_volume)
                   
                    #delete the image...it is not needed anymore
                    #TODO(gbasava): Cinder takes a while to create the volume from image... so we need to verify the volume creation is complete.
                    time.sleep(30)
                    image_service.delete(context, restored_volume_image['id'])
            utils.delete_if_exists(restored_file_path)
            try:
                shutil.rmtree( temp_directory )
            except OSError as exc:
                pass
                    
        #create nova instance
        restored_instance_name = uuid.uuid4().hex
        compute_service = nova.API()
        restored_compute_image = compute_service.get_image(context, restored_image['id'])
        restored_compute_flavor = compute_service.get_flavor(context, 'm1.tiny')

        restored_instance = compute_service.create_server(context, restored_instance_name, restored_compute_image, restored_compute_flavor, nics=nics)
        #attach volumes 
        for device, restored_volume in device_restored_volumes.iteritems():
            compute_service.attach_volume(context, restored_instance.id, restored_volume['id'], ('/dev/' + device))
              
