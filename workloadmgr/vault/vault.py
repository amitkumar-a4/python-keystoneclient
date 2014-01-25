# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Implementation of a snapshot service that uses Vault as the backend

"""

import os
import StringIO
import types
from ctypes import *

import eventlet
from oslo.config import cfg

from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr import utils
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import timeutils
from workloadmgr.vault import swift

LOG = logging.getLogger(__name__)

wlm_vault_opts = [
    cfg.StrOpt('wlm_vault_read_chunk_size_kb',
               default=128,
               help='Read size in KB'),
    cfg.StrOpt('wlm_vault_write_chunk_size_kb',
               default=32,
               help='Write size in KB'),
    cfg.StrOpt('wlm_vault_service',
               default='vault',
               help='Write size in KB'),
    cfg.StrOpt('wlm_vault_local',
               default=False,
               help='Store in local file system'),
    cfg.StrOpt('wlm_vault_local_directory',
               default='/tmp/snapshots',
               help='Location where snapshots will be stored'),        
]

FLAGS = flags.FLAGS
FLAGS.register_opts(wlm_vault_opts)

class VaultBackupService(base.Base):
    def __init__(self, context):
        self.context = context
        
    def copy_remote_file(self, src_host, src, dest, tvault_fs=False):
        try:
            if tvault_fs:
                utils.execute('gcp', 'root@' + src_host + ':' + src, dest, run_as_root=False)
            else:
                utils.execute('scp', 'root@' + src_host + ':' + src, dest, run_as_root=False)
        except:
            #TODO(giri): handle exception
            pass
      

    def store_local(self, snapshot_metadata, src_host, file_to_snapshot_path):
        """Backup the given file to local filesystem using the given snapshot metadata."""
                 
        copy_to_file_path = FLAGS.wlm_vault_local_directory
        fileutils.ensure_tree(copy_to_file_path)
        copy_to_file_path = copy_to_file_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
        fileutils.ensure_tree(copy_to_file_path)
        copy_to_file_path = copy_to_file_path + '/vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        fileutils.ensure_tree(copy_to_file_path)
        copy_to_file_path = copy_to_file_path + '/vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'], 
                                                                      snapshot_metadata['resource_name'].replace(' ',''))
        fileutils.ensure_tree(copy_to_file_path)
        copy_to_file_path = copy_to_file_path + '/' + snapshot_metadata['vm_disk_resource_snap_id']
        self.copy_remote_file(src_host, file_to_snapshot_path, copy_to_file_path)   
        return copy_to_file_path
    
    def restore_local(self, snapshot_metadata, restore_to_file_path):
        """Restore a snapshot from the local filesystem."""
                 
        copy_from_file_path = FLAGS.wlm_vault_local_directory
        copy_from_file_path = copy_from_file_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
        copy_from_file_path = copy_from_file_path + '/vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        copy_from_file_path = copy_from_file_path + '/vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'], 
                                                                      snapshot_metadata['resource_name'].replace(' ',''))
        copy_from_file_path = copy_from_file_path + '/' + snapshot_metadata['vm_disk_resource_snap_id']
        utils.copy_file(copy_from_file_path, restore_to_file_path)
        return    
    
    
    def store(self, snapshot_metadata, src_host, file_to_snapshot_path):
        """Backup the given file to trilioFS using the given snapshot metadata."""
        if FLAGS.wlm_vault_local:
            return self.store_local(snapshot_metadata, src_host, file_to_snapshot_path)
        from workloadmgr.vault.glusterapi import gfapi
        volume = gfapi.Volume("localhost", "vault")
        volume.mount() 
                 
        copy_to_file_path = '/snapshots'
        volume.mkdir(copy_to_file_path.encode('ascii','ignore'))
        copy_to_file_path = copy_to_file_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
        volume.mkdir(copy_to_file_path.encode('ascii','ignore'))
        copy_to_file_path = copy_to_file_path + '/vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        volume.mkdir(copy_to_file_path.encode('ascii','ignore'))
        copy_to_file_path = copy_to_file_path + '/vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'], 
                                                                      snapshot_metadata['resource_name'].replace(' ',''))
        volume.mkdir(copy_to_file_path.encode('ascii','ignore'))
        copy_to_file_path = copy_to_file_path + '/' + snapshot_metadata['vm_disk_resource_snap_id']
        self.copy_remote_file(src_host, file_to_snapshot_path, copy_to_file_path, tvault_fs = True)  
        """
        copy_to_file_path_handle = volume.creat(copy_to_file_path.encode('ascii','ignore'), os.O_RDWR, 0644)
        file_to_snapshot_handle = file(file_to_snapshot_path, 'rb')
        file_to_snapshot_size = int(os.stat(file_to_snapshot_path).st_size)
        while file_to_snapshot_size > 0:
            chunk =  file_to_snapshot_handle.read(FLAGS.wlm_vault_write_chunk_size_kb*1024)
            copy_to_file_path_handle.write(chunk)
            file_to_snapshot_size -= FLAGS.wlm_vault_write_chunk_size_kb*1024
        file_to_snapshot_handle.close()
        """
        return copy_to_file_path
        
    def restore(self, snapshot_metadata, restore_to_file_path):
        """Restore a snapshot from trilioFS."""
        if FLAGS.wlm_vault_local:
            return self.restore_local(snapshot_metadata, restore_to_file_path)
        from workloadmgr.vault.glusterapi import gfapi
        volume = gfapi.Volume("localhost", "vault")
        volume.mount() 
                 
        copy_from_file_path = '/snapshots'
        copy_from_file_path = copy_from_file_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
        copy_from_file_path = copy_from_file_path + '/vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        copy_from_file_path = copy_from_file_path + '/vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'], 
                                                                      snapshot_metadata['resource_name'].replace(' ',''))
        copy_from_file_path = copy_from_file_path + '/' + snapshot_metadata['vm_disk_resource_snap_id']
        copy_from_file_path_handle = volume.open(copy_from_file_path.encode('ascii','ignore'), os.O_RDONLY)
        restore_to_file_path_handle = file(restore_to_file_path, 'wb')
        rbuf = create_string_buffer(FLAGS.wlm_vault_read_chunk_size_kb*1024)
        rc = copy_from_file_path_handle.read_buffer(rbuf, FLAGS.wlm_vault_read_chunk_size_kb*1024)
        while rc > 0:
            restore_to_file_path_handle.write(rbuf[:rc])
            rc = copy_from_file_path_handle.read_buffer(rbuf, FLAGS.wlm_vault_read_chunk_size_kb*1024)
        restore_to_file_path_handle.close()
        return    


def get_vault_service(context):
    if FLAGS.wlm_vault_service == 'swift':
        return swift.SwiftBackupService(context)
    else:
        return VaultBackupService(context)
