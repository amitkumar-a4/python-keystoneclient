# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Implementation of a snapshot service that uses Vault as the backend

"""

import os
import StringIO
import types
import time
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
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.virt import qemuimages

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
    cfg.StrOpt('wlm_vault_local_directory',
               default='/tmp/wlm',
               help='Location where snapshots will be stored'),        
]

FLAGS = flags.FLAGS
FLAGS.register_opts(wlm_vault_opts)


class VaultBackupService(base.Base):
    def __init__(self, context):
        self.context = context
        
    def get_snapshot_file_path(self, snapshot_metadata):
        snapshot_file_path = '/snapshots'
        if FLAGS.wlm_vault_service == 'local':  
            snapshot_file_path = FLAGS.wlm_vault_local_directory + snapshot_file_path 
            
        snapshot_file_path = snapshot_file_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
        snapshot_file_path = snapshot_file_path + '/vm_id_%s' % (snapshot_metadata['snapshot_vm_id'])
        snapshot_file_path = snapshot_file_path + '/vm_res_id_%s_%s' % (snapshot_metadata['snapshot_vm_resource_id'], 
                                                                      snapshot_metadata['resource_name'].replace(' ',''))
        snapshot_file_path = snapshot_file_path + '/' + snapshot_metadata['vm_disk_resource_snap_id']
        return snapshot_file_path
                 

    def store(self, snapshot_metadata, iterator, size):
        """Backup from the given iterator to trilioFS using the given snapshot metadata."""
        copy_to_file_path = self.get_snapshot_file_path(snapshot_metadata) 
        head, tail = os.path.split(copy_to_file_path)
        if FLAGS.wlm_vault_service == 'local':
            fileutils.ensure_tree(head)
            vault_file = open(copy_to_file_path, 'wb') 
        else:
            from workloadmgr.vault.glusterapi import gfapi
            volume = gfapi.Volume("localhost", "vault")
            volume.mount() 
            volume.mkdir(head.encode('ascii','ignore'))
            vault_file = volume.creat(copy_to_file_path.encode('ascii','ignore'), os.O_RDWR, 0644)
        
        #TODO(giri): The connection can be closed in the middle:  try catch block and retry?
        db = WorkloadMgrDB().db
        snapshot_obj = db.snapshot_get(self.context, snapshot_metadata['snapshot_id'])
        uploaded_size_incremental = 0
        for chunk in iterator:
            vault_file.write(chunk)
            uploaded_size_incremental = uploaded_size_incremental + len(chunk)
            #update every 5MB
            if uploaded_size_incremental > (5 * 1024 * 1024):
                snapshot_obj = db.snapshot_update(self.context, snapshot_obj.id, {'uploaded_size_incremental': uploaded_size_incremental})
                LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': snapshot_obj.progress_percent,})
                uploaded_size_incremental = 0
        
        vault_file.close()
        
        if uploaded_size_incremental > 0:
            snapshot_obj = db.snapshot_update(self.context, snapshot_obj.id, {'uploaded_size_incremental': uploaded_size_incremental})
            uploaded_size_incremental = 0

        LOG.debug(_("snapshot_size: %(snapshot_size)s") %{'snapshot_size': snapshot_obj.size,})
        LOG.debug(_("uploaded_size: %(uploaded_size)s") %{'uploaded_size': snapshot_obj.uploaded_size,})
        LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': snapshot_obj.progress_percent,})
                
        return copy_to_file_path   
        
         
    def restore_local(self, snapshot_metadata, restore_to_file_path):
        """Restore a snapshot from the local filesystem."""
        copy_from_file_path = self.get_snapshot_file_path(snapshot_metadata)
        image_attr = qemuimages.qemu_img_info(copy_from_file_path)
        if snapshot_metadata['disk_format'] == 'qcow2' and image_attr.file_format == 'raw':
            qemuimages.convert_image(copy_from_file_path, restore_to_file_path, 'qcow2')
            WorkloadMgrDB().db.restore_update(  self.context, 
                                                snapshot_metadata['restore_id'], 
                                                {'uploaded_size_incremental': os.path.getsize(copy_from_file_path)})
        else:        
            restore_to_file = open(restore_to_file_path, 'wb')
            for chunk in utils.ChunkedFile(copy_from_file_path, {'function': WorkloadMgrDB().db.restore_update,
                                                                 'context': self.context,
                                                                 'id':snapshot_metadata['restore_id']}):
                restore_to_file.write(chunk)
            restore_to_file.close()

        restore_obj = WorkloadMgrDB().db.restore_get(self.context, snapshot_metadata['restore_id'])
        LOG.debug(_("restore_size: %(restore_size)s") %{'restore_size': restore_obj.size,})
        LOG.debug(_("uploaded_size: %(uploaded_size)s") %{'uploaded_size': restore_obj.uploaded_size,})
        LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': restore_obj.progress_percent,})
           
        return    
        
    def restore(self, snapshot_metadata, restore_to_file_path):
        """Restore a snapshot from trilioFS."""
        if FLAGS.wlm_vault_service == 'local':
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
