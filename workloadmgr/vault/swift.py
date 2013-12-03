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

import eventlet
from oslo.config import cfg

from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import timeutils
from swiftclient import client as swift

LOG = logging.getLogger(__name__)

wlm_swift_opts = [
    cfg.StrOpt('wlm_swift_url',
               default='http://localhost:8080/v1/AUTH_',
               help='The URL of the Swift endpoint'),
    cfg.StrOpt('wlm_swift_container',
               default='wlm_snapshots',
               help='The default Swift container to use for workload snapshots'),
    cfg.IntOpt('wlm_swift_object_size',
               default=524288000,
               help='The size in bytes of Swift snapshot objects'),
    cfg.IntOpt('wlm_swift_retry_attempts',
               default=3,
               help='The number of retries to make for Swift operations'),
    cfg.IntOpt('wlm_swift_retry_backoff',
               default=2,
               help='The backoff time in seconds between Swift retries'),
    cfg.StrOpt('wlm_compression_algorithm',
               default= 'none', #'zlib',
               help='Compression algorithm (None to disable)'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(wlm_swift_opts)


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
        self.swift_url = '%s%s' % (FLAGS.wlm_swift_url,
                                   self.context.project_id)
        self.az = FLAGS.storage_availability_zone
        self.data_block_size_bytes = FLAGS.wlm_swift_object_size
        self.swift_attempts = FLAGS.wlm_swift_retry_attempts
        self.swift_backoff = FLAGS.wlm_swift_retry_backoff
        self.compressor = \
            self._get_compressor(FLAGS.wlm_compression_algorithm)
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

    def _create_container(self, context, snapshot_metadata):
        snapshot_id = snapshot_metadata['snapshot_id']
        container = snapshot_metadata['snapshot_id']
        LOG.debug(_('_create_container started, container: %(container)s,'
                    'snapshot: %(snapshot_id)s') % locals())
        if container is None:
            container = FLAGS.wlm_swift_container
        if not self._check_container_exists(container):
            self.conn.put_container(container)
        return container

                                     
    def _generate_swift_object_name_prefix(self, snapshot_metadata):
        az = 'az_zone1' #TODO(gbasava): Fix with right parameters later
        jobrun = 'jobrun_%s' % (snapshot_metadata['snapshot_id'])
        vm_id = 'vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        vm_res_id = 'vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'],
                                         snapshot_metadata['resource_name'])
        timestamp = timeutils.strtime(fmt="%Y%m%d%H%M%S")
        prefix = jobrun + '/' + vm_id + '/' + vm_res_id
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

    def _metadata_filename(self, snapshot_metadata):
        object_prefix = self._generate_swift_object_name_prefix(snapshot_metadata)
        swift_object_name = snapshot_metadata['vm_disk_resource_snap_id']
        filename = '%s/%s_metadata' % (object_prefix, swift_object_name)
        return filename

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

    def store(self, snapshot_metadata, file_to_snapshot_path):
        """Backup the given file to swift using the given snapshot metadata."""

        try:
            container = self._create_container(self.context, snapshot_metadata)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=str(err))
        
        
        object_prefix = self._generate_swift_object_name_prefix(snapshot_metadata)
        fileobj = file(file_to_snapshot_path)
        
        file_to_snapshot_size = os.path.getsize(file_to_snapshot_path)

        object_id = 1
        object_list = []
        object_name = None
        #TODO(gbasava): make this only one file snapshot...dynamic large object
        while True:
            time.sleep(10)
            data_block_size_bytes = self.data_block_size_bytes
            object_name = '%s/%s_%05d' % (object_prefix, snapshot_metadata['vm_disk_resource_snap_id'], object_id)
            obj = {}
            obj[object_name] = {}
            obj[object_name]['offset'] = fileobj.tell()
            data = fileobj.read(data_block_size_bytes)
            obj[object_name]['length'] = len(data)
            if data == '':
                break
            LOG.debug(_('reading chunk of data from volume'))
            if self.compressor is not None:
                algorithm = FLAGS.wlm_compression_algorithm.lower()
                obj[object_name]['compression'] = algorithm
                data_size_bytes = len(data)
                data = self.compressor.compress(data)
                comp_size_bytes = len(data)
                LOG.debug(_('compressed %(data_size_bytes)d bytes of data'
                            ' to %(comp_size_bytes)d bytes using '
                            '%(algorithm)s') % locals())
            else:
                LOG.debug(_('not compressing data'))
                obj[object_name]['compression'] = 'none'

            reader = StringIO.StringIO(data)
            LOG.debug(_('About to put_object'))
            try:
                etag = self.conn.put_object(container, object_name, reader)
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=str(err))
            LOG.debug(_('swift MD5 for %(object_name)s: %(etag)s') % locals())
            md5 = hashlib.md5(data).hexdigest()
            obj[object_name]['md5'] = md5
            LOG.debug(_('snapshot MD5 for %(object_name)s: %(md5)s') % locals())
            if etag != md5:
                err = _('error writing object to swift, MD5 of object in '
                        'swift %(etag)s is not the same as MD5 of object sent '
                        'to swift %(md5)s') % locals()
                raise exception.InvalidBackup(reason=err)
            object_list.append(obj)
            object_id += 1
            LOG.debug(_('Calling eventlet.sleep(0)'))
            eventlet.sleep(0)
        
        fileobj.close()
        try:
            self._write_metadata(snapshot_metadata, container, object_list)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=str(err))
        #LOG.debug(_('snapshot %s finished.') % snapshot_metadata['vm_disk_resource_snap_id'])
        return object_name

    def _restore_v1(self, snapshot_metadata, restore_to_file_path):
        """Restore a v1 swift volume snapshot from swift."""
        try:
            container = self._create_container(self.context, snapshot_metadata)
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
                (resp, body) = self.conn.get_object(container, object_name)
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=str(err))
            compression_algorithm = metadata_object[object_name]['compression']
            decompressor = self._get_compressor(compression_algorithm)
            if decompressor is not None:
                LOG.debug(_('decompressing data using %s algorithm') %
                          compression_algorithm)
                decompressed = decompressor.decompress(body)
                fileobj.write(decompressed)
            else:
                fileobj.write(body)

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
        try:
            container = self._create_container(self.context, snapshot_metadata)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=str(err))
        
        object_prefix = self._generate_swift_object_name_prefix(snapshot_metadata)
 
       
        self._restore_v1(snapshot_metadata, restore_to_file_path)
        
        LOG.debug(_('restore of snapshot %s finished.') % snapshot_metadata['snapshot_id'])

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


def get_vault_service(context):
    return SwiftBackupService(context)
