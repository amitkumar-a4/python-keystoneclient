# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Implementation of a backup target endpoint for TrilioVault
"""

import abc
import base64
import glob
import pickle
import json
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
import uuid
import threading

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
from swiftclient.service import SwiftService, SwiftError, SwiftUploadObject
from swiftclient.exceptions import ClientException
from os.path import isfile, isdir, join
from os import environ, walk, _exit as os_exit

from threading import Thread
from functools import wraps

from keystoneauth1.identity.generic import password as passMod
from keystoneauth1 import session
from keystoneclient import client

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

wlm_vault_opts = [
    cfg.StrOpt('vault_storage_type',
               default='none',
               help='Storage type: local, das, vault, nfs, swift-i, swift-s, s3'), 
    # swift-i: integrated(keystone), swift-s: standalone
    cfg.StrOpt('vault_data_directory',
               default='/var/triliovault-mounts',
               help='Location where snapshots will be stored'),
    cfg.StrOpt('vault_data_directory_old',
               default='/var/triliovault',
               help='Legacy location where snapshots will be stored'),
    cfg.StrOpt('vault_storage_nfs_export',
               default='local',
               help='NFS Export'),
    cfg.StrOpt('vault_storage_nfs_options',
               default='nolock',
               help='NFS Options'),
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
    cfg.StrOpt('trustee_role',
               default='Member',
               help='Role that trustee will impersonate'),                                                         
    cfg.StrOpt('triliovault_public_key',
               default='/etc/workloadmgr/triliovault.pub',
               help='Location where snapshots will be stored'),
    cfg.StrOpt('domain_name',
               default='default',
               help='cloud-admin user domain id'),
    cfg.StrOpt('triliovault_user_domain_id',
               default='default',
               help='triliovault user domain name'),
    cfg.StrOpt('keystone_auth_version',
               default='2.0',
               help='Keystone authentication version'),
    cfg.IntOpt('workload_full_backup_factor',
               default=50,
               help='The size of full backup compared to actual resource size in percentage'),
    cfg.IntOpt('workload_incr_backup_factor',
               default=10,
               help='The size of incremental backup compared to full backup in percentage'),
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

class TrilioVaultBackupTarget(object):

    __metaclass__ = abc.ABCMeta

    def __init__(self, backupendpoint, backup_target_type, mountpath=None):
        self.__backup_endpoint = backupendpoint
        self.__backup_target_type = backup_target_type
        self.__mountpath = mountpath or backupendpoint

    @property
    def backup_endpoint(self):
        return self.__backup_endpoint

    @property
    def backup_target_type(self):
        return self.__backup_target_type

    @property
    def mount_path(self):
        return self.__mountpath

    def __str__(self):
        return "%s:%s" % (self.backup_target_type,
                          self.backup_endpoint)

    ###
    #   All path manipulation methods
    ###
    @abc.abstractmethod
    def get_progress_tracker_directory(self, tracker_metadata):
        """
        Get the location where all tracking objects are stored. The tracking
        object is a file on NFS. It can be object in object store
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_progress_tracker_path(self, tracker_metadata):
        """
        Get the path of the tracker object based on the tracker matadata.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_workload_transfers_directory(self):
        """
        Get the path of the directory where transfer authentication keys are stored when
        transfering workload ownership between tenants of two different clouds
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_workload_transfers_path(self, transfers_metadata):
        """
        The absolute path of workload transfer file for the workload id 
        defined in transfers_metadata
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_workload_path(self, workload_metadata):
        pass

    @abc.abstractmethod
    def get_snapshot_path(self, snapshot_metadata):                 
        pass

    @abc.abstractmethod
    def get_snapshot_vm_path(self, snapshot_vm_metadata):                 
        pass

    @abc.abstractmethod
    def get_snapshot_vm_resource_path(self, snapshot_vm_resource_metadata):                 
        pass

    @abc.abstractmethod
    def get_snapshot_vm_disk_resource_path(self, snapshot_vm_disk_resource_metadata):
        pass

    @abc.abstractmethod
    def get_restore_staging_path(self, restore_metadata):
        pass

    @abc.abstractmethod
    def get_restore_vm_staging_path(self, restore_vm_metadata): 
        pass

    @abc.abstractmethod
    def get_restore_vm_resource_staging_path(self, restore_vm_resource_metadata):                 
        pass

    @abc.abstractmethod
    def get_restore_vm_disk_resource_staging_path(self, restore_vm_disk_resource_metadata):
        pass

    ##
    # purge staging area functions
    ##
    def purge_snapshot_from_staging_area(self, context, snapshot_metadata):
        directory = self.get_progress_tracker_directory(snapshot_metadata)
        shutil.rmtree(directory)
        pass

    def purge_snapshot_vm_from_staging_area(self, context, snapshot_vm_metadata):
        pass

    def purge_snapshot_vm_resource_from_staging_area(self, context, snapshot_vm_resource_metadata):
        pass

    def purge_restore_vm_from_staging_area(self, context, restore_vm_metadata):
        pass

    def purge_restore_vm_resource_from_staging_area(self, context, restore_vm_resource_metadata):
        pass

    ##
    # backup target capabilities
    ##
    @abc.abstractmethod
    def commit_supported(self):
        pass

    ##
    # backup target capabilities
    ##
    @abc.abstractmethod
    def requires_staging(self):
        pass

    ##
    # backup target capabilities
    ##
    @abc.abstractmethod
    def tracking_supported(self):
        """
        Can the backup media can be used for maintaining progress
        tracking files for tracking various snapshot and upload
        operations between data movers and triliovault backup engines
        """
        pass

    ##
    # backup target availability status
    ##
    @abc.abstractmethod
    def is_online(self):
        pass

    @abc.abstractmethod
    def mount_backup_target(self):
        pass

    @abc.abstractmethod
    def get_total_capacity(self, context):
        """
        return total capacity of the backup target and
        amount of storage that is utilized
        """
        pass

    ##
    # object manipulation methods on the backup target
    ##

    ##
    # for workload transfers
    ##
    @abc.abstractmethod
    def get_all_workload_transfers(self):
        """
        List of workload transfers on this particular backup media
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def transfers_delete(self, context, transfers_metadata):
        """
        List of workload transfers on this particular backup media
        """
        raise NotImplementedError()

    ##
    # triliovault object (json) access methods
    @abc.abstractmethod
    def put_object(self, path, json_data):
        pass

    @abc.abstractmethod
    def get_object(self, path):
        pass

    @abc.abstractmethod
    def object_exists(self, path):
        pass

    @abc.abstractmethod
    def get_object_size(self, vault_path):
        pass

    @abc.abstractmethod
    def workload_delete(self, context, workload_metadata):
        pass

    @abc.abstractmethod
    def snapshot_delete(self, context, snapshot_metadata):
        pass
  
    ##
    # upload workloadmgr objects metadata functions
    ##
    def upload_snapshot_metatdata_to_object_store(self, context,
                                                  snapshot_metadata):
        pass

    def download_metadata_from_object_store(self, context):
        return 0

def ensure_mounted():
    '''Make sure NFS share is mounted at designated location. Otherwise
       throw exception '''

    def wrap(func):
        def new_function(*args, **kw):
            if args[0].is_mounted() == False:
                raise exception.InvalidNFSMountPoint(
                    reason="'%s' is not '%s' mounted" % \
                           (args[0].mount_path, args[0].backup_endpoint))

            return func(*args, **kw)
        return new_function
    return wrap


def to_abs():
    '''convert the path to absolute path, it called with relative path'''

    def wrap(func):
        def new_function(*args, **kw):
            path = args[1]
            if not os.path.isabs(path):
                path = os.path.join(args[0].mount_path, path)
            new_args = (args[0], path)
            new_args += args[2:]
            return func(*new_args, **kw)
        return new_function
    return wrap

def get_directory_size(path):
    cmd = ['du', '-shb', path]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    out, err = p.communicate()
    return out.split('\t')[0]


class NfsTrilioVaultBackupTarget(TrilioVaultBackupTarget):
    def __init__(self, backupendpoint):
        if CONF.vault_storage_type == 'nfs':
           base64encode = base64.b64encode(backupendpoint)
           mountpath = os.path.join(CONF.vault_data_directory,
                                 base64encode)
           self.umount_backup_target_swift()
           fileutils.ensure_tree(mountpath)
           self.__mountpath = mountpath
           super(NfsTrilioVaultBackupTarget, self).__init__(backupendpoint, "nfs",
                                                         mountpath=mountpath)
           if not self.is_mounted():
              utils.chmod(mountpath, '0777')

        elif CONF.vault_storage_type == 'swift-s':
             mountpath = CONF.vault_data_directory
             self.__mountpath = mountpath
             super(NfsTrilioVaultBackupTarget, self).__init__(backupendpoint, "swift-s",
                                                         mountpath=mountpath)  

    def get_progress_tracker_directory(self, tracker_metadata):
        """
        Get the location where all tracking objects are stored. The tracking
        object is a file on NFS. It can be object in object store
        """
        mountpath = self.mount_path
        progress_tracker_directory = os.path.join(mountpath,
            "contego_tasks", 'snapshot_%s' % (tracker_metadata['snapshot_id']))

        fileutils.ensure_tree(progress_tracker_directory)
        utils.chmod(progress_tracker_directory, '0777')
        return progress_tracker_directory

    def get_progress_tracker_path(self, tracker_metadata):
        """
        Get the path of the tracker object based on the tracker matadata.
        """
        progress_tracker_directory = self.get_progress_tracker_directory(tracker_metadata)
        if progress_tracker_directory:
            progress_tracking_file_path = os.path.join(
                progress_tracker_directory,
                tracker_metadata['resource_id'])    
            return progress_tracking_file_path
        else:
            return None      

    def get_workload_transfers_directory(self):
        """
        Get the path of the directory where transfer authentication keys are stored when
        transfering workload ownership between tenants of two different clouds
        """
        workload_transfers_directory = os.path.join(self.mount_path,
                                                    "workload_transfers")

        fileutils.ensure_tree(workload_transfers_directory)
        utils.chmod(workload_transfers_directory, '0777')
        return workload_transfers_directory

    def get_workload_transfers_path(self, transfers_metadata):
        """
        The absolute path of workload transfer file for the workload id 
        defined in transfers_metadata
        """
        workload_transfers_directory = self.get_workload_transfers_directory()
        if workload_transfers_directory:
            workload_transfers_file_path = os.path.join(
                workload_transfers_directory,
                transfers_metadata['workload_id'])    
            return workload_transfers_file_path
        else:
            return None

    @ensure_mounted()
    def get_workload_path(self, workload_metadata):
        workload_path = os.path.join(self.mount_path,
            'workload_%s' % (workload_metadata['workload_id']))
        return workload_path

    #@ensure_mounted()
    #def get_openstack_workload_path(self, workload_metadata):
    #    workload_path = os.path.join(self.mount_path,
    #                    'workload_%s' % (workload_metadata['workload_id']))
    #    return workload_path
   
    @ensure_mounted()
    def get_config_workload_path(self, config_workload_metadata):
        config_workload_path = os.path.join(self.mount_path,
                                     'config_workload_%s' % (config_workload_metadata['config_workload_id']))
        return config_workload_path
    
    def get_config_backup_path(self, backup_metadata):
        workload_path = self.get_config_workload_path(backup_metadata)
        backup_path = os.path.join(workload_path,
                                     'backup_%s' % (backup_metadata['backup_id']))
        return backup_path
 
    def get_snapshot_path(self, snapshot_metadata):                 
        workload_path = self.get_workload_path(snapshot_metadata)
        snapshot_path = os.path.join(workload_path,
                            'snapshot_%s' % (snapshot_metadata['snapshot_id']))
        return snapshot_path

    def get_snapshot_vm_path(self, snapshot_vm_metadata):                 
        snapshot_path = self.get_snapshot_path(snapshot_vm_metadata)
        snapshot_vm_path = os.path.join(snapshot_path,
            'vm_id_%s' % (snapshot_vm_metadata['snapshot_vm_id']))
        return snapshot_vm_path

    def get_snapshot_vm_resource_path(self, snapshot_vm_resource_metadata):                 
        snapshot_vm_path = self.get_snapshot_vm_path(snapshot_vm_resource_metadata)
        snapshot_vm_resource_path = os.path.join(snapshot_vm_path,
            'vm_res_id_%s_%s' % (snapshot_vm_resource_metadata['snapshot_vm_resource_id'], 
            snapshot_vm_resource_metadata['snapshot_vm_resource_name'].replace(' ','')))

        return snapshot_vm_resource_path    

    def get_snapshot_vm_disk_resource_path(self, snapshot_vm_disk_resource_metadata):
        snapshot_vm_resource_path = \
            self.get_snapshot_vm_resource_path(snapshot_vm_disk_resource_metadata)
        snapshot_vm_disk_resource_path = os.path.join(snapshot_vm_resource_path,
            snapshot_vm_disk_resource_metadata['vm_disk_resource_snap_id'])

        return snapshot_vm_disk_resource_path

    def get_restore_staging_path(self, restore_metadata):
        vault_data_directory = os.path.join(self.mount_path,
                                            "staging",
                                            socket.gethostname())
        restore_staging_path = os.path.join(vault_data_directory,
            'restore_%s' % (restore_metadata['restore_id']))
        return restore_staging_path

    def get_restore_vm_staging_path(self, restore_vm_metadata): 
        restore_staging_path = self.get_restore_staging_path(restore_vm_metadata)
        restore_vm_staging_path = os.path.join(restore_staging_path,
            'vm_id_%s' % (restore_vm_metadata['snapshot_vm_id']))
        return restore_vm_staging_path

    def get_restore_vm_resource_staging_path(self, restore_vm_resource_metadata):                 
        restore_vm_staging_path = self.get_restore_vm_staging_path(restore_vm_resource_metadata)
        restore_vm_resource_staging_path = os.path.join(restore_vm_staging_path,
            'vm_res_id_%s_%s' % (restore_vm_resource_metadata['snapshot_vm_resource_id'], 
                                 restore_vm_resource_metadata['snapshot_vm_resource_name'].replace(' ','')))
        return restore_vm_resource_staging_path  

    def get_restore_vm_disk_resource_staging_path(self, restore_vm_disk_resource_metadata):
        restore_vm_resource_staging_path = self.get_restore_vm_resource_staging_path(restore_vm_disk_resource_metadata)
        restore_vm_disk_resource_staging_path = os.path.join(restore_vm_resource_staging_path,
            restore_vm_disk_resource_metadata['vm_disk_resource_snap_id'])
        return restore_vm_disk_resource_staging_path

    ##
    # backup target capabilities
    ##
    def commit_supported(self):
        return True

    ##
    # backup target capabilities
    ##
    def requires_staging(self):
        return False

    def tracking_supported(self):
        return True

    ##
    # backup target availability status
    ##
    @autolog.log_method(logger=Logger) 
    def is_online(self):
        status = False
        try:
            nfsshare = self.backup_endpoint
            nfsserver = nfsshare.split(":")[0]
            rpcinfo = utils.execute("rpcinfo", "-s", nfsserver)

            for i in rpcinfo[0].split("\n")[1:]:
                if len(i.split()) and i.split()[3] == 'mountd':
                    status = True
                    break
        except Exception as ex:
            LOG.exception(ex)

        return status 

    @autolog.log_method(logger=Logger) 
    def is_mounted(self):
        '''Make sure backup endpoint is mounted at mount_path'''
        mountpath = self.mount_path
        nfsshare = self.backup_endpoint

        if not os.path.ismount(mountpath):
            return False

        with open('/proc/mounts','r') as f:
            mounts = [{line.split()[1]:line.split()[0]}
                      for line in f.readlines() if line.split()[1] == mountpath]

        return len(mounts) and mounts[0].get(mountpath, None) == nfsshare

    def umount_backup_target_swift(self):
        try:
            command = ['sudo', 'service', 'tvault-swift', 'stop']
            subprocess.check_call(command, shell=False)
        except Exception as ex:
               pass

        try:
            command = ['sudo', 'umount', '-f', CONF.vault_data_directory]
            subprocess.call(command, shell=False)
        except Exception as exception:
            pass

    @autolog.log_method(logger=Logger) 
    def umount_backup_target(self):
        nfsshare = self.backup_endpoint
        mountpath = self.mount_path

        """ mounts storage """
        try:
            command = ['sudo', 'umount', nfsshare]
            subprocess.call(command, shell=False)
        except Exception as exception:
            pass
    
        try:
            command = ['sudo', 'umount', nfsshare]
            subprocess.call(command, shell=False)
        except Exception as exception:
            pass           
    
        try:
            command = ['sudo', 'umount', '-l', nfsshare]
            subprocess.call(command, shell=False)
        except Exception as exception:
            pass                

    @autolog.log_method(logger=Logger) 
    def mount_backup_target(self, old_share=False):
        self.umount_backup_target()

        nfsshare = self.backup_endpoint
        mountpath = self.mount_path
        nfsoptions = CONF.vault_storage_nfs_options

        if self.is_online():
           command = ['timeout', '-sKILL', '30' , 'sudo',
                       'mount', '-o', nfsoptions, nfsshare,
                       mountpath]
           subprocess.check_call(command, shell=False) 
           if old_share is True:
              command = ['timeout', '-sKILL', '30' , 'sudo',
                           'mount', '--bind', mountpath,
                           CONF.vault_data_directory_old]
              subprocess.check_call(command, shell=False) 
        else:
             raise exception.BackupTargetOffline(endpoint=nfsshare)

    @autolog.log_method(logger=Logger) 
    def get_total_capacity(self, context):
        """
        return total capacity of the backup target and
        amount of storage that is utilized
        """
        total_capacity = 1
        total_utilization = 1
        try:
            mountpath = self.mount_path
            nfsshare = self.backup_endpoint
            stdout, stderr = utils.execute('df', mountpath)
            if stderr != '':
                msg = _('Could not execute df command successfully. Error %s'), (stderr)
                raise exception.ErrorOccurred(reason=msg)

            # Filesystem     1K-blocks      Used Available Use% Mounted on
            # /dev/sda1      464076568 248065008 192431096  57% /

            fields = stdout.split('\n')[0].split()
            values = stdout.split('\n')[1].split()

            total_capacity = int(values[1]) * 1024
            # Used entry in df command is not reliable indicator. Hence we use
            # size - available as total utilization
            total_utilization = total_capacity - int(values[3]) * 1024

            try:
                stdout, stderr = utils.execute('du', '-shb', mountpath, run_as_root=True)
                if stderr != '':
                    msg = _('Could not execute du command successfully. Error %s'), (stderr)
                    raise exception.ErrorOccurred(reason=msg)
                #196022926557    /var/triliovault
                du_values = stdout.split()                
                total_utilization = int(du_values[0])
            except Exception as ex:
                LOG.exception(ex)

        except Exception as ex:
            LOG.exception(ex)

        return total_capacity,total_utilization

    ##
    # object manipulation methods on the backup target
    ##

    ##
    # for workload transfers
    ##
    def get_all_workload_transfers(self):
        """
        List of workload transfers on this particular backup media
        """
        workload_transfers_directory = self.get_workload_transfers_directory()
        transfers = []
        if workload_transfers_directory:
            pattern = os.path.join(workload_transfers_directory, "*")
            for transfer_file in glob.glob(pattern):
                tran = json.loads(self.get_object(transfer_file))
                transfers.append(tran)

        return transfers

    @autolog.log_method(logger=Logger) 
    def transfers_delete(self, context, transfers_metadata):
        """
        List of workload transfers on this particular backup media
        """
        try:
            transfer_path  = self.get_workload_transfers_path(transfers_metadata)
            if isfile(transfer_path):
                os.remove(transfer_path)
        except Exception as ex:
            LOG.exception(ex)  

    ##
    # triliovault object (json) access methods
    @autolog.log_method(logger=Logger)         
    @to_abs()
    def put_object(self, path, json_data):
        head, tail = os.path.split(path)
        fileutils.ensure_tree(head)
        with open(path, 'w') as json_file:
            json_file.write(json_data)
        return

    @autolog.log_method(logger=Logger)     
    @to_abs()
    def get_object(self, path):
        with open(path, 'r') as json_file:
            return json_file.read()

    @to_abs()
    def object_exists(self, path):
        return os.path.isfile(path)

    @to_abs()
    def get_object_size(self, path):
        size = 0
        try:
            statinfo = os.stat(path)
            size = statinfo.st_size
        except Exception as ex:
            LOG.exception(ex)
        return size            

    @autolog.log_method(logger=Logger)
    def get_workloads(self, context):
        self.download_metadata_from_object_store(context)
        parent_path = self.mount_path
        workload_urls = []
        try:
            for name in os.listdir(parent_path):
                if os.path.isdir(os.path.join(parent_path, name)) and name.startswith('workload_'):
                    workload_urls.append(os.path.join(parent_path, name))
        except Exception as ex:
            LOG.exception(ex)
        return workload_urls  

    @autolog.log_method(logger=Logger) 
    def workload_delete(self, context, workload_metadata):
        try:
            workload_path = self.get_workload_path(workload_metadata)
            if os.path.isdir(workload_path):
                shutil.rmtree(workload_path)
        except Exception as ex:
            LOG.exception(ex)  

    @autolog.log_method(logger=Logger)         
    def snapshot_delete(self, context, snapshot_metadata):
        try:
            snapshot_path = self.get_snapshot_path(snapshot_metadata)
            if os.path.isdir(snapshot_path):
                shutil.rmtree(snapshot_path)
        except Exception as ex:
            LOG.exception(ex)

    @autolog.log_method(logger=Logger)
    def config_backup_delete(self, context, backup_metadata):
        try:
            backup_path = self.get_config_backup_path(backup_metadata)
            if os.path.isdir(backup_path):
                shutil.rmtree(backup_path)
        except Exception as ex:
            LOG.exception(ex)

    ##
    # Object specific operations
    @autolog.log_method(logger=Logger) 
    def _update_workload_ownership_on_media(self, context, workload_id):
        try:
            workload_path  = self.get_workload_path({'workload_id': workload_id})
            def _update_metadata_file(pathname): 
                metadata = json.loads(self.get_object(pathname))

                metadata['user_id'] = context.user_id
                metadata['project_id'] = context.project_id

                self.put_object(pathname, json.dumps(metadata))

            for snap in glob.glob(os.path.join(workload_path, "snapshot_*")):
                _update_metadata_file(os.path.join(snap, "snapshot_db"))

            _update_metadata_file(os.path.join(workload_path, "workload_db"))

        except Exception as ex:
            LOG.exception(ex)
            raise


class SwiftTrilioVaultBackupTarget(NfsTrilioVaultBackupTarget):
    def __init__(self, backupendpoint):
        super(SwiftTrilioVaultBackupTarget, self).__init__(backupendpoint)

    @autolog.log_method(logger=Logger)
    def get_progress_tracker_directory(self, tracker_metadata):
        """
        Get the location where all tracking objects are stored. The tracking
        object is a file on NFS. It can be object in object store
        """
        mountpath = self.mount_path
        progress_tracker_directory = os.path.join(mountpath,
            "contego_tasks", 'snapshot_%s' % (tracker_metadata['snapshot_id']))

        fileutils.ensure_tree(progress_tracker_directory)
        return progress_tracker_directory

    @autolog.log_method(logger=Logger)
    def mount_backup_target(self, old_share=False): 
        try:
            command = ['sudo', 'service', 'tvault-swift', 'start']
            subprocess.check_call(command, shell=False)
        except Exception as ex:
               pass

    @autolog.log_method(logger=Logger)
    def is_online(self):
        status = False
        stdout, stderr = utils.execute('sudo', 'service', 'tvault-swift', 'status', run_as_root=False)
        if 'running' in stdout:
            stdout, stderr = utils.execute('stat', '-f', self.mount_path)
            if stderr != '':
                msg = _('Could not execute stat command successfully. Error %s'), (stderr)
                raise exception.ErrorOccurred(reason=msg)
            file_type = stdout.split('\n')[1].split('Type: ')[1] 
            if file_type == 'fuseblk':
               status = True
        return status

    @autolog.log_method(logger=Logger)
    def umount_backup_target(self):
        try:
            command = ['sudo', 'service', 'tvault-swift', 'stop']
            subprocess.check_call(command, shell=False)
        except Exception as ex:
               pass

    @autolog.log_method(logger=Logger)
    @to_abs()
    def put_object(self, path, json_data):
        head, tail = os.path.split(path)
        fileutils.ensure_tree(head)
        try:
            with open(path, 'w') as json_file:
                 json_file.write(json_data)
        except:
               with open(path, 'w') as json_file:
                    json_file.write(json_data)
        return

    @autolog.log_method(logger=Logger)
    def snapshot_delete(self, context, snapshot_metadata):
        try:
            snapshot_path = self.get_snapshot_path(snapshot_metadata)
            retry = 0
            while os.path.isdir(snapshot_path):
               try:
                   command = ['rm', '-rf', snapshot_path]
                   subprocess.check_call(command, shell=False)
               except:
                       pass
               retry += 1
               if retry >= 1:
                  break
        except Exception as ex:
            LOG.exception(ex)

    @autolog.log_method(logger=Logger)
    def snapshot_delete(self, context, snapshot_metadata):
        try:
            snapshot_path = self.get_openstack_config_snapshot_path(snapshot_metadata)
            retry = 0
            while os.path.isdir(snapshot_path):
                try:
                    command = ['rm', '-rf', snapshot_path]
                    subprocess.check_call(command, shell=False)
                except:
                    pass
                retry += 1
                if retry >= 1:
                    break
        except Exception as ex:
            LOG.exception(ex)
    @autolog.log_method(logger=Logger)
    def get_total_capacity(self, context):
        """
        return total capacity of the backup target and
        amount of storage that is utilized
        """
        total_capacity = 1
        total_utilization = 1
        try:
            mountpath = self.mount_path
            stdout, stderr = utils.execute('stat', '-f', mountpath)
            if stderr != '':
                msg = _('Could not execute stat command successfully. Error %s'), (stderr)
                raise exception.ErrorOccurred(reason=msg)
            total_capacity = int(stdout.split('\n')[3].split('Blocks:')[1].split(' ')[2])
            try:
                 total_free = int(stdout.split('\n')[3].split('Blocks:')[1].split(' ')[4])
            except:
                   total_free = int(stdout.split('\n')[3].split('Blocks:')[1].split('Available: ')[1])
            total_utilization = abs(total_capacity - total_free)

        except Exception as ex:
            LOG.exception(ex)

        return total_capacity,total_utilization

triliovault_backup_targets = {}
@autolog.log_method(logger=Logger) 
def mount_backup_media():
    for idx, backup_target in enumerate(CONF.vault_storage_nfs_export.split(',')):
        backup_target = backup_target.strip()
        if backup_target == '':
            continue
        if CONF.vault_storage_type == 'nfs': 
            backend = NfsTrilioVaultBackupTarget(backup_target)
        elif CONF.vault_storage_type == 'swift-s':
            backend = SwiftTrilioVaultBackupTarget(backup_target)

        triliovault_backup_targets[backup_target] = backend
        backend.mount_backup_target()


def get_backup_target(backup_endpoint):
    backup_endpoint = backup_endpoint.strip()
    backup_target = triliovault_backup_targets.get(backup_endpoint, None)
    
    if backup_target is None:
        mount_backup_media()
        backup_target = triliovault_backup_targets.get(backup_endpoint, None)

    return backup_target


def get_settings_backup_target():
    settings_path_new = os.path.join(CONF.cloud_unique_id,"settings_db")
    for backup_endpoint in CONF.vault_storage_nfs_export.split(','):
        get_backup_target(backup_endpoint.strip())
    for endpoint, backup_target in triliovault_backup_targets.iteritems():
        if backup_target.object_exists(settings_path_new):
            return (backup_target, settings_path_new)

    triliovault_backup_targets.values()[0].put_object(settings_path_new,
                                                      json.dumps([]))
    settings_path = "settings_db"
    for endpoint, backup_target in triliovault_backup_targets.iteritems():
        if backup_target.object_exists(settings_path):
            return (backup_target, settings_path)

    return (triliovault_backup_targets.values()[0], settings_path_new)

def get_capacities_utilizations(context):
    def fill_capacity_utilization(context, backup_target, stats):
        nfsshare = backup_target.backup_endpoint
        cap, util = backup_target.get_total_capacity(context)
           
        stats[nfsshare] = {'total_capacity': cap,
                           'total_utilization': util,
                           'nfsstatus': True }

    stats = {}
    threads = []
    for nfsshare in CONF.vault_storage_nfs_export.split(','):
        nfsshare = nfsshare.strip()
        backup_target = get_backup_target(nfsshare)
        nfsstatus = backup_target.is_online()

        stats[nfsshare] = {'total_capacity': -1,
                           'total_utilization': -1,
                           'nfsstatus': nfsstatus }
        if nfsstatus is True:
            t = threading.Thread(target=fill_capacity_utilization,
                                 args=[context, backup_target, stats])
            t.start()
            threads.append(t)

    for t in threads:
        t.join()

    return stats


def get_workloads(context):
    workloads = []

    for backup_endpoint in CONF.vault_storage_nfs_export.split(','):
        get_backup_target(backup_endpoint)

    for endpoint, backup_target in triliovault_backup_targets.iteritems():
        workloads += backup_target.get_workloads(context)

    return workloads

def validate_workload(workload_url):
    if os.path.isdir(workload_url) and os.path.exists(os.path.join(workload_url, "workload_db")):
        return True
    else:
        return False


def get_all_workload_transfers(context):
    transfers = []

    for backup_endpoint in CONF.vault_storage_nfs_export.split(','):
        get_backup_target(backup_endpoint)

    for endpoint, backup_target in triliovault_backup_targets.iteritems():
        transfers += backup_target.get_all_workload_transfers()

    return transfers

def get_nfs_share_for_workload_by_free_overcommit(context, workload):
    """
       workload is a dict with id, name, description and metadata.
       metadata includes size of the workload and approximate backup storage needed
       to hold all backups
    """

    shares = {}
    caps = get_capacities_utilizations(context)
    for endpoint, backend in triliovault_backup_targets.iteritems():
        if caps[endpoint]['nfsstatus'] is False:
            continue
        shares[endpoint] = {
                     'noofworkloads': 0,
                     'totalcommitted': 0,
                     'endpoint': endpoint,
                     'capacity': caps[endpoint]['total_capacity'],
                     'used': caps[endpoint]['total_utilization']
                    }
    if len(shares) == 0:
        raise exception.InvalidState(reason="No NFS shares mounted")

    # if only one nfs share is configured, then return that share
    if len(shares) == 1:
        return shares.keys()[0]

    for endpoint, values in shares.iteritems():
        base64encode = base64.b64encode(endpoint)
        mountpath = os.path.join(CONF.vault_data_directory, base64encode)
        for w in os.listdir(mountpath):
            try:
                if not 'workload_' in w:
                    continue
                workload_path = os.path.join(mountpath, w)
                with open(os.path.join(workload_path, "workload_db"), "r") as f:
                    wjson = json.load(f)
                values['noofworkloads'] += 1
                workload_approx_backup_size = 0

                for meta in wjson['metadata']:
                    if meta['key'] == 'workload_approx_backup_size':
                        workload_approx_backup_size = int(meta['value'])

                if workload_approx_backup_size == 0:
                    workload_backup_media_size = 0
                    for result in glob.iglob(os.path.join(workload_path, 'snapshot_*/snapshot_db')): 
                         with open(result, "r") as snaprecf:
                             snaprec = json.load(snaprecf)
                         if snaprec['snapshot_type'] == "full":
                             workload_backup_media_size = snaprec['size'] / 1024 / 1024 / 1024
      
                    # workload_backup_media_size is in GBs
                    workload_backup_media_size = workload_backup_media_size or 10
                    jobschedule = pickle.loads(str(wjson['jobschedule']))
                    if jobschedule['retention_policy_type'] == 'Number of Snapshots to Keep':
                        incrs = int(jobschedule['retention_policy_value'])
                    else:
                        jobsperday = int(jobschedule['interval'].split("hr")[0])
                        incrs = int(jobschedule['retention_policy_value']) * jobsperday

                    if jobschedule['fullbackup_interval'] == '-1':
                        fulls = 1
                    else:
                        fulls = incrs/int(jobschedule['fullbackup_interval'])
                        incrs = incrs - fulls

                    workload_approx_backup_size = \
                            (fulls * workload_backup_media_size * CONF.workload_full_backup_factor +
                             incrs * workload_backup_media_size * CONF.workload_incr_backup_factor) / 100
                    values['totalcommitted'] += workload_approx_backup_size * 1024 * 1024 * 1024
                else:
                    values['totalcommitted'] += workload_approx_backup_size * 1024 * 1024 * 1024
            except Exception as ex:
                LOG.exception(ex) 

    def getKey(item):
        item['free'] = item['capacity'] - item['totalcommitted']
        return min(item['capacity'] - item['totalcommitted'],
                   item['capacity'] - item['used'])

    sortedlist = sorted(shares.values(), reverse=True, key=getKey)

    return sortedlist[0]['endpoint']

def get_workloads_for_tenant(context, tenant_ids):
    workload_ids = []
    for backup_endpoint in CONF.vault_storage_nfs_export.split(','):
        backup_target = None
        try:
            backup_target = get_backup_target(backup_endpoint)
            for workload_url in backup_target.get_workloads(context):
                workload_values = json.loads(backup_target.get_object(\
                        os.path.join(workload_url, 'workload_db')))
                project_id = workload_values.get('project_id')
                workload_id = workload_values.get('id')
                if project_id in tenant_ids:
                    workload_ids.append(workload_id)
        except Exception as ex:
            LOG.exception(ex)
    return  workload_ids

def update_workload_db(context, workloads_to_update, new_tenant_id, user_id):

    workload_urls = []
    jobscheduler_map = {}

    try:
        #Get list of workload directory path for workloads need to update
        for workload_id in workloads_to_update:
            for backup_endpoint in CONF.vault_storage_nfs_export.split(','):
                backup_target = None
                backup_target = get_backup_target(backup_endpoint)
                workload_url = os.path.join(backup_target.mount_path, "workload_" + workload_id)
                if os.path.isdir(workload_url):
                    workload_urls.append(workload_url)
                    break;

        #Iterate through each workload directory and update workload_db and snapsot_db with new values
        for workload_path in workload_urls:
            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())

                        if db_values.get('project_id', None) is not None:
                            db_values['project_id'] = new_tenant_id
                        else:
                            db_values['tenant_id'] = new_tenant_id
                        db_values['user_id'] = user_id

                        if db_values.get('jobschedule', None) is not None:
                            jobschedule = pickle.loads(db_values['jobschedule'])
                            if jobschedule['enabled'] is True:
                               jobschedule['enabled'] = False
                               db_values['jobschedule'] = pickle.dumps(jobschedule)
                            jobscheduler_map[db_values['id']] = db_values['jobschedule']

                        with open(os.path.join(path, name), 'w') as file:
                            json.dump(db_values, file)

        return jobscheduler_map

    except Exception as ex:
        LOG.exception(ex)

"""
if __name__ == '__main__':
    nfsbackend = 
 
    nfsbackend.umount_backup_target()
    nfsbackend.mount_backup_target()
    workload_path = nfsbackend.get_workload_path({'workload_id': str(uuid.uuid4())})
    print workload_path
    import pdb;pdb.set_trace()
    print nfsbackend.get_total_capacity(None)
    nfsbackend.umount_backup_target()
    workload_path = nfsbackend.get_workload_path({'workload_id': str(uuid.uuid4())})
    print workload_path
"""
