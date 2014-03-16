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
               default=True,
               help='Store in local file system'),
    cfg.StrOpt('wlm_vault_local_directory',
               default='/tmp',
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
        
    def get_snapshot_file_path(self, snapshot_metadata):
        snapshot_file_path = '/snapshots'
        if FLAGS.wlm_vault_local:  
            snapshot_file_path = FLAGS.wlm_vault_local_directory + snapshot_file_path 
            
        snapshot_file_path = snapshot_file_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
        snapshot_file_path = snapshot_file_path + '/vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        snapshot_file_path = snapshot_file_path + '/vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'], 
                                                                      snapshot_metadata['resource_name'].replace(' ',''))
        snapshot_file_path = snapshot_file_path + '/' + snapshot_metadata['vm_disk_resource_snap_id']
        return snapshot_file_path
                 

    def store_scp_local(self, snapshot_metadata, src_host, file_to_snapshot_path):
        """
        Backup the given file to local filesystem using the given snapshot metadata.
        uses SCP
        """
        copy_to_file_path = self.get_snapshot_file_path(snapshot_metadata)
        head, tail = os.path.split(copy_to_file_path)
        fileutils.ensure_tree(head)
        self.copy_remote_file(src_host, file_to_snapshot_path, copy_to_file_path)   
        return copy_to_file_path
    
    def store_scp(self, snapshot_metadata, src_host, file_to_snapshot_path):
        """Backup the given file to trilioFS using the given snapshot metadata."""
        if FLAGS.wlm_vault_local:
            return self.store_scp_local(snapshot_metadata, src_host, file_to_snapshot_path)
        from workloadmgr.vault.glusterapi import gfapi
        volume = gfapi.Volume("localhost", "vault")
        volume.mount() 
        
        copy_to_file_path = self.get_snapshot_file_path(snapshot_metadata) 
        volume.mkdir(copy_to_file_path.encode('ascii','ignore'))
        self.copy_remote_file(src_host, file_to_snapshot_path, copy_to_file_path, tvault_fs = True)  
        return copy_to_file_path    
    
    def store_local(self, snapshot_metadata, iterator):
        """Backup from the given iterator to local filesystem using the given snapshot metadata."""
        copy_to_file_path = self.get_snapshot_file_path(snapshot_metadata)
        head, tail = os.path.split(copy_to_file_path)
        fileutils.ensure_tree(head)
        vault_file = open(copy_to_file_path, 'wb') 
        #TODO(giri): The connection can be closed in the middle:  try catch block and retry?
        for chunk in iterator:
            vault_file.write(chunk)
        vault_file.close()    

        return copy_to_file_path    
    
    def store(self, snapshot_metadata, iterator):
        """Backup from the given iterator to trilioFS using the given snapshot metadata."""
        if FLAGS.wlm_vault_local:
            return self.store_local(snapshot_metadata, iterator)
        from workloadmgr.vault.glusterapi import gfapi
        volume = gfapi.Volume("localhost", "vault")
        volume.mount() 
        
        copy_to_file_path = self.get_snapshot_file_path(snapshot_metadata) 
        head, tail = os.path.split(copy_to_file_path)
        volume.mkdir(head.encode('ascii','ignore'))
        copy_to_file_path_handle = volume.creat(copy_to_file_path.encode('ascii','ignore'), os.O_RDWR, 0644)
        #TODO(giri): The connection can be closed in the middle:  try catch block and retry?
        for chunk in iterator:
            copy_to_file_path_handle.write(chunk)
        copy_to_file_path_handle.close() 
        return copy_to_file_path           
        
         
    def restore_local(self, snapshot_metadata, restore_to_file_path):
        """Restore a snapshot from the local filesystem."""
        copy_from_file_path = self.get_snapshot_file_path(snapshot_metadata)
        utils.copy_file(copy_from_file_path, restore_to_file_path)
        return    
        
    def restore(self, snapshot_metadata, restore_to_file_path):
        """Restore a snapshot from trilioFS."""
        if FLAGS.wlm_vault_local:
            return self.restore_local(snapshot_metadata, restore_to_file_path)
        from workloadmgr.vault.glusterapi import gfapi
        volume = gfapi.Volume("localhost", "vault")
        volume.mount() 
                 
        copy_from_file_path = self.get_snapshot_file_path(snapshot_metadata) 
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
