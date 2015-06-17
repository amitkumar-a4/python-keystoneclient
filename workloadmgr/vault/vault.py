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
import subprocess
from subprocess import check_output
import re
import shutil

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

from workloadmgr import exception
from swiftclient.service import SwiftService, SwiftError, SwiftUploadObject
from swiftclient.exceptions import ClientException
from os.path import isfile, isdir, join
from os import environ, walk, _exit as os_exit

LOG = logging.getLogger(__name__)

wlm_vault_opts = [
    cfg.StrOpt('wlm_vault_storage_type',
               default='none',
               help='Storage type: local, das, vault, nfs, swift-i, swift-s, s3'), 
    # swift-i: integrated(keystone) swift, swift-s: standalone swift
    cfg.StrOpt('wlm_vault_local_directory',
               default='/opt/stack/data/wlm',
               help='Location where snapshots will be stored'),
    cfg.StrOpt('wlm_vault_storage_nfs_export',
               default='local',
               help='NFS Export'),
    cfg.StrOpt('wlm_vault_storage_das_device',
               default='none',
               help='das device /dev/sdb'),
    cfg.StrOpt('wlm_vault_swift_auth_url',
               default='http://localhost:5000/v2.0',
               help='Keystone Authorization URL'),
    cfg.StrOpt('wlm_vault_swift_tenant',
               default='admin',
               help='Swift tenant'),                  
    cfg.StrOpt('wlm_vault_swift_username',
               default='admin',
               help='Swift username'),
    cfg.StrOpt('wlm_vault_swift_password',
               default='password',
               help='Swift password'),                                                         
    cfg.StrOpt('wlm_vault_swift_container',
               default='TrilioVault',
               help='NFS Export'), 
    cfg.StrOpt('wlm_vault_swift_segment_size',
               default='5368709120',
               help='Default segment size 5GB'),                     
    cfg.StrOpt('wlm_vault_read_chunk_size_kb',
               default=128,
               help='Read size in KB'),
    cfg.StrOpt('wlm_vault_write_chunk_size_kb',
               default=32,
               help='Write size in KB'),
                                                                            
]

FLAGS = flags.FLAGS
FLAGS.register_opts(wlm_vault_opts)

def commit_supported():
    if FLAGS.wlm_vault_storage_type == 'local' or \
       FLAGS.wlm_vault_storage_type == 'vault' or \
       FLAGS.wlm_vault_storage_type == 'nfs' or \
       FLAGS.wlm_vault_storage_type == 'das':
            return True
    else:
        return False    

def mount_backup_media():
    """ mounts storage """
    try:
        command = ['sudo', 'umount', FLAGS.wlm_vault_local_directory]
        subprocess.call(command, shell=False)
    except Exception as exception:
        pass
    
    try:
        command = ['sudo', 'umount', FLAGS.wlm_vault_local_directory]
        subprocess.call(command, shell=False)
    except Exception as exception:
        pass           
    
    try:
        command = ['sudo', 'umount', FLAGS.wlm_vault_local_directory]
        subprocess.call(command, shell=False)
    except Exception as exception:
        pass                
    
    if FLAGS.wlm_vault_storage_type == 'local':
        pass
    elif FLAGS.wlm_vault_storage_type == 'vault':
        pass  
    elif FLAGS.wlm_vault_storage_type == 'nfs':        
        command = ['timeout', '-sKILL', '30' , 'sudo', 'mount', '-o', 'nolock', FLAGS.wlm_vault_storage_nfs_export, FLAGS.wlm_vault_local_directory]
        subprocess.check_call(command, shell=False) 
    else: # das, swift-i, swift-s, s3
        if FLAGS.wlm_vault_storage_das_device != 'none':      
            command = ['sudo', 'mount', FLAGS.wlm_vault_storage_das_device, FLAGS.wlm_vault_local_directory]
            subprocess.check_call(command, shell=False) 
            
def get_workload_path(workload_metadata, staging = False):
    workload_path = 'snapshots'
    if FLAGS.wlm_vault_storage_type == 'local' or \
       FLAGS.wlm_vault_storage_type == 'vault' or \
       FLAGS.wlm_vault_storage_type == 'nfs' or \
       FLAGS.wlm_vault_storage_type == 'das' or \
       staging == True:  
            workload_path = os.path.join(FLAGS.wlm_vault_local_directory + "/" + workload_path) 
    
    workload_path = workload_path + '/workload_%s' % (workload_metadata['workload_id'])
    return workload_path   

def get_snapshot_path(snapshot_metadata, staging = False):                 
    workload_path = get_workload_path(snapshot_metadata, staging)
    snapshot_path = workload_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
    return snapshot_path

def get_snapshot_vm_path(snapshot_vm_metadata, staging = False):                 
    snapshot_path = get_snapshot_path(snapshot_vm_metadata, staging)
    snapshot_vm_path = snapshot_path + '/vm_id_%s' % (snapshot_vm_metadata['snapshot_vm_id'])    
    return snapshot_vm_path   
            
def get_snapshot_file_path(snapshot_file_metadata, staging = False):
    snapshot_vm_path = get_snapshot_vm_path(snapshot_file_metadata, staging)
    snapshot_file_path = snapshot_vm_path + '/vm_res_id_%s_%s' % (snapshot_file_metadata['snapshot_vm_resource_id'], 
                                                                    snapshot_file_metadata['resource_name'].replace(' ',''))
    snapshot_file_path = snapshot_file_path + '/' + snapshot_file_metadata['vm_disk_resource_snap_id']
    return snapshot_file_path

def workload_delete(workload_metadata, staging = False):
    try:
        workload_path  = get_workload_path(workload_metadata, staging)
        if staging == True:
            shutil.rmtree(workload_path)
        elif FLAGS.wlm_vault_storage_type == 'local' or \
           FLAGS.wlm_vault_storage_type == 'vault' or \
           FLAGS.wlm_vault_storage_type == 'nfs' or \
           FLAGS.wlm_vault_storage_type == 'das':   
                shutil.rmtree(workload_path)
        elif FLAGS.wlm_vault_storage_type == 'swift-i':
                pass
        elif FLAGS.wlm_vault_storage_type == 'swift-s':
                swift_delete_folder(workload_path)  
        elif FLAGS.wlm_vault_storage_type == 's3':
                pass                      
    except Exception as ex:
        LOG.exception(ex)  
        
def snapshot_delete(snapshot_metadata, staging = False):
    try:
        snapshot_path = get_snapshot_path(snapshot_metadata, staging)
        if staging == True:
            shutil.rmtree(snapshot_path)
        elif FLAGS.wlm_vault_storage_type == 'local' or \
           FLAGS.wlm_vault_storage_type == 'vault' or \
           FLAGS.wlm_vault_storage_type == 'nfs' or \
           FLAGS.wlm_vault_storage_type == 'das':
                shutil.rmtree(snapshot_path)
        elif FLAGS.wlm_vault_storage_type == 'swift-i':
                pass
        elif FLAGS.wlm_vault_storage_type == 'swift-s':
                swift_delete_folder(snapshot_path)  
        elif FLAGS.wlm_vault_storage_type == 's3':
                pass     
    except Exception as ex:
        LOG.exception(ex)
        
def put_object(path, json_data):
    head, tail = os.path.split(path)
    fileutils.ensure_tree(head)
    with open(path, 'w') as json_file:
        json_file.write(json_data)
    return    
    
def get_object(path):
    path = FLAGS.wlm_vault_local_directory + '/snapshots/' + path
    with open(path, 'r') as json_file:
        return json_file.read()
    
def get_workloads(staging = False):
    parent_path = FLAGS.wlm_vault_local_directory + '/snapshots/'
    workload_urls = []
    try:
        for name in os.listdir(parent_path):
            if os.path.isdir(os.path.join(parent_path, name)):
                workload_url = {'workload_url': name, 'snapshot_urls': []}
                for subname in os.listdir(os.path.join(parent_path, workload_url['workload_url'])):
                    if os.path.isdir(os.path.join(parent_path, workload_url['workload_url'], subname)):
                        workload_url['snapshot_urls'].append(os.path.join(workload_url['workload_url'], subname))
                workload_urls.append(workload_url)
    except Exception as ex:
        LOG.exception(ex)
    return workload_urls  

def upload_to_object_store(context, snapshot_metadata):
    if FLAGS.wlm_vault_storage_type == 'swift-i': 
        WorkloadMgrDB().db.snapshot_update(context, snapshot_metadata['snapshot_id'], {'progress_msg': 'Uploading snapshot to object store'}) 
        workload_path = get_workload_path(snapshot_metadata, staging = True)
        snapshot_path = get_snapshot_path(snapshot_metadata, staging = True)
        swift_upload_files([snapshot_path], context)
        swift_upload_files([workload_path + '/workload_db'], context)
        swift_upload_files([workload_path + '/workload_vms_db'], context)
        workload_delete(snapshot_metadata, staging = True)
    if FLAGS.wlm_vault_storage_type == 'swift-s': 
        WorkloadMgrDB().db.snapshot_update(context, snapshot_metadata['snapshot_id'], {'progress_msg': 'Uploading snapshot to object store'}) 
        workload_path = get_workload_path(snapshot_metadata, staging = True)
        snapshot_path = get_snapshot_path(snapshot_metadata, staging = True)
        swift_upload_files([snapshot_path], context = None)
        swift_upload_files([workload_path + '/workload_db'], context = None)
        swift_upload_files([workload_path + '/workload_vms_db'], context = None)        
        workload_delete(snapshot_metadata, staging = True)        
    elif FLAGS.wlm_vault_storage_type == 's3':
        pass
    
def download_snapshot_vm_from_object_store(context, snapshot_vm_metadata):
    if FLAGS.wlm_vault_storage_type == 'swift-i':
        WorkloadMgrDB().db.restore_update(context, snapshot_vm_metadata['restore_id'], {'progress_msg': 'Downloading vm snapshot from object store'})  
        snapshot_vm_folder = get_snapshot_vm_path(snapshot_vm_metadata)
        swift_download_folder(snapshot_vm_folder, context)
    if FLAGS.wlm_vault_storage_type == 'swift-s': 
        WorkloadMgrDB().db.restore_update(context, snapshot_vm_metadata['restore_id'], {'progress_msg': 'Downloading vm snapshot from object store'})  
        snapshot_vm_folder = get_snapshot_vm_path(snapshot_vm_metadata)
        swift_download_folder(snapshot_vm_folder, context = None)       
    elif FLAGS.wlm_vault_storage_type == 's3':
        pass    
        
def swift_upload_files(files, context = None): 
    """ upload a files or directories to swift """
    options = { 'use_slo': False, 'verbose': 1, 'os_username': FLAGS.wlm_vault_swift_username, 'os_user_domain_name': None, 
                'os_cacert': None, 'os_tenant_name': FLAGS.wlm_vault_swift_tenant, 'os_user_domain_id': None, 'header': [], 
                'auth_version': '2.0', 'ssl_compression': True, 'os_password': FLAGS.wlm_vault_swift_password, 'os_user_id': None, 
                'skip_identical': True, 'segment_container': None, 'os_project_id': None, 'snet': False, 
                'object_uu_threads': 10, 'object_name': None, 'os_tenant_id': None, 
                'os_project_name': None, 'os_service_type': None, 'segment_size': FLAGS.wlm_vault_swift_segment_size, 'os_help': None, 
                'object_threads': 10, 'os_storage_url': None, 'insecure': False, 'segment_threads': 10, 
                'auth': FLAGS.wlm_vault_swift_auth_url, 'os_auth_url': FLAGS.wlm_vault_swift_auth_url, 
                'user': FLAGS.wlm_vault_swift_username, 'key': FLAGS.wlm_vault_swift_password, 'os_region_name': None, 
                'info': False, 'retries': 5, 'os_project_domain_id': None, 'checksum': True, 
                'changed': True, 'leave_segments': False, 'os_auth_token': None, 
                'os_options': {'project_name': None, 'region_name': None, 'tenant_name': FLAGS.wlm_vault_swift_tenant, 
                               'user_domain_name': None, 'endpoint_type': None, 'object_storage_url': None, 
                               'project_domain_id': None, 'user_id': None, 'user_domain_id': None, 
                               'tenant_id': None, 'service_type': None, 'project_id': None, 
                               'auth_token': None, 'project_domain_name': None}, 
                'debug': False, 'os_project_domain_name': None, 'os_endpoint_type': None,
                'verbose': 1}
    

    if options['object_name'] is not None:
        if len(files) > 1:
            raise exception.ErrorOccurred(reason="object-name only be used with 1 file or dir")
        else:
            orig_path = files[0]

    if options['segment_size']:
        try:
            # If segment size only has digits assume it is bytes
            int(options['segment_size'])
        except ValueError:
            try:
                size_mod = "BKMG".index(options['segment_size'][-1].upper())
                multiplier = int(options['segment_size'][:-1])
            except ValueError:
                raise exception.ErrorOccurred(reason="Invalid segment size")

            options.segment_size = str((1024 ** size_mod) * multiplier)
    
    with SwiftService(options=options) as swift:
        try:
            objs = []
            dir_markers = []
            for f in files:
                if isfile(f):
                    objs.append(f)
                elif isdir(f):
                    for (_dir, _ds, _fs) in walk(f):
                        if not (_ds + _fs):
                            dir_markers.append(_dir)
                        else:
                            objs.extend([join(_dir, _f) for _f in _fs])
                else:
                    raise exception.ErrorOccurred(reason="Local file '%s' not found."% f)

            # Now that we've collected all the required files and dir markers
            # build the tuples for the call to upload
            if options['object_name'] is not None:
                objs = [
                    SwiftUploadObject(
                        o, object_name=o.replace(
                            orig_path, options['object_name'], 1
                        )
                    ) for o in objs
                ]
                dir_markers = [
                    SwiftUploadObject(
                        None, object_name=d.replace(
                            orig_path, options['object_name'], 1
                        ), options={'dir_marker': True}
                    ) for d in dir_markers
                ]
            else:
                objs = [
                    SwiftUploadObject(
                        o, object_name=o.replace(FLAGS.wlm_vault_local_directory, '', 1)
                    ) for o in objs
                ]
                dir_markers = [
                    SwiftUploadObject(
                        None, object_name=d.replace(FLAGS.wlm_vault_local_directory, '', 1), options={'dir_marker': True}
                    ) for d in dir_markers
                ]                

            for r in swift.upload(FLAGS.wlm_vault_swift_container, objs + dir_markers):
                if r['success']:
                    if options['verbose']:
                        if 'attempts' in r and r['attempts'] > 1:
                            if 'object' in r:
                                LOG.info('%s [after %d attempts]' % (r['object'], r['attempts']))
                        else:
                            if 'object' in r:
                                LOG.info(r['object'])
                            elif 'for_object' in r:
                                LOG.info('%s segment %s' % (r['for_object'], r['segment_index']))
                else:
                    error = r['error']
                    if 'action' in r and r['action'] == "create_container":
                        # it is not an error to be unable to create the
                        # container so print a warning and carry on
                        if isinstance(error, ClientException):
                            if (r['headers'] and
                                    'X-Storage-Policy' in r['headers']):
                                msg = ' with Storage Policy %s' % \
                                      r['headers']['X-Storage-Policy'].strip()
                            else:
                                msg = ' '.join(str(x) for x in (
                                    error.http_status, error.http_reason)
                                )
                                if error.http_response_content:
                                    if msg:
                                        msg += ': '
                                    msg += error.http_response_content[:60]
                                msg = ': %s' % msg
                        else:
                            msg = ': %s' % error
                        LOG.warning('Warning: failed to create container %r%s', FLAGS.wlm_vault_swift_container, msg )
                    else:
                        LOG.warning("%s" % error)
                        too_large = (isinstance(error, ClientException) and
                                     error.http_status == 413)
                        if too_large and options['verbose'] > 0:
                            LOG.error("Consider using the --segment-size option to chunk the object")
        
        
        except SwiftError as ex:
            LOG.exception(ex)
            raise  
        except Exception as ex:
            LOG.exception(ex)
            raise                                              

def swift_delete_folder(folder, context = None):
    cmd = "swift"
    cmd = cmd + " --os-auth-url " + FLAGS.wlm_vault_swift_auth_url
    cmd = cmd + " --os-tenant-name " + FLAGS.wlm_vault_swift_tenant
    cmd = cmd + " --os-username " + FLAGS.wlm_vault_swift_username
    cmd = cmd + " --os-password " + FLAGS.wlm_vault_swift_password
    
    cmd_list = cmd + " list " + FLAGS.wlm_vault_swift_container + " > " + "/tmp/swift.out"
    
    if os.path.isfile('/tmp/swift.out'):
        os.remove('/tmp/swift.out')   
    os.system('bash -c ' + "'" + cmd_list + "'")
    if os.path.isfile('/tmp/swift.out'):
        with open("/tmp/swift.out") as f:
            content = f.readlines()
        for line in content:
            if folder in line:
                cmd_delete = cmd + " delete " + FLAGS.wlm_vault_swift_container + " " + line
                os.system('bash -c ' + "'" + cmd_delete + "'")

def swift_download_folder(folder, context = None):
    cmd = "swift"
    cmd = cmd + " --os-auth-url " + FLAGS.wlm_vault_swift_auth_url
    cmd = cmd + " --os-tenant-name " + FLAGS.wlm_vault_swift_tenant
    cmd = cmd + " --os-username " + FLAGS.wlm_vault_swift_username
    cmd = cmd + " --os-password " + FLAGS.wlm_vault_swift_password
    
    cmd_list = cmd + " list " + FLAGS.wlm_vault_swift_container + " > " + "/tmp/swift.out"
    
    if os.path.isfile('/tmp/swift.out'):
        os.remove('/tmp/swift.out')   
    os.system('bash -c ' + "'" + cmd_list + "'")
    if os.path.isfile('/tmp/swift.out'):
        cmd = "cd " + FLAGS.wlm_vault_local_directory + " && " + cmd
        with open("/tmp/swift.out") as f:
            content = f.readlines()
        for line in content:
            if folder in line:
                cmd_download = cmd + " download " + FLAGS.wlm_vault_swift_container + " " + line
                os.system('bash -c ' + "'" + cmd_download + "'")   

def purge_workload_from_staging_area(context, workload_metadata):
    try:
        workload_path  = get_workload_path(workload_metadata, staging = True)
        if FLAGS.wlm_vault_storage_type == 'swift-i':
            pass
        elif FLAGS.wlm_vault_storage_type == 'swift-s':
            shutil.rmtree(workload_path)  
        elif FLAGS.wlm_vault_storage_type == 's3':
            pass                      
    except Exception as ex:
        LOG.exception(ex) 

def purge_snapshot_from_staging_area(context, snapshot_metadata):
    try:
        snapshot_path  = get_snapshot_path(snapshot_metadata, staging = True)
        if FLAGS.wlm_vault_storage_type == 'swift-i':
            pass
        elif FLAGS.wlm_vault_storage_type == 'swift-s':
            shutil.rmtree(snapshot_path)  
        elif FLAGS.wlm_vault_storage_type == 's3':
            pass                      
    except Exception as ex:
        LOG.exception(ex) 
                
def purge_snapshot_vm_from_staging_area(context, snapshot_vm_metadata):
    try:
        snapshot_vm_path  = get_snapshot_vm_path(snapshot_vm_metadata, staging = True)
        if FLAGS.wlm_vault_storage_type == 'swift-i':
            pass
        elif FLAGS.wlm_vault_storage_type == 'swift-s':
            shutil.rmtree(snapshot_vm_path)  
        elif FLAGS.wlm_vault_storage_type == 's3':
            pass                      
    except Exception as ex:
        LOG.exception(ex)  
        
def get_size(vault_service_url):
    size = 0
    try:
        statinfo = os.stat(vault_service_url)
        size = statinfo.st_size
    except Exception as ex:
        LOG.exception(ex)
    return size            

def get_restore_size(vault_service_url, disk_format, disk_type):
    restore_size = 0
    if disk_format == 'vmdk':
        try:
            vix_disk_lib_env = os.environ.copy()
            vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                               
            cmdspec = [ "trilio-vix-disk-cli", "-spaceforclone", disk_type, vault_service_url,]      
            cmd = " ".join(cmdspec)
            for idx, opt in enumerate(cmdspec):
                if opt == "-password":
                    cmdspec[idx+1] = self._session._host_password
                    break
                          
            output = check_output(cmdspec, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
            space_for_clone_str = re.search(r'\d+ Bytes Required for Cloning',output)
            restore_size = int(space_for_clone_str.group().split(" ")[0])
        except subprocess.CalledProcessError as ex:
            LOG.critical(_("cmd: %s resulted in error: %s") %(cmd, ex.output))
            LOG.exception(ex)
    return restore_size                                    
   
class VaultBackupService(base.Base):
    def __init__(self, context):
        self.context = context

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
                print "progress_percent: " + str(snapshot_obj.progress_percent) + "%"
                #LOG.debug(_("progress_percent: %(progress_percent)s") %{'progress_percent': snapshot_obj.progress_percent,})
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
    
    def get_size(self, vault_service_url):
        size = 0
        try:
            statinfo = os.stat(vault_service_url)
            size = statinfo.st_size
        except Exception as ex:
            LOG.exception(ex)
        return size            

    def get_restore_size(self, vault_service_url, disk_format, disk_type):
        restore_size = 0
        if disk_format == 'vmdk':
            try:
                vix_disk_lib_env = os.environ.copy()
                vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                                   
                cmdspec = [ "trilio-vix-disk-cli", "-spaceforclone", disk_type, vault_service_url,]      
                cmd = " ".join(cmdspec)
                for idx, opt in enumerate(cmdspec):
                    if opt == "-password":
                        cmdspec[idx+1] = self._session._host_password
                        break
                              
                output = check_output(cmdspec, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
                space_for_clone_str = re.search(r'\d+ Bytes Required for Cloning',output)
                restore_size = int(space_for_clone_str.group().split(" ")[0])
            except subprocess.CalledProcessError as ex:
                LOG.critical(_("cmd: %s resulted in error: %s") %(cmd, ex.output))
                LOG.exception(ex)
        return restore_size
                  

def get_vault_service(context):
    return VaultBackupService(context)
    if FLAGS.wlm_vault_service == 'swift':
        return swift.SwiftBackupService(context)
    else:
        return VaultBackupService(context)
