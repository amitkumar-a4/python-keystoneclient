# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Implementation of a snapshot service that uses Swift as the backend

**Related Flags**

:snapshot_swift_url: The URL of the Swift endpoint (default:
                                                        localhost:8080).
:snapshot_swift_object_size: The size in bytes of the Swift objects used
                                    for volume snapshots (default: 52428800).
:snapshot_swift_retry_attempts: The number of retries to make for Swift
                                    operations (default: 10).
:snapshot_swift_retry_backoff: The backoff time in seconds between retrying
                                    failed Swift operations (default: 10).
:snapshot_compression_algorithm: Compression algorithm to use for volume
                               snapshots. Supported options are:
                               None (to disable), zlib and bz2 (default: zlib)
"""

import hashlib
import httplib
import json
import os
import socket
import StringIO
import time
import types
import threading

import eventlet
from oslo.config import cfg

from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import timeutils
from workloadmgr.openstack.common import jsonutils
from swiftclient import client as swift
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.virt import qemuimages

LOG = logging.getLogger(__name__)

lock = threading.Lock()

wlm_vault_swift_opts = [
    cfg.StrOpt('wlm_vault_swift_url',
               default='http://localhost:8080/v1/AUTH_',
               help='The URL of the Swift endpoint'),
    cfg.StrOpt('wlm_vault_swift_container',
               default='vast_snapshots',
               help='The default Swift container to use for workload snapshots'),
    cfg.IntOpt('wlm_vault_swift_object_size',
               default=2 * 1024 * 1024 * 1024,
               help='The size in bytes of Swift snapshot objects'),
    cfg.IntOpt('wlm_vault_swift_retry_attempts',
               default=3,
               help='The number of retries to make for Swift operations'),
    cfg.IntOpt('wlm_vault_swift_retry_backoff',
               default=2,
               help='The backoff time in seconds between Swift retries'),
    cfg.StrOpt('wlm_vault_compression_algorithm',
               default= 'none', #'zlib',
               help='Compression algorithm (None to disable)'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(wlm_vault_swift_opts)

class ReadWrapper(object):

    def __init__(self, obj_with_read, update=None):    
        
        self.inner_read = None
        if hasattr(obj_with_read, 'read'):
            self.inner_read = obj_with_read.read
            obj_with_read.read = self._read_wrap
        self.update = update
        self.uploaded_size_incremental = 0

    def _read_wrap(self, chunk_size):
        chunk = self.inner_read(chunk_size)
        read_size = len(chunk)
        self.uploaded_size_incremental = self.uploaded_size_incremental + read_size
        if self.update and ((self.uploaded_size_incremental > (5 * 1024 * 1024)) or (read_size < chunk_size)):
            object = self.update['function'](self.update['context'], 
                                             self.update['id'], 
                                             {'uploaded_size_incremental': self.uploaded_size_incremental})
            print "progress_percent: " + str(object.progress_percent) + "%"
            #LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': object.progress_percent,})
            self.uploaded_size_incremental = 0

        return chunk


class SwiftBackupService(base.Base):
    """Provides snapshot, restore and delete of snapshot objects within Swift."""

    SERVICE_VERSION = '1.0.0'
    SERVICE_VERSION_MAPPING = {'1.0.0': '_restore_v1'}

    def _get_compressor(self, algorithm):
        try:
            if algorithm.lower() in ('none', 'off', 'no'):
                return None
            elif algorithm.lower() in ('zlib', 'gzip'):
                import zlib as compressor
                return compressor
            elif algorithm.lower() in ('bz2', 'bzip2'):
                import bz2 as compressor
                return compressor
        except ImportError:
            pass

        err = _('unsupported compression algorithm: %s') % algorithm
        raise ValueError(unicode(err))

    def __init__(self, context, db_driver=None):
        self.context = context
        self.swift_url = '%s%s' % (FLAGS.wlm_vault_swift_url,
                                   self.context.project_id)
        self.az = FLAGS.storage_availability_zone
        self.data_block_size_bytes = FLAGS.wlm_vault_swift_object_size
        self.swift_attempts = FLAGS.wlm_vault_swift_retry_attempts
        self.swift_backoff = FLAGS.wlm_vault_swift_retry_backoff
        self.compressor = \
            self._get_compressor(FLAGS.wlm_vault_compression_algorithm)
        self.conn = swift.Connection(None, None, None,
                                     retries=self.swift_attempts,
                                     preauthurl=self.swift_url,
                                     preauthtoken=self.context.auth_token,
                                     starting_backoff=self.swift_backoff)
        super(SwiftBackupService, self).__init__(db_driver)



    def _check_container_exists(self, container):
        LOG.debug(_('_check_container_exists: container: %s') % container)
        try:
            self.conn.head_container(container)
        except swift.ClientException as error:
            if error.http_status == httplib.NOT_FOUND:
                LOG.debug(_('container %s does not exist') % container)
                return False
            else:
                raise
        else:
            LOG.debug(_('container %s exists') % container)
            return True

    def _create_workload_container_n_metadata(self, context, workload):
        try:
            lock.acquire()
            container = self._generate_workload_container_name(workload)
            if not self._check_container_exists(container):
                self.conn.put_container(container)
                self._write_wl_metadata(workload, container)
            return container
        finally:
            lock.release()        

    def _create_snapshot_metadata(self, context, snapshot):
        try:
            lock.acquire()
            workload = WorkloadMgrDB().db.workload_get(context, snapshot.workload_id)
            container = self._generate_workload_container_name(workload)
            self._write_snapshot_metadata(snapshot, container)
            return container
        finally:
            lock.release()        

    def _generate_workload_container_name(self, workload):
        container = 'workload_%s' % (workload.id)
        LOG.debug(_('_generate_workload_container_name: %s') % container)
        return container

    def _generate_workload_object_name_prefix(self, workload):
        wl = 'workload_%s' % (workload.id)
        LOG.debug(_('_generate_workload_object_name_prefix: %s') % wl)
        return wl

    def _generate_snapshot_object_name_prefix(self, snapshot):
        workload = WorkloadMgrDB().db.workload_get(self.context, snapshot.workload_id)
        wl = 'workload_%s' % (workload.id)
        snap = 'snapshot_%s' % (snapshot.id)

        prefix = wl + '/' + snap

        LOG.debug(_('_generate_swift_object_name_prefix: %s') % prefix)
        return prefix

    def _generate_swift_object_name_prefix(self, snapshot_metadata):
        snap = WorkloadMgrDB().db.snapshot_get(self.context, snapshot_metadata['snapshot_id'])
        snapprefix = self._generate_snapshot_object_name_prefix(snap)
        vm_id = 'vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        vm_res_id = 'vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'],
                                         snapshot_metadata['resource_name'])
        prefix = snapprefix + '/' + vm_id + '/' + vm_res_id
        LOG.debug(_('_generate_swift_object_name_prefix: %s') % prefix)
        return prefix

    def _generate_object_names(self, container, snapshot_metadata):
        prefix = self._generate_swift_object_name_prefix(snapshot_metadata)
        swift_objects = self.conn.get_container(container,
                                                prefix=prefix,
                                                full_listing=True)[1]
        swift_object_names = []
        for swift_object in swift_objects:
            swift_object_names.append(swift_object['name'])
        LOG.debug(_('generated object list: %s') % swift_object_names)
        return swift_object_names

    def _wl_metadata_filename(self, workload):
        object_prefix = self._generate_workload_object_name_prefix(workload)
        meta = '%s/wl_metadata' % (object_prefix)
        meta_vms = '%s/wl_metadata_vms' % (object_prefix)
        return meta, meta_vms

    def _snapshot_metadata_filename(self, snapshot):
        object_prefix = self._generate_snapshot_object_name_prefix(snapshot)
        meta = '%s/snapshot_metadata' % (object_prefix)
        meta_vms = '%s/snapshot_metadata_vms' % (object_prefix)
        return meta, meta_vms

    def _write_wl_metadata(self, workload, container):
        meta, meta_vms = self._wl_metadata_filename(workload)
        LOG.debug(_('_write_wl_metadata started, container name: %(container)s,'
                    ' metadata filename: %(meta)s') % locals())
        metadata_json = jsonutils.dumps(workload, sort_keys=True, indent=2)
        reader = StringIO.StringIO(metadata_json)
        etag = self.conn.put_object(container, meta, reader)
        md5 = hashlib.md5(metadata_json).hexdigest()
        if etag != md5:
            err = _('error writing metadata file to swift, MD5 of metadata'
                    ' file in swift [%(etag)s] is not the same as MD5 of '
                    'metadata file sent to swift [%(md5)s]') % locals()
            raise exception.InvalidBackup(reason=err)

        vms = WorkloadMgrDB().db.workload_vms_get(self.context, workload.id)
        metadata_vms_json = jsonutils.dumps(vms, sort_keys=True, indent=2)
        reader = StringIO.StringIO(metadata_vms_json)
        etag = self.conn.put_object(container, meta_vms, reader)
        md5 = hashlib.md5(metadata_vms_json).hexdigest()
        if etag != md5:
            err = _('error writing metadata file to swift, MD5 of metadata'
                    ' file in swift [%(etag)s] is not the same as MD5 of '
                    'metadata file sent to swift [%(md5)s]') % locals()
            raise exception.InvalidBackup(reason=err)

        LOG.debug(_('_write_wl_metadata finished'))

    def _write_snapshot_metadata(self, snapshot, container):
        meta, meta_vms = self._snapshot_metadata_filename(snapshot)
        LOG.debug(_('_write_wl_metadata started, container name: %(container)s,'
                    ' metadata filename: %(meta)s') % locals())
        metadata_json = jsonutils.dumps(snapshot, sort_keys=True, indent=2)
        reader = StringIO.StringIO(metadata_json)
        etag = self.conn.put_object(container, meta, reader)
        md5 = hashlib.md5(metadata_json).hexdigest()
        if etag != md5:
            err = _('error writing metadata file to swift, MD5 of metadata'
                    ' file in swift [%(etag)s] is not the same as MD5 of '
                    'metadata file sent to swift [%(md5)s]') % locals()
            raise exception.InvalidBackup(reason=err)

        vms = WorkloadMgrDB().db.snapshot_vms_get(self.context, snapshot.id)
        metadata_vms_json = jsonutils.dumps(vms, sort_keys=True, indent=2)
        reader = StringIO.StringIO(metadata_vms_json)
        etag = self.conn.put_object(container, meta_vms, reader)
        md5 = hashlib.md5(metadata_vms_json).hexdigest()
        if etag != md5:
            err = _('error writing metadata file to swift, MD5 of metadata'
                    ' file in swift [%(etag)s] is not the same as MD5 of '
                    'metadata file sent to swift [%(md5)s]') % locals()
            raise exception.InvalidBackup(reason=err)

        LOG.debug(_('_write_wl_metadata finished'))

    def _metadata_filename(self, snapshot_metadata):
        object_prefix = self._generate_swift_object_name_prefix(snapshot_metadata)
        swift_object_name = snapshot_metadata['vm_disk_resource_snap_id']
        filename = '%s/%s_metadata' % (object_prefix, swift_object_name)
        return filename

    def put_object(self, url, json_data):
        container = url.split('/', 1)[0]
        reader = StringIO.StringIO(json_data)
        etag = self.conn.put_object(container, url, reader)
        md5 = hashlib.md5(json_data).hexdigest()
        if etag != md5:
            err = _('error writing metadata file to swift, MD5 of metadata'
                    ' file in swift [%(etag)s] is not the same as MD5 of '
                    'metadata file sent to swift [%(md5)s]') % locals()
            raise exception.InvalidBackup(reason=err)
    
    def get_workloads(self):
        #placeholder for now
        return []        

    def _write_metadata(self, snapshot_metadata, container, object_list):
        filename = self._metadata_filename(snapshot_metadata)
        LOG.debug(_('_write_metadata started, container name: %(container)s,'
                    ' metadata filename: %(filename)s') % locals())
        metadata = {}
        metadata['version'] = self.SERVICE_VERSION
        metadata['vm_disk_resource_snap_id'] = snapshot_metadata['vm_disk_resource_snap_id']
        metadata['snapshot_vm_resource_id'] = snapshot_metadata['snapshot_vm_resource_id']
        metadata['snapshot_vm_id'] = snapshot_metadata['snapshot_vm_id']
        metadata['snapshot_id'] = snapshot_metadata['snapshot_id']
        metadata['objects'] = object_list
        metadata_json = json.dumps(metadata, sort_keys=True, indent=2)
        reader = StringIO.StringIO(metadata_json)
        etag = self.conn.put_object(container, filename, reader)
        md5 = hashlib.md5(metadata_json).hexdigest()
        if etag != md5:
            err = _('error writing metadata file to swift, MD5 of metadata'
                    ' file in swift [%(etag)s] is not the same as MD5 of '
                    'metadata file sent to swift [%(md5)s]') % locals()
            raise exception.InvalidBackup(reason=err)
        LOG.debug(_('_write_metadata finished'))

    def _read_metadata(self, container, snapshot_metadata):
        filename = self._metadata_filename(snapshot_metadata)
        LOG.debug(_('_read_metadata started, container name: %(container)s, '
                    'metadata filename: %(filename)s') % locals())
        (resp, body) = self.conn.get_object(container, filename)
        metadata = json.loads(body)
        LOG.debug(_('_read_metadata finished (%s)') % metadata)
        return metadata

    def store(self, snapshot_metadata, iterator, size):
        """Backup the given file to swift using the given snapshot metadata."""
           
        try:
            # upload snapshot metadata
            snapshot = WorkloadMgrDB().db.snapshot_get(self.context, snapshot_metadata['snapshot_id'])

            # upload workload metadata
            workload = WorkloadMgrDB().db.workload_get(self.context, snapshot.workload_id)
            self._create_workload_container_n_metadata(self.context, workload)

            self._create_snapshot_metadata(self.context, snapshot)
            container = self._generate_workload_container_name(workload)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=str(err))
        
        read_wrapper = ReadWrapper(iterator, {'function': WorkloadMgrDB().db.snapshot_update,
                                              'context': self.context,
                                              'id':snapshot_metadata['snapshot_id']})
        
        object_prefix = self._generate_swift_object_name_prefix(snapshot_metadata)

        object_id = 1
        object_list = []
        object_name = None
        uploaded_size=0
        #TODO(gbasava): make this only one file snapshot...dynamic large object
        while uploaded_size < size:
            time.sleep(5)
            object_name = '%s/%s_%05d' % (object_prefix, snapshot_metadata['vm_disk_resource_snap_id'], object_id)
            obj = {}
            obj[object_name] = {}
            
            obj[object_name]['offset'] = uploaded_size
            if size - uploaded_size >= self.data_block_size_bytes:
                obj[object_name]['length'] = self.data_block_size_bytes
            else:
                obj[object_name]['length'] = size - uploaded_size
            
            try:
                etag = self.conn.put_object(container, object_name, iterator, obj[object_name]['length'])
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=str(err))
            uploaded_size = uploaded_size + obj[object_name]['length']
            """
            md5 = hashlib.md5(data).hexdigest()
            obj[object_name]['md5'] = md5
            LOG.debug(_('snapshot MD5 for %(object_name)s: %(md5)s') % locals())
            if etag != md5:
                err = _('error writing object to swift, MD5 of object in '
                        'swift %(etag)s is not the same as MD5 of object sent '
                        'to swift %(md5)s') % locals()
                raise exception.InvalidBackup(reason=err)
            """
            object_list.append(obj)
            object_id += 1
            LOG.debug(_('Calling eventlet.sleep(0)'))
            eventlet.sleep(0)
        
        try:
            self._write_metadata(snapshot_metadata, container, object_list)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=str(err))
        return object_name

    def _restore_v1(self, snapshot_metadata, restore_to_file_path):
        """Restore a v1 swift volume snapshot from swift."""

        try:
            snapshot = WorkloadMgrDB().db.snapshot_get(self.context, snapshot_metadata['snapshot_id'])
            workload = WorkloadMgrDB().db.workload_get(self.context, snapshot.workload_id)
            container = self._generate_workload_container_name(workload)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=str(err))
        
        try:
            metadata = self._read_metadata(container, snapshot_metadata)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=str(err))

        metadata_objects = metadata['objects']
        metadata_object_names = []
        for metadata_object in metadata_objects:
            metadata_object_names.extend(metadata_object.keys())
        LOG.debug(_('metadata_object_names = %s') % metadata_object_names)
        prune_list = [self._metadata_filename(snapshot_metadata)]
        swift_object_names = [swift_object_name for swift_object_name in
                              self._generate_object_names(container, snapshot_metadata)
                              if swift_object_name not in prune_list]


        for metadata_object_name in metadata_object_names:
            if metadata_object_name not in swift_object_names:
                err = _('restore_snapshot aborted. %s is not available in the swift', (metadata_object_name))
                raise exception.InvalidBackup(reason=err)

        fileobj = file(restore_to_file_path, 'wb')
        for metadata_object in metadata_objects:
            object_name = metadata_object.keys()[0]
            try:
                (resp, body) = self.conn.get_object(container, object_name, resp_chunk_size = 65536)
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=str(err))
            
            uploaded_size_incremental = 0
            for chunk in body:
                fileobj.write(chunk)
                read_size = len(chunk)
                uploaded_size_incremental = uploaded_size_incremental + read_size
                if ((uploaded_size_incremental > (5 * 1024 * 1024)) or (read_size < 65536)):
                    object = WorkloadMgrDB().db.restore_update(self.context, 
                                                               snapshot_metadata['restore_id'], 
                                                               {'uploaded_size_incremental': uploaded_size_incremental})
                    print "progress_percent: " + str(object.progress_percent) + "%"
                    #LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': object.progress_percent,})
                    uploaded_size_incremental = 0                
                
            # force flush every write to avoid long blocking write on close
            fileobj.flush()
            os.fsync(fileobj.fileno())
            # Restoring a snapshot to a volume can take some time. Yield so other
            # threads can run, allowing for among other things the service
            # status to be updated
            eventlet.sleep(0)
        fileobj.close()
        
    def restore(self, snapshot_metadata, restore_to_file_path):
        """Restore to the given file from swift."""
       
        self._restore_v1(snapshot_metadata, restore_to_file_path)
        
    def mount(self):
        pass
    
    def get_size(self, vault_service_url):
        pass    
    
    def delete(self, snapshot):
        """Delete the given snapshot from swift."""
        container = snapshot['container']
        LOG.debug('delete started, snapshot: %s, container: %s, prefix: %s',
                  snapshot['id'], container, snapshot['objecturl'])

        if container is not None:
            swift_object_names = []
            try:
                swift_object_names = self._generate_object_names(snapshot)
            except Exception:
                LOG.warn(_('swift error while listing objects, continuing'
                           ' with delete'))

            for swift_object_name in swift_object_names:
                try:
                    self.conn.delete_object(container, swift_object_name)
                except socket.error as err:
                    raise exception.SwiftConnectionFailed(reason=str(err))
                except Exception:
                    LOG.warn(_('swift error while deleting object %s, '
                               'continuing with delete') % swift_object_name)
                else:
                    LOG.debug(_('deleted swift object: %(swift_object_name)s'
                                ' in container: %(container)s') % locals())
                # Deleting a snapshot's objects from swift can take some time.
                # Yield so other threads can run
                eventlet.sleep(0)

        LOG.debug(_('delete %s finished') % snapshot_metadata['snapshot_id'])
