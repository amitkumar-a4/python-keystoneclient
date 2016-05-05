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
import socket

import eventlet
from oslo.config import cfg

from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr import utils
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import timeutils
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.virt import qemuimages
from workloadmgr import autolog
from workloadmgr import exception
from swiftclient.service import SwiftService, SwiftError, SwiftUploadObject
from swiftclient.exceptions import ClientException
from os.path import isfile, isdir, join
from os import environ, walk, _exit as os_exit

from threading import Thread
from functools import wraps

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

wlm_vault_opts = [
    cfg.StrOpt('vault_storage_type',
               default='none',
               help='Storage type: local, das, vault, nfs, swift-i, swift-s, s3'), 
    # swift-i: integrated(keystone), swift-s: standalone
    cfg.StrOpt('vault_data_directory',
               default='/var/triliovault',
               help='Location where snapshots will be stored'),
    cfg.StrOpt('vault_storage_nfs_export',
               default='local',
               help='NFS Export'),
    cfg.StrOpt('vault_storage_das_device',
               default='none',
               help='das device /dev/sdb'),
    cfg.StrOpt('vault_swift_auth_version',
               default='KEYSTONE_V2',
               help='KEYSTONE_V2 KEYSTONE_V3 TEMPAUTH'),                  
    cfg.StrOpt('vault_swift_auth_url',
               default='http://localhost:5000/v2.0',
               help='Keystone Authorization URL'),
    cfg.StrOpt('vault_swift_tenant',
               default='admin',
               help='Swift tenant'),                  
    cfg.StrOpt('vault_swift_username',
               default='admin',
               help='Swift username'),
    cfg.StrOpt('vault_swift_password',
               default='password',
               help='Swift password'),                                                         
    cfg.StrOpt('vault_swift_container_prefix',
               default='TrilioVault',
               help='Swift Container Prefix'), 
    cfg.StrOpt('vault_swift_segment_size',
               #default='5368709120', 5GB
               default='524288000', # 500MB
               help='Default segment size 500MB'),
    cfg.IntOpt('vault_retry_count',
               default=2,
               help='The number of times we retry on failures'),
    cfg.StrOpt('vault_swift_url_template',
               default='http://localhost:8080/v1/AUTH_%(project_id)s',
               help='The URL of the Swift endpoint'),                                                                      
    cfg.StrOpt('vault_read_chunk_size_kb',
               default=128,
               help='Read size in KB'),
    cfg.StrOpt('vault_write_chunk_size_kb',
               default=32,
               help='Write size in KB'),
                                                                            
]

CONF = cfg.CONF
CONF.register_opts(wlm_vault_opts)

def run_async(func):
    """
        run_async(func)
            function decorator, intended to make "func" run in a separate
            thread (asynchronously).
            Returns the created Thread object

            E.g.:
            @run_async
            def task1():
                do_something

            @run_async
            def task2():
                do_something_too

            t1 = task1()
            t2 = task2()
            ...
            t1.join()
            t2.join()
    """


    @wraps(func)
    def async_func(*args, **kwargs):
        func_hl = Thread(target = func, args = args, kwargs = kwargs)
        func_hl.start()
        return func_hl

    return async_func

def get_progress_tracker_directory(tracker_metadata):
    progress_tracker_directory = ''
    if CONF.vault_storage_type == 'local' or \
       CONF.vault_storage_type == 'vault' or \
       CONF.vault_storage_type == 'nfs' or \
       CONF.vault_storage_type == 'das':
        progress_tracker_directory = os.path.join(CONF.vault_data_directory + "/contego_tasks") + \
                                    '/snapshot_%s' % (tracker_metadata['snapshot_id'])
    else:
        return None
           
    fileutils.ensure_tree(progress_tracker_directory)
    utils.chmod(progress_tracker_directory, '0777')
    return progress_tracker_directory

def get_progress_tracker_path(tracker_metadata):
    progress_tracker_directory = get_progress_tracker_directory(tracker_metadata)
    if progress_tracker_directory:
        progress_tracking_file_path = os.path.join(progress_tracker_directory + '/' + tracker_metadata['resource_id'])    
        return progress_tracking_file_path
    else:
        return None      
    
def get_vault_data_directory():
    vault_data_directory = ''
    if CONF.vault_storage_type == 'local' or \
       CONF.vault_storage_type == 'vault' or \
       CONF.vault_storage_type == 'nfs' or \
       CONF.vault_storage_type == 'das':
            vault_data_directory = CONF.vault_data_directory
    else:
        vault_data_directory = CONF.vault_data_directory + "/staging/"  +  socket.gethostname()
    
    head, tail = os.path.split(vault_data_directory + '/')
    fileutils.ensure_tree(head)
    return vault_data_directory    
    
def commit_supported():
    if CONF.vault_storage_type == 'local' or \
       CONF.vault_storage_type == 'vault' or \
       CONF.vault_storage_type == 'nfs' or \
       CONF.vault_storage_type == 'das':
            return True
    else:
        return False  
    
def get_storage_type():
    return CONF.vault_storage_type

@autolog.log_method(logger=Logger) 
def mount_backup_media():
    """ mounts storage """
    try:
        command = ['sudo', 'umount', CONF.vault_data_directory]
        subprocess.call(command, shell=False)
    except Exception as exception:
        pass
    
    try:
        command = ['sudo', 'umount', CONF.vault_data_directory]
        subprocess.call(command, shell=False)
    except Exception as exception:
        pass           
    
    try:
        command = ['sudo', 'umount', '-l', CONF.vault_data_directory]
        subprocess.call(command, shell=False)
    except Exception as exception:
        pass                
    
    if CONF.vault_storage_type == 'local':
        pass
    elif CONF.vault_storage_type == 'vault':
        pass  
    elif CONF.vault_storage_type == 'nfs':        
         command = ['timeout', '-sKILL', '30' , 'sudo', 'mount', '-o', 'nolock', CONF.vault_storage_nfs_export, CONF.vault_data_directory]
         subprocess.check_call(command, shell=False) 
         
    else: # das, swift-i, swift-s, s3
        if CONF.vault_storage_das_device != 'none':      
            try:
                command = ['sudo', 'mount', CONF.vault_storage_das_device, CONF.vault_data_directory]
                _returncode = subprocess.check_call(command, shell=False) 
            except Exception as ex:
                LOG.exception(ex)
                pass
            
def get_workload_path(workload_metadata):
    workload_path = os.path.join(get_vault_data_directory() + '/workload_%s' % (workload_metadata['workload_id']))
    return workload_path   

def get_snapshot_path(snapshot_metadata):                 
    workload_path = get_workload_path(snapshot_metadata)
    snapshot_path = workload_path + '/snapshot_%s' % (snapshot_metadata['snapshot_id'])
    return snapshot_path

def get_snapshot_vm_path(snapshot_vm_metadata):                 
    snapshot_path = get_snapshot_path(snapshot_vm_metadata)
    snapshot_vm_path = snapshot_path + '/vm_id_%s' % (snapshot_vm_metadata['snapshot_vm_id'])    
    return snapshot_vm_path

def get_snapshot_vm_resource_path(snapshot_vm_resource_metadata):                 
    snapshot_vm_path = get_snapshot_vm_path(snapshot_vm_resource_metadata)
    snapshot_vm_resource_path = snapshot_vm_path + '/vm_res_id_%s_%s' % (snapshot_vm_resource_metadata['snapshot_vm_resource_id'], 
                                                                         snapshot_vm_resource_metadata['snapshot_vm_resource_name'].replace(' ',''))
    return snapshot_vm_resource_path    
            
def get_snapshot_vm_disk_resource_path(snapshot_vm_disk_resource_metadata):
    snapshot_vm_resource_path = get_snapshot_vm_resource_path(snapshot_vm_disk_resource_metadata)
    snapshot_vm_disk_resource_path = snapshot_vm_resource_path + '/' + snapshot_vm_disk_resource_metadata['vm_disk_resource_snap_id']
    return snapshot_vm_disk_resource_path

def get_restore_staging_path(restore_metadata):
    vault_data_directory = CONF.vault_data_directory + "/staging/"  +  socket.gethostname()
    restore_staging_path = os.path.join(vault_data_directory + '/restore_%s' % (restore_metadata['restore_id']))
    return restore_staging_path                 

def get_restore_vm_staging_path(restore_vm_metadata): 
    restore_staging_path = get_restore_staging_path(restore_vm_metadata)
    restore_vm_staging_path = restore_staging_path + '/vm_id_%s' % (restore_vm_metadata['snapshot_vm_id'])
    return restore_vm_staging_path
                    
def get_restore_vm_resource_staging_path(restore_vm_resource_metadata):                 
    restore_vm_staging_path = get_restore_vm_staging_path(restore_vm_resource_metadata)
    restore_vm_resource_staging_path = restore_vm_staging_path + '/vm_res_id_%s_%s' % (restore_vm_resource_metadata['snapshot_vm_resource_id'], 
                                                                    restore_vm_resource_metadata['snapshot_vm_resource_name'].replace(' ',''))
    return restore_vm_resource_staging_path  
            
def get_restore_vm_disk_resource_staging_path(restore_vm_disk_resource_metadata):
    restore_vm_resource_staging_path = get_restore_vm_resource_staging_path(restore_vm_disk_resource_metadata)
    restore_vm_disk_resource_staging_path = restore_vm_resource_staging_path + '/' + restore_vm_disk_resource_metadata['vm_disk_resource_snap_id']
    return restore_vm_disk_resource_staging_path

def get_swift_container(context, workload_metadata):
    swift_list_all(context, container = None)
    if os.path.isfile('/tmp/swift.out'):
        with open("/tmp/swift.out") as f:
            content = f.readlines()
        for container in content:
            container = container.replace('\n', '')
            if container.endswith('_' + workload_metadata['workload_id']):
                return container    
    
    if len(CONF.vault_swift_container_prefix):
        container = CONF.vault_swift_container_prefix + '_'
    else:
        container = ''
    container = container + workload_metadata['workload_name'] + '_' + workload_metadata['workload_id']
    return container
    
@autolog.log_method(logger=Logger) 
def workload_delete(context, workload_metadata):
    try:
        workload_path  = get_workload_path(workload_metadata)
        if CONF.vault_storage_type == 'local' or \
           CONF.vault_storage_type == 'vault' or \
           CONF.vault_storage_type == 'nfs' or \
           CONF.vault_storage_type == 'das':   
            if os.path.isdir(workload_path):
                shutil.rmtree(workload_path)
        elif CONF.vault_storage_type == 'swift-i':
                pass
        elif CONF.vault_storage_type == 'swift-s':
            container = get_swift_container(context, workload_metadata)
            if os.path.isdir(workload_path):
                shutil.rmtree(workload_path)            
            swift_delete_folder(context, workload_path, container)
            swift_delete_container(context, container)
            swift_delete_container(context, container + '_segments')  
        elif CONF.vault_storage_type == 's3':
                pass                      
    except Exception as ex:
        LOG.exception(ex)  

@autolog.log_method(logger=Logger)         
def snapshot_delete(context, snapshot_metadata):
    try:
        snapshot_path = get_snapshot_path(snapshot_metadata)
        if CONF.vault_storage_type == 'local' or \
           CONF.vault_storage_type == 'vault' or \
           CONF.vault_storage_type == 'nfs' or \
           CONF.vault_storage_type == 'das':
            if os.path.isdir(snapshot_path):
                shutil.rmtree(snapshot_path)
        elif CONF.vault_storage_type == 'swift-i':
                pass
        elif CONF.vault_storage_type == 'swift-s':
                if os.path.isdir(snapshot_path):
                    shutil.rmtree(snapshot_path)
                swift_delete_folder(context, snapshot_path, get_swift_container(context, snapshot_metadata))  
        elif CONF.vault_storage_type == 's3':
                pass     
    except Exception as ex:
        LOG.exception(ex)

@autolog.log_method(logger=Logger)         
def put_object(path, json_data):
    head, tail = os.path.split(path)
    fileutils.ensure_tree(head)
    with open(path, 'w') as json_file:
        json_file.write(json_data)
    return    

@autolog.log_method(logger=Logger)     
def get_object(path):
    path = get_vault_data_directory() + '/' + path
    with open(path, 'r') as json_file:
        return json_file.read()
 
@autolog.log_method(logger=Logger)     
def get_workloads(context):
    download_metadata_from_object_store(context)
    parent_path = get_vault_data_directory()
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

@autolog.log_method(logger=Logger) 
def upload_snapshot_metatdata_to_object_store(context, snapshot_metadata):
    if CONF.vault_storage_type == 'swift-i' or CONF.vault_storage_type == 'swift-s': 
        workload_path = get_workload_path(snapshot_metadata)
        snapshot_path = get_snapshot_path(snapshot_metadata)
        container = get_swift_container(context, snapshot_metadata)
        try:
            WorkloadMgrDB().db.snapshot_update(context, snapshot_metadata['snapshot_id'], {'progress_msg': 'Uploading snapshot metadata to object store'}) 
            swift_upload_files(context, [get_vault_data_directory() + "/settings_db"], container)
            swift_upload_files(context, [workload_path + '/workload_db'], container)
            swift_upload_files(context, [workload_path + '/workload_vms_db'], container)
            for dirName, subdirList, fileList in os.walk(snapshot_path):
                for fname in fileList:
                    file_path = dirName + '/' + fname
                    if  "/snapshot_db" in file_path or \
                        "/snapshot_vms_db" in file_path or \
                        "/resources_db" in file_path or \
                        "/network_db" in file_path or \
                        "/security_group_db" in file_path or \
                        "/disk_db"  in file_path:      
                            swift_upload_files(context, [file_path], container)
        except Exception as ex:
            LOG.exception(ex)
            WorkloadMgrDB().db.snapshot_update(context, snapshot_metadata['snapshot_id'], {'progress_msg': 'Retrying to upload snapshot metadata to object store'}) 
            swift_upload_files(context, [get_vault_data_directory() + "/settings_db"], container)
            swift_upload_files(context, [workload_path + '/workload_db'], container)
            swift_upload_files(context, [workload_path + '/workload_vms_db'], container)
            for dirName, subdirList, fileList in os.walk(snapshot_path):
                for fname in fileList:
                    file_path = dirName + '/' + fname
                    if  "/snapshot_db" in file_path or \
                        "/snapshot_vms_db" in file_path or \
                        "/resources_db" in file_path or \
                        "/network_db" in file_path or \
                        "/security_group_db" in file_path or \
                        "/disk_db"  in file_path:      
                            swift_upload_files(context, [file_path], container)
                    
        purge_workload_from_staging_area(context, snapshot_metadata)        
    elif CONF.vault_storage_type == 's3':
        pass
    
@autolog.log_method(logger=Logger) 
def upload_snapshot_vm_to_object_store(context, snapshot_vm_metadata):
    if CONF.vault_storage_type == 'swift-i' or CONF.vault_storage_type == 'swift-s': 
        WorkloadMgrDB().db.snapshot_update(context, snapshot_vm_metadata['snapshot_id'], {'progress_msg': 'Uploading virtual machine snapshot to object store'}) 
        snapshot_vm_path = get_snapshot_vm_path(snapshot_vm_metadata)
        container = get_swift_container(context, snapshot_vm_metadata)
        try:
            swift_upload_files(context, [snapshot_vm_path], container)
        except Exception as ex:
            LOG.exception(ex)
            WorkloadMgrDB().db.snapshot_update(context, snapshot_vm_metadata['snapshot_id'], {'progress_msg': 'Retrying to upload virtual machine snapshot to object store'})
            swift_upload_files(context, [snapshot_vm_path], container)
    elif CONF.vault_storage_type == 's3':
        pass    
    
@autolog.log_method(logger=Logger) 
def upload_snapshot_vm_resource_to_object_store(context, snapshot_vm_resource_metadata):
    start_time = timeutils.utcnow()
    if CONF.vault_storage_type == 'swift-i' or CONF.vault_storage_type == 'swift-s': 
        progress_msg = "Uploading '"+ snapshot_vm_resource_metadata['snapshot_vm_resource_name'] + "' of '" + snapshot_vm_resource_metadata['snapshot_vm_name'] + "' to object store"
        WorkloadMgrDB().db.snapshot_update(context, snapshot_vm_resource_metadata['snapshot_id'], {'progress_msg': progress_msg}) 
        snapshot_vm_resource_path = get_snapshot_vm_path(snapshot_vm_resource_metadata)
        container = get_swift_container(context, snapshot_vm_resource_metadata)
        try:
            swift_upload_files(context, [snapshot_vm_resource_path], container)
        except Exception as ex:
            LOG.exception(ex)
            progress_msg = "Retrying to upload '"+ snapshot_vm_resource_metadata['snapshot_vm_resource_name'] + "' of '" + snapshot_vm_resource_metadata['snapshot_vm_name'] + "' to object store"
            WorkloadMgrDB().db.snapshot_update(context, snapshot_vm_resource_metadata['snapshot_id'], {'progress_msg': progress_msg})
            swift_upload_files(context, [snapshot_vm_resource_path], container)
    elif CONF.vault_storage_type == 's3':
        return 0
    else:
        return 0
    return int((timeutils.utcnow() - start_time).total_seconds()) 

@run_async 
@autolog.log_method(logger=Logger)
def upload_snapshot_vm_disk_resource_to_object_store(context, 
                                                     snapshot_vm_disk_resource_metadata, 
                                                     snapshot_vm_disk_resource_path):
    fileutils.ensure_tree('/var/run/workloadmgr')
    progress_tracking_file_path = '/var/run/workloadmgr' + '/' + snapshot_vm_disk_resource_metadata['vm_disk_resource_snap_id']
    with open(progress_tracking_file_path, "w+") as progress_tracking_file:
        progress_tracking_file.write('In Progress')    
    if CONF.vault_storage_type == 'swift-i' or CONF.vault_storage_type == 'swift-s': 
        progress_msg = "Uploading '"+ snapshot_vm_disk_resource_metadata['snapshot_vm_resource_name'] + "' of '" + snapshot_vm_disk_resource_metadata['snapshot_vm_name'] + "' to object store"
        LOG.info(progress_msg)
        object_name = get_snapshot_vm_disk_resource_path(snapshot_vm_disk_resource_metadata)
        object_name = object_name.replace(get_vault_data_directory(), '', 1)
        container = get_swift_container(context, snapshot_vm_disk_resource_metadata)
        try:
            swift_upload_files(context, [snapshot_vm_disk_resource_path], container, object_name=object_name)
        except Exception as ex:
            LOG.exception(ex)
            progress_msg = "Retrying to upload '"+ snapshot_vm_disk_resource_metadata['snapshot_vm_resource_name'] + "' of '" + snapshot_vm_disk_resource_metadata['snapshot_vm_name'] + "' to object store"
            LOG.info(progress_msg)
            swift_upload_files(context, [snapshot_vm_disk_resource_path], container, object_name=object_name)
    elif CONF.vault_storage_type == 's3':
        pass
    else:
        pass
    with open(progress_tracking_file_path, "w+") as progress_tracking_file:
        progress_tracking_file.write('Completed')       
    
@autolog.log_method(logger=Logger) 
def download_metadata_from_object_store(context):
    start_time = timeutils.utcnow()
    if CONF.vault_storage_type == 'swift-i': 
        return 0
    elif CONF.vault_storage_type == 'swift-s':
        purge_staging_area(context) 
        swift_list_all(context, container = None)
        cmd = get_swift_base_cmd(context)    
        if os.path.isfile('/tmp/swift.out'):
            with open("/tmp/swift.out") as f:
                content = f.readlines()
            for container in content:
                if container.startswith(CONF.vault_swift_container_prefix):
                    swift_download_metadata_from_object_store(context, container.replace('\n', ''))
    elif CONF.vault_storage_type == 's3':
        return 0
    else:
        return 0
    return int((timeutils.utcnow() - start_time).total_seconds())  
    

@autolog.log_method(logger=Logger)     
def download_snapshot_vm_from_object_store(context, snapshot_vm_metadata):
    start_time = timeutils.utcnow()
    if CONF.vault_storage_type == 'swift-i' or CONF.vault_storage_type == 'swift-s': 
        WorkloadMgrDB().db.restore_update(context, snapshot_vm_metadata['restore_id'], {'progress_msg': 'Downloading virtual machine snapshot from object store'})  
        snapshot_vm_folder = get_snapshot_vm_path(snapshot_vm_metadata)
        container = get_swift_container(context, snapshot_vm_metadata)
        swift_download_folder(context, snapshot_vm_folder, container)       
    elif CONF.vault_storage_type == 's3':
        return 0
    else:
        return 0
    return int((timeutils.utcnow() - start_time).total_seconds())  
    
@autolog.log_method(logger=Logger)     
def download_snapshot_vm_resource_from_object_store(context, snapshot_vm_resource_metadata):
    start_time = timeutils.utcnow()    
    if CONF.vault_storage_type == 'swift-i' or CONF.vault_storage_type == 'swift-s': 
        try:
            progress_msg = "Downloading '" + snapshot_vm_resource_metadata['snapshot_vm_resource_name'] +\
                           "' of '" + snapshot_vm_resource_metadata['snapshot_vm_name'] + "' from object store"
            WorkloadMgrDB().db.restore_update(context, snapshot_vm_resource_metadata['restore_id'], {'progress_msg': progress_msg})  
        except:
            pass
        snapshot_vm_resource_folder = get_snapshot_vm_resource_path(snapshot_vm_resource_metadata)
        container = get_swift_container(context, snapshot_vm_resource_metadata)
        swift_download_folder(context, snapshot_vm_resource_folder, container)
    elif CONF.vault_storage_type == 's3':
        return 0
    else:
        return 0
    return int((timeutils.utcnow() - start_time).total_seconds())        

@autolog.log_method(logger=Logger)         
def swift_upload_files(context, files, container, object_name = None): 
    """ upload a files or directories to swift """
    options = {}
    if CONF.vault_storage_type == 'swift-i':
        if not context:
            raise exception.NovaException(msg=('Error: context is none with integrated swift')) 
        auth_token = context.auth_token
        object_storage_url = CONF.vault_swift_url_template % context.to_dict()
        auth_url = None
        user_name = None
        password = None
        tenant_name = None          
    else:
        auth_token = None
        object_storage_url = None
        auth_url = CONF.vault_swift_auth_url
        user_name = CONF.vault_swift_username
        password = CONF.vault_swift_password
        tenant_name = CONF.vault_swift_tenant        
    
    if CONF.vault_swift_auth_version == 'TEMPAUTH':
        options = {'use_slo': False, 'verbose': 1, 'os_username': None, 'os_user_domain_name': None, 
                   'os_cacert': None, 'os_tenant_name': None, 'os_user_domain_id': None, 'header': [], 
                   'auth_version': '1.0', 'ssl_compression': True, 'os_password': None, 'os_user_id': None, 
                   'skip_identical': True, 'segment_container': None, 'os_project_id': None, 'snet': False, 
                   'object_uu_threads': 10, 'object_name': object_name, 'os_tenant_id': None, 
                   'os_project_name': None, 'os_service_type': None, 'segment_size': CONF.vault_swift_segment_size, 'os_help': None, 
                   'object_threads': 10, 'os_storage_url': object_storage_url, 'insecure': False, 'segment_threads': 10, 
                   'auth': auth_url, 'os_auth_url': None, 
                   'user': user_name, 'key': password, 'os_region_name': None, 
                   'info': False, 'retries': 5, 'os_project_domain_id': None, 'checksum': True, 
                   'changed': True, 'leave_segments': False, 'os_auth_token': auth_token, 
                   'os_options': {'project_name': None, 'region_name': None, 'tenant_name': None, 
                                  'user_domain_name': None, 'endpoint_type': None, 'object_storage_url': object_storage_url, 
                                  'project_domain_id': None, 'user_id': None, 'user_domain_id': None, 
                                  'tenant_id': None, 'service_type': None, 'project_id': None, 
                                  'auth_token': auth_token, 'project_domain_name': None}, 
                   'debug': False, 'os_project_domain_name': None, 'os_endpoint_type': None, 'verbose': 1}
        
    else:
        if CONF.vault_swift_auth_version == 'KEYSTONE_V2':
            auth_version = '2.0'
        else:
            auth_version =  '3'
        options = { 'use_slo': False, 'verbose': 1, 'os_username': user_name, 'os_user_domain_name': None, 
                    'os_cacert': None, 'os_tenant_name': tenant_name, 'os_user_domain_id': None, 'header': [], 
                    'auth_version': auth_version, 'ssl_compression': True, 'os_password': password, 'os_user_id': None, 
                    'skip_identical': True, 'segment_container': None, 'os_project_id': None, 'snet': False, 
                    'object_uu_threads': 10, 'object_name': object_name, 'os_tenant_id': None, 
                    'os_project_name': None, 'os_service_type': None, 'segment_size': CONF.vault_swift_segment_size, 'os_help': None, 
                    'object_threads': 10, 'os_storage_url': object_storage_url, 'insecure': False, 'segment_threads': 10, 
                    'auth': auth_url, 'os_auth_url': auth_url, 
                    'user': user_name, 'key': password, 'os_region_name': None, 
                    'info': False, 'retries': 5, 'os_project_domain_id': None, 'checksum': True, 
                    'changed': True, 'leave_segments': False, 'os_auth_token': auth_token, 
                    'os_options': {'project_name': None, 'region_name': None, 'tenant_name': tenant_name, 
                                   'user_domain_name': None, 'endpoint_type': None, 'object_storage_url': object_storage_url, 
                                   'project_domain_id': None, 'user_id': None, 'user_domain_id': None, 
                                   'tenant_id': None, 'service_type': None, 'project_id': None, 
                                   'auth_token': auth_token, 'project_domain_name': None}, 
                    'debug': False, 'os_project_domain_name': None, 'os_endpoint_type': None, 'verbose': 1}
    

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
                        o, object_name=o.replace(get_vault_data_directory(), '', 1)
                    ) for o in objs
                ]
                dir_markers = [
                    SwiftUploadObject(
                        None, object_name=d.replace(get_vault_data_directory(), '', 1), options={'dir_marker': True}
                    ) for d in dir_markers
                ]                

            for r in swift.upload(container, objs + dir_markers):
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
                        LOG.warning('Warning: failed to create container %r%s', container, msg )
                        raise exception.ErrorOccurred(reason = ('Warning: failed to create container %r%s', container, msg))
                    else:
                        LOG.warning("%s" % error)
                        too_large = (isinstance(error, ClientException) and
                                     error.http_status == 413)
                        if too_large and options['verbose'] > 0:
                            LOG.error("Consider using the --segment-size option to chunk the object")
                        raise exception.ErrorOccurred(reason = error)                            
        
        
        except SwiftError as ex:
            LOG.exception(ex)
            raise  
        except Exception as ex:
            LOG.exception(ex)
            raise 
        
@autolog.log_method(logger=Logger)        
def get_swift_base_cmd(context):
    if CONF.vault_storage_type == 'swift-i':
        if not context:
            raise exception.NovaException(msg=('Error: context is none with integrated swift')) 
        object_storage_url = CONF.vault_swift_url_template % context.to_dict()
        if CONF.vault_swift_auth_version == 'KEYSTONE_V2':
            cmd = ["swift",
                   "--auth-version", "2",
                   "--os-auth-token", context.auth_token,
                   "--os-storage-url", object_storage_url]
        else:
            cmd = ["swift",
                   "--auth-version", "3",
                   "--os-auth-token", context.auth_token,
                   "--os-storage-url", object_storage_url]
        
    else:     
        if CONF.vault_swift_auth_version == 'TEMPAUTH':
            cmd = ["swift",
                   "-A", CONF.vault_swift_auth_url,
                   "-U", CONF.vault_swift_username,
                   "-K", "******"]        
        else:
            if CONF.vault_swift_auth_version == 'KEYSTONE_V2':
                cmd = ["swift",
                       "--auth-version", "2",
                       "--os-auth-url", CONF.vault_swift_auth_url,
                       "--os-tenant-name", CONF.vault_swift_tenant,
                       "--os-username", CONF.vault_swift_username,
                       "--os-password", "******"]
            else:
                cmd = ["swift",
                       "--auth-version", "3",
                       "--os-auth-url", CONF.vault_swift_auth_url,
                       "--os-tenant-name", CONF.vault_swift_tenant,
                       "--os-username", CONF.vault_swift_username,
                       "--os-password", "******"]
    return cmd

@autolog.log_method(logger=Logger)        
def swift_list_all(context, container):
    cmd = get_swift_base_cmd(context)
    if container:
        cmd_list = cmd + [ "list", container]
    else:
        cmd_list = cmd + [ "list" ]
    cmd_list_str = " ".join(cmd_list)
    for idx, opt in enumerate(cmd_list):
        if opt == "--os-password":
            cmd_list[idx+1] = CONF.vault_swift_password
            break
        if opt == "-K":
            cmd_list[idx+1] = CONF.vault_swift_password
            break              
    if os.path.isfile('/tmp/swift.out'):
        os.remove('/tmp/swift.out')    

    LOG.debug(cmd_list_str)   
    for i in range(0,CONF.vault_retry_count):
        try:
            with open('/tmp/swift.out', "w") as f:                                
                subprocess.check_call(cmd_list, shell=False, stdout=f)
                break
        except Exception as ex:
            LOG.exception(ex)                                                      
            if i == CONF.vault_retry_count:
                raise ex
            
@autolog.log_method(logger=Logger) 
def swift_delete_container(context, container):
    cmd = get_swift_base_cmd(context)    
    cmd_delete = cmd + [ "delete", container]
    cmd_delete_str = " ".join(cmd_delete)
    for idx, opt in enumerate(cmd_delete):
        if opt == "--os-password":
            cmd_delete[idx+1] = CONF.vault_swift_password
            break
        if opt == "-K":
            cmd_delete[idx+1] = CONF.vault_swift_password
            break                                             
    LOG.debug(cmd_delete_str)                                  
    for i in range(0,CONF.vault_retry_count):
        try:                                
            subprocess.check_call(cmd_delete, shell=False, cwd=get_vault_data_directory())
            break
        except Exception as ex:
            LOG.exception(ex)
            if i == CONF.vault_retry_count:
                raise ex               
                
@autolog.log_method(logger=Logger) 
def swift_delete_folder(context, folder, container):
    swift_list_all(context, container)
    cmd = get_swift_base_cmd(context)    
    if os.path.isfile('/tmp/swift.out'):
        with open("/tmp/swift.out") as f:
            content = f.readlines()
        for line in content:
            if folder.replace(get_vault_data_directory() + '/', '', 1) in line:
                cmd_delete = cmd + [ "delete", container, line.replace('\n', '')]
                cmd_delete_str = " ".join(cmd_delete)
                for idx, opt in enumerate(cmd_delete):
                    if opt == "--os-password":
                        cmd_delete[idx+1] = CONF.vault_swift_password
                        break
                    if opt == "-K":
                        cmd_delete[idx+1] = CONF.vault_swift_password
                        break                                             
                LOG.debug(cmd_delete_str)                                  
                for i in range(0,CONF.vault_retry_count):
                    try:                                
                        subprocess.check_call(cmd_delete, shell=False, cwd=get_vault_data_directory())
                        break
                    except Exception as ex:
                        LOG.exception(ex)
                        if i == CONF.vault_retry_count:
                            raise ex                                 

@autolog.log_method(logger=Logger) 
def swift_download_folder(context, folder, container):
    swift_list_all(context, container)
    cmd = get_swift_base_cmd(context) 
    if os.path.isfile('/tmp/swift.out'):
        with open("/tmp/swift.out") as f:
            content = f.readlines()
        if len(content) <= 0:
            msg = 'Error downloading objects from ' + folder.replace(get_vault_data_directory() + '/', '', 1)
            msg = msg + ' in container ' + container
            raise exception.ErrorOccurred(reason=msg)
        for line in content:
            if folder.replace(get_vault_data_directory() + '/', '', 1) in line:
                cmd_download = cmd + [ "download", container, line.replace('\n', '')]
                cmd_download_str = " ".join(cmd_download)
                for idx, opt in enumerate(cmd_download):
                    if opt == "--os-password":
                        cmd_download[idx+1] = CONF.vault_swift_password
                        break
                    if opt == "-K":
                        cmd_download[idx+1] = CONF.vault_swift_password
                        break                                           
                LOG.debug(cmd_download_str)                                  
                for i in range(0,CONF.vault_retry_count):
                    try:                                
                        subprocess.check_call(cmd_download, shell=False, cwd=get_vault_data_directory())
                        break
                    except Exception as ex:
                        LOG.exception(ex)
                        if i == CONF.vault_retry_count:
                            raise ex                                                           

@autolog.log_method(logger=Logger) 
def purge_staging_area(context):
    try:
        if CONF.vault_storage_type == 'swift-s' or \
           CONF.vault_storage_type == 'swift-i' or \
           CONF.vault_storage_type == 's3':     
            shutil.rmtree(get_vault_data_directory())   
                   
    except Exception as ex:
        LOG.exception(ex) 
        
@autolog.log_method(logger=Logger) 
def purge_workload_from_staging_area(context, workload_metadata):
    try:
        workload_path  = get_workload_path(workload_metadata)
        if CONF.vault_storage_type == 'swift-s' or \
           CONF.vault_storage_type == 'swift-i' or \
           CONF.vault_storage_type == 's3':     
            if os.path.isdir(workload_path):
                shutil.rmtree(workload_path)            
              
    except Exception as ex:
        LOG.exception(ex) 

@autolog.log_method(logger=Logger) 
def purge_snapshot_from_staging_area(context, snapshot_metadata):
    try:
        snapshot_path  = get_snapshot_path(snapshot_metadata)
        if CONF.vault_storage_type == 'swift-s' or \
           CONF.vault_storage_type == 'swift-i' or \
           CONF.vault_storage_type == 's3':     
            if os.path.isdir(snapshot_path):
                shutil.rmtree(snapshot_path)     
              
    except Exception as ex:
        LOG.exception(ex) 
        
    try:
        progress_tracker_directory = get_progress_tracker_directory(snapshot_metadata)        
        if os.path.isdir(progress_tracker_directory):
            shutil.rmtree(progress_tracker_directory)     
              
    except Exception as ex:
        LOG.exception(ex)         

@autolog.log_method(logger=Logger)                 
def purge_snapshot_vm_from_staging_area(context, snapshot_vm_metadata):
    try:
        snapshot_vm_path  = get_snapshot_vm_path(snapshot_vm_metadata)
        if CONF.vault_storage_type == 'swift-s' or \
           CONF.vault_storage_type == 'swift-i' or \
           CONF.vault_storage_type == 's3':           
            if os.path.isdir(snapshot_vm_path):
                shutil.rmtree(snapshot_vm_path)     
                   
    except Exception as ex:
        LOG.exception(ex)  
        
@autolog.log_method(logger=Logger)                 
def purge_snapshot_vm_resource_from_staging_area(context, snapshot_vm_resource_metadata):
    try:
        snapshot_vm_resource_path  = get_snapshot_vm_resource_path(snapshot_vm_resource_metadata)
        if CONF.vault_storage_type == 'swift-s' or \
           CONF.vault_storage_type == 'swift-i' or \
           CONF.vault_storage_type == 's3':     
            if os.path.isdir(snapshot_vm_resource_path):
                shutil.rmtree(snapshot_vm_resource_path)     
                 
    except Exception as ex:
        LOG.exception(ex) 
        
@autolog.log_method(logger=Logger) 
def purge_restore_from_staging_area(context, restore_metadata):
    try:
        restore_staging_path  = get_restore_staging_path(restore_metadata)
        if os.path.isdir(restore_staging_path):
            shutil.rmtree(restore_staging_path)     
              
    except Exception as ex:
        LOG.exception(ex) 

@autolog.log_method(logger=Logger)                 
def purge_restore_vm_from_staging_area(context, restore_vm_metadata):
    try:
        restore_vm_staging_path  = get_restore_vm_staging_path(restore_vm_metadata)
        if os.path.isdir(restore_vm_staging_path):
            shutil.rmtree(restore_vm_staging_path)     
                   
    except Exception as ex:
        LOG.exception(ex)  
        
@autolog.log_method(logger=Logger)                 
def purge_restore_vm_resource_from_staging_area(context, restore_vm_resource_metadata):
    try:
        restore_vm_resource_staging_path  = get_restore_vm_resource_staging_path(restore_vm_resource_metadata)
        if os.path.isdir(restore_vm_resource_staging_path):
            shutil.rmtree(restore_vm_resource_staging_path)      
                 
    except Exception as ex:
        LOG.exception(ex)                   

def get_size(vault_path):
    size = 0
    try:
        statinfo = os.stat(vault_path)
        size = statinfo.st_size
        #LOG.debug('size of ' + vault_path + ': ' + str(size))
    except Exception as ex:
        LOG.exception(ex)
    return size            

@autolog.log_method(logger=Logger) 
def get_restore_size(vault_path, disk_format, disk_type):
    restore_size = 0
    if disk_format == 'vmdk':
        try:
            vix_disk_lib_env = os.environ.copy()
            vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'
                               
            cmdspec = [ "trilio-vix-disk-cli", "-spaceforclone", disk_type, vault_path,]      
            cmd = " ".join(cmdspec)
                         
            output = check_output(cmdspec, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
            space_for_clone_str = re.search(r'\d+ Bytes Required for Cloning',output)
            restore_size = int(space_for_clone_str.group().split(" ")[0])
        except subprocess.CalledProcessError as ex:
            LOG.critical(_("cmd: %s resulted in error: %s") %(cmd, ex.output))
            LOG.exception(ex)
    return restore_size          

@autolog.log_method(logger=Logger) 
def swift_download_metadata_from_object_store(context, container):
    swift_list_all(context, container)
    cmd = get_swift_base_cmd(context)
    if os.path.isfile('/tmp/swift.out'):
        with open("/tmp/swift.out") as f:
            content = f.readlines()
        for line in content:
            if  "settings_db" in line or \
                "/workload_db" in line or \
                "/workload_vms_db" in line or \
                "/snapshot_db" in line or \
                "/snapshot_vms_db" in line or \
                "/resources_db" in line or \
                "/network_db" in line or \
                "/security_group_db" in line or \
                "/disk_db"  in line:
                    cmd_download = cmd + [ "download", container, line.replace('\n', '')]
                    cmd_download_str = " ".join(cmd_download)
                    for idx, opt in enumerate(cmd_download):
                        if opt == "--os-password":
                            cmd_download[idx+1] = CONF.vault_swift_password
                            break
                        if opt == "-K":
                            cmd_download[idx+1] = CONF.vault_swift_password
                            break                                                  
                    LOG.debug(cmd_download_str)
                    for i in range(0,CONF.vault_retry_count):
                        try:                                
                            subprocess.check_call(cmd_download, shell=False, cwd=get_vault_data_directory())
                            break
                        except Exception as ex:
                            LOG.exception(ex)
                            if i == CONF.vault_retry_count:
                                raise ex                              
                    
                    
def get_total_capacity(context):
    total_capacity = 1
    total_utilization = 1 
    try:
        if CONF.vault_storage_type == 'local' or \
           CONF.vault_storage_type == 'vault' or \
           CONF.vault_storage_type == 'nfs' or \
           CONF.vault_storage_type == 'das':   
                stdout, stderr = utils.execute('df', get_vault_data_directory())
                if stderr != '':
                    msg = _('Could not execute df command successfully. Error %s'), (stderr)
                    raise exception.ErrorOccurred(reason=msg)
            
                # Filesystem     1K-blocks      Used Available Use% Mounted on
                # /dev/sda1      464076568 248065008 192431096  57% /
            
                fields = stdout.split('\n')[0].split()
                values = stdout.split('\n')[1].split()
                
                total_capacity = int(values[1]) * 1024
                total_utilization = int(values[2]) * 1024
                try:
                    stdout, stderr = utils.execute('du', '-shb', get_vault_data_directory(), run_as_root=True)
                    if stderr != '':
                        msg = _('Could not execute du command successfully. Error %s'), (stderr)
                        raise exception.ErrorOccurred(reason=msg)
                    #196022926557    /var/triliovault
                    du_values = stdout.split()                
                    total_utilization = int(du_values[0])
                except Exception as ex:
                    LOG.exception(ex)                
        elif CONF.vault_storage_type == 'swift-i':
            pass
        elif CONF.vault_storage_type == 'swift-s':
            cmd = get_swift_base_cmd(context)
            cmd_stat = cmd + ["stat"]
            for idx, opt in enumerate(cmd_stat):
                if opt == "--os-password":
                    cmd_stat[idx+1] = CONF.vault_swift_password
                    break
                if opt == "-K":
                    cmd_stat[idx+1] = CONF.vault_swift_password
                    break   
            stdout, stderr = utils.execute(*cmd_stat) 
            values = stdout.split('\n')
            for val in values:
                if "Meta Quota-Bytes:" in val:
                    total_capacity = int(val.split(':')[1].strip())                    
                
                if "Bytes:" in val:
                    if val.split(':')[0].strip() == 'Bytes':
                        total_utilization = int(val.split(':')[1].strip())
 
        elif CONF.vault_storage_type == 's3':
            pass                          
    except Exception as ex:
        LOG.exception(ex)    
    return total_capacity,total_utilization                                           
