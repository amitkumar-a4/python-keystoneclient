#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

from __future__ import with_statement

import os
import sys
import errno
import argparse

from bunch import bunchify
import vaultswift
import shutil

from fuse import FUSE, FuseOSError, Operations
from pwd import getpwnam
import functools
import subprocess

try:
    from oslo_config import cfg
except ImportError:
    from oslo.config import cfg

try:
    from oslo_log import log as logging
except ImportError:
    from nova.openstack.common import log as logging

_DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
FUSE_USER = "nova"

common_cli_opts = [
    cfg.BoolOpt('debug',
                short='d',
                default=False,
                help='Print debugging output (set logging level to '
                     'DEBUG instead of default WARNING level).'),
    cfg.BoolOpt('verbose',
                short='v',
                default=False,
                help='Print more verbose output (set logging level to '
                     'INFO instead of default WARNING level).'),
]

logging_cli_opts = [
    cfg.StrOpt('log-config',
               metavar='PATH',
               help='If this option is specified, the logging configuration '
                    'file specified is used and overrides any other logging '
                    'options specified. Please see the Python logging module '
                    'documentation for details on logging configuration '
                    'files.'),
    cfg.StrOpt('log-config-append',
               metavar='PATH',
               help='(Optional) Log Append'),
     cfg.StrOpt('watch-log-file',
               metavar='PATH',
               help='(Optional) Watch log'),
    cfg.StrOpt('log-format',
               default=None,
               metavar='FORMAT',
               help='A logging.Formatter log message format string which may '
                    'use any of the available logging.LogRecord attributes. '
                    'This option is deprecated.  Please use '
                    'logging_context_format_string and '
                    'logging_default_format_string instead.'),
    cfg.StrOpt('log-date-format',
               default=_DEFAULT_LOG_DATE_FORMAT,
               metavar='DATE_FORMAT',
               help='Format string for %%(asctime)s in log records. '
                    'Default: %(default)s'),
    cfg.StrOpt('log-file',
               metavar='PATH',
               deprecated_name='logfile',
               help='(Optional) Name of log file to output to. '
                    'If no default is set, logging will go to stdout.'),
    cfg.StrOpt('log-dir',
               deprecated_name='logdir',
               help='(Optional) The base directory used for relative '
                    '--log-file paths'),
    cfg.BoolOpt('use-syslog',
                default=False,
                help='Use syslog for logging.'),
    cfg.StrOpt('syslog-log-facility',
               default='LOG_USER',
               help='syslog facility to receive log lines')
]

generic_log_opts = [
    cfg.BoolOpt('use_stderr',
                default=True,
                help='Log output to standard error')
]

log_opts = [
    cfg.StrOpt('logging_context_format_string',
               default='%(asctime)s.%(msecs)03d %(process)d %(levelname)s '
                       '%(name)s [%(request_id)s %(user)s %(tenant)s] '
                       '%(instance)s%(message)s',
               help='format string to use for log messages with context'),
    cfg.StrOpt('logging_default_format_string',
               default='%(asctime)s.%(msecs)03d %(process)d %(levelname)s '
                       '%(name)s [-] %(instance)s%(message)s',
               help='format string to use for log messages without context'),
    cfg.StrOpt('logging_debug_format_suffix',
               default='%(funcName)s %(pathname)s:%(lineno)d',
               help='data to append to log format when level is DEBUG'),
    cfg.StrOpt('logging_exception_prefix',
               default='%(asctime)s.%(msecs)03d %(process)d TRACE %(name)s '
               '%(instance)s',
               help='prefix each line of exception output with this format'),
    cfg.ListOpt('default_log_levels',
                default=[
                    'amqplib=WARN',
                    'sqlalchemy=WARN',
                    'boto=WARN',
                    'suds=INFO',
                    'keystone=INFO',
                    'eventlet.wsgi.server=WARN'
                ],
                help='list of logger=LEVEL pairs'),
    cfg.BoolOpt('publish_errors',
                default=False,
                help='publish error events'),
    cfg.BoolOpt('fatal_deprecations',
                default=False,
                help='make deprecations fatal'),
    cfg.StrOpt('instance_format',
               default='[instance: %(uuid)s] ',
               help='If an instance is passed with the log message, format '
                    'it like this'),
    cfg.StrOpt('instance_uuid_format',
               default='[instance: %(uuid)s] ',
               help='If an instance UUID is passed with the log message, '
                    'format it like this'),
]

contego_vault_opts = [
    cfg.StrOpt('vault_storage_type',
               default='nfs',
               help='Storage type: nfs, swift-i, swift-s'),
    cfg.StrOpt('vault_data_directory',
               help='Location where snapshots will be stored'),
    cfg.StrOpt('vault_data_directory_old',
               default='/var/triliovault',
               help='Location where snapshots will be stored'),
    cfg.StrOpt('vault_storage_nfs_export',
               default='local',
               help='NFS Export'),
    cfg.StrOpt('vault_storage_nfs_options',
               default='nolock',
               help='NFS Options'),
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
    cfg.StrOpt('vault_swift_domain_id',
               default='default',
               help='Swift domain id'),
    cfg.StrOpt('vault_swift_container_prefix',
               default='TrilioVault',
               help='Swift Container Prefix'),
    cfg.StrOpt('vault_swift_segment_size',
               default='33554432', 
               help='Default segment size 34MB'),
    cfg.IntOpt('vault_retry_count',
               default=2,
               help='The number of times we retry on failures'),
    cfg.StrOpt('vault_swift_url_template',
               default='http://localhost:8080/v1/AUTH_%(project_id)s',
               help='The URL of the Swift endpoint'),
]

CONF = cfg.CONF
CONF.register_opts(contego_vault_opts)
CONF.register_cli_opts(logging_cli_opts)
CONF.register_cli_opts(generic_log_opts)
CONF.register_cli_opts(log_opts)
CONF.register_cli_opts(common_cli_opts)
CONF(sys.argv[1:], project='swift')
LOG = logging.getLogger(__name__)
logging.setup(cfg.CONF, 'swift')
try:
    LOG.logger.setLevel(logging.ERROR)
except:
       LOG.logger.setLevel(logging.logging.ERROR)

options = {'sync_to': None,'verbose': 1,'header': [],'auth_version': u'1.0',
           'os_options': {u'project_name': None,
                          u'region_name': 'RegionOne',
                          u'user_domain_name': None,
                          u'endpoint_type': None,
                          u'object_storage_url': None,
                          u'project_domain_id': None,
                          u'user_id': None,
                          u'user_domain_id': None,
                          u'tenant_id': None,
                          u'service_type': None,
                          u'project_id': None,
                          u'auth_token': None,
                          u'project_domain_name': None
                         },
           'ssl_compression': True,
           'os_storage_url': None,
           'os_username': '',
           'os_password': '',
           'os_cacert': None,
           'os_tenant_name': 'demo',
           'os_auth_url': '',
           'os_auth_token': None,
           'insecure': False,
           'snet': False,'sync_key': None,'auth': '','user': '','key': '',
           'read_acl': None,'info': False,'retries': 5,'write_acl': None,'meta': [],
           'debug': False,'use_slo': False,'checksum': True, 'changed': False, 
           'leave_segments': False,'skip_identical': True,'segment_threads': 10,
           'object_dd_threads': 10,'object_uu_threads': 10,'container_threads': 10,
           'yes_all': False,'object_name': None,
          }

if CONF.vault_swift_auth_version == 'TEMPAUTH':
   options['auth_version'] = '1.0'
   options['auth'] = CONF.vault_swift_auth_url
   options['user'] = CONF.vault_swift_username
   options['key'] = CONF.vault_swift_password
else:
    options['auth_version'] = '2.0'
    if 'v3' in CONF.vault_swift_auth_url:
       options['auth_version'] = '3'
       options['os_options']['user_domain_id'] = CONF.vault_swift_domain_id
       options['os_options']['domain_id'] = CONF.vault_swift_domain_id
       options['os_options']['project_name'] = CONF.vault_swift_tenant
    options['os_auth_url'] = CONF.vault_swift_auth_url
    options['os_username'] = CONF.vault_swift_username
    options['os_password'] = CONF.vault_swift_password
    options['os_domain_id'] = CONF.vault_swift_domain_id
    options['os_user_domain_id'] = CONF.vault_swift_domain_id
    options['os_tenant_name'] = CONF.vault_swift_tenant
     

def disable_logging(func):
    @functools.wraps(func)
    def wrapper(*args,**kwargs):
        try:
            logging.logging.disable(logging.ERROR)
        except:
               logging.logging.disable(logging.logging.ERROR)
        result = func(*args,**kwargs)
        try:
            logging.logging.disable(logging.NOTSET)
        except:
               logging.logging.disable(logging.logging.NOTSET)
        return result
    return wrapper


def split_head_tail(path):
    head, tail = os.path.split(path)
    prefix = ''
    while head not in ('', '/'):
        if prefix != '':
           prefix = os.path.join(tail, prefix)
        else:
             prefix = tail
        head, tail = os.path.split(head)

    return tail, prefix

def get_head(path):
    head, tail = os.path.split(path)
    return head


class TrilioVault(Operations):
    def __init__(self, root, path='.'):
        self.root = root
        self.user_id = getpwnam(FUSE_USER).pw_uid
        self.group_id = getpwnam(FUSE_USER).pw_gid

    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path

    def _get_cache(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        if not os.path.isdir(CONF.vault_data_directory_old):
           try:
               command = ['sudo', 'mkdir', CONF.vault_data_directory_old]
               subprocess.call(command, shell=False)
               command = ['sudo', 'chown', str(self.user_id)+':'+str(self.group_id), CONF.vault_data_directory_old]
               subprocess.call(command, shell=False)
           except:
                  pass
        else:
             stat_info = os.stat(CONF.vault_data_directory_old)
             if stat_info.st_uid != self.user_id or stat_info.st_gid != self.group_id:
                command = ['sudo', 'chown', str(self.user_id)+':'+str(self.group_id), CONF.vault_data_directory_old]
                subprocess.call(command, shell=False)

        path = os.path.join(CONF.vault_data_directory_old, partial)
        return path

    def destroy(self, path):
        print "destroy, "
        shutil.rmtree(CONF.vault_data_directory_old)
        return 0

    def chmod(self, path, mode):
        print "chmod, ", path
        container, prefix = split_head_tail(path)
        cache_path = self._get_cache(prefix)
        return 0
        return os.chmod(cache_path, mode)

    def chown(self, path, uid, gid):
        print "chown, ",path
        container, prefix = split_head_tail(path)
        cache_path = self._get_cache(prefix)
        return os.chown(cache_path, uid, gid)

    @disable_logging
    def getattr(self, path, fh=None):
        print "getattr, ", path
        full_path = self._full_path(path)
        container, prefix = split_head_tail(path)
        _opts = options.copy()

        if container == '':
            args = []
        else:
            args = [container]

        _opts['delimiter'] =  None
        _opts['human'] = False
        _opts['totals'] = False
        _opts['long'] = False
        _opts['prefix'] = None

        _opts = bunchify(_opts)
        d = {}
        if prefix != '':
           _opts['prefix'] = prefix
           args.append(prefix)
        else:
             prefix = None
        try:
            st = vaultswift.st_stat(args, _opts)
            d['st_gid'] = self.group_id
            d['st_uid'] = self.user_id
            d['st_atime'] = int(st['headers']['x-timestamp'].split('.')[1])
            d['st_ctime'] = int(st['headers']['x-timestamp'].split('.')[0])
            d['st_mtime'] = int(st['headers']['x-timestamp'].split('.')[0])
            d['st_nlink'] = 1
            d['st_mode'] = 33261
            d['st_size'] = int(st['headers']['content-length'])
            if (d['st_size'] == 0 and container == '') or (d['st_size'] == 0 and prefix is None) or \
                (d['st_size'] == 0 and prefix == ''):
               d['st_nlink'] = 3
               d['st_size'] = 4096
               d['st_mode'] = 16893
        except Exception as ex:
            if prefix is None:
               prefix = container
            full_path1 = self._get_cache(os.path.join(container, prefix))
            full_path = self._get_cache(prefix)
            mkdirs = get_head(prefix)
            try:
                 st = os.lstat(full_path)
                 #full_path = full_path1
            except:
                   args1 = args
                   if len(args1) > 1:
                      args1.pop()
                   try:
                       _opts['prefix'] = os.path.join(_opts['prefix'], '')
                       st = vaultswift.st_list(args1, _opts)
                       if len(st) > 0:
                          #full_path = full_path1
                          self.mkdir(prefix, 0751, True)
                   except:
                          pass
            if prefix == '4913' or prefix[:-1].endswith('~'):
                return 
            st = os.lstat(full_path)
            d = dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                     'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid',))

        # st_blksize and st_blocks are import for qemu-img info command to
        # display disk size attribute correctly. Without this information
        # it displays disk size 0
        d['st_blksize'] = 512
        d['st_blocks'] = d['st_size'] / 512
        print d
        return d

    def readdir(self, path, fh):
        listing = []
        print "readdir, ", path
        container, prefix = split_head_tail(path)
        _opts = options.copy()
        _opts['delimiter'] =  None
        _opts['human'] = False
        _opts['totals'] = False
        _opts['long'] = False
        _opts['prefix'] = None
        args = []
        if container == '':
            args = []
        else:
            args = [container]
            #_opts['delimiter'] =  '/'
            if prefix != '' and prefix is not None:
               _opts['prefix'] = prefix+'/'

        _opts = bunchify(_opts)
        listing += vaultswift.st_list(args, _opts)
        dirents = ['.','..']
        for lst in listing:
            if prefix and prefix not in lst:
               continue
            if prefix:
                component, rest = split_head_tail(lst.split(prefix, 1)[1])
            else:
                component, rest = split_head_tail(lst)
            if rest != '' and rest != '':
               mkdirs = get_head(lst)
               self.mkdir(mkdirs, 0751, True)
            if component is not None and component != '' and \
                not component.endswith('_segments'):
               if component not in dirents:
                  dirents.append(component) 
        for r in list(dirents):
            yield r

    '''def readlink(self, path):
        print "readlink, ", path
        pathname = os.readlink(self._full_path(path))
        if pathname.startswith("/"):
            return os.path.relpath(pathname, self.root)
        else:
            return pathname

    def mknod(self, path, mode, dev):
        print "mknod, ", path
        return os.mknod(self._full_path(path), mode, dev)'''

    def rmdir(self, path):
        print "rmdir, ", path
        container, obj = split_head_tail(path)
        _opts = options.copy()
        _opts = bunchify(_opts)
        args1 = [container]
        if obj != '' and obj != '/':
           args1.append(obj)
        try:
            vaultswift.st_delete(args1, _opts)
        except Exception as ex:
            LOG.exception(ex)
            pass

        try:
            args1[0] = args1[0]+"_segments"
            vaultswift.st_delete(args1, _opts)
        except Exception as ex:
            LOG.exception(ex)
            pass

        cache_path = self._get_cache(path)
        return os.rmdir(cache_path)

    def mkdir(self, path, mode, ist=False):
        print "mkdir, ", path
        container, obj = split_head_tail(path)
        if (obj == '' or obj == '/') and ist is False:
           _opts = options.copy()
           _opts = bunchify(_opts)
           args1 = [container]
           try:
               vaultswift.st_post(args1, _opts)
               os.mkdir(container, mode)
           except Exception as ex:
               LOG.exception(ex)
               return 0
           return 0
        cache_path = self._get_cache(path)
        if ist is False:
           cache_path = self._get_cache(obj)
        try:
            os.makedirs(cache_path, mode)
        except Exception as ex:
               pass
        return 0

    def statfs(self, path):
        print "statfs, ", path
        _opts = options.copy()
        _opts = bunchify(_opts)
        args1 = []
        stv = vaultswift.st_stat(args1, _opts)
        if 'x-account-meta-quota-bytes' in stv['headers']:
           f_blocks = int(stv['headers']['x-account-meta-quota-bytes'])
           f_bavail = int(stv['headers']['x-account-meta-quota-bytes']) - int(stv['headers']['x-account-bytes-used'])
        else:
             f_blocks = -1
             f_bavail = int(stv['headers']['x-account-bytes-used'])
        dt = {}
        dt['f_blocks'] = f_blocks
        dt['f_bfree'] = f_bavail
        dt['f_bavail'] = f_bavail
        dt['f_favail'] = 0
        dt['f_frsize'] = 0
        return dt

    def unlink(self, path):
        print "unlink, ", path
        container, obj = split_head_tail(path)
        cache_path = self._get_cache(obj)
        _opts = options.copy()
        _opts = bunchify(_opts)
        args1 = [container]
        if obj != '' and obj != '/':
           args1.append(obj)
        try:
            vaultswift.st_delete(args1, _opts)
        except Exception as ex:
               LOG.exception("called")
               pass

        """"try:
            vaultswift.st_delete([container, obj.strip('/') + "_segments"], _opts)
        except:
            pass"""
        
        try:
            return os.unlink(self._cache_path(path))
        except:
            pass

    def symlink(self, name, target):
        print "symlink, ", target
        container, prefix = split_head_tail(target)
        cache_path_target = self._get_cache(prefix)
        return os.symlink(name, cache_path_target)

    def rename(self, old, new):
        print "rename, %s -> %s" % (old, new)
        container, prefix = split_head_tail(old)
        cache_path_old = self._get_cache(prefix)
        container, prefix = split_head_tail(new)
        cache_path_new = self._get_cache(prefix)
        fh = self.open(old, os.O_RDONLY)
        os.rename(cache_path_old, cache_path_new)
        self.unlink(old)
        self.release(new, fh)
        return 0

    def link(self, target, name):
        print "link, ", target
        container, prefix = split_head_tail(target)
        cache_path_target = self._get_cache(prefix)
        container, prefix = split_head_tail(name)
        cache_path_name = self._get_cache(prefix)
        return os.link(cache_path_target, cache_path_name)

    def utimens(self, path, times=None):
        print "utimens, ", path
        container, prefix = split_head_tail(path)
        cache_path = self._get_cache(prefix)
        return os.utime(cache_path, times)

    def create(self, path, mode, fi=None):
        container, prefix = split_head_tail(path)
        full_path = self._get_cache(prefix)
        print "create, ", path
        return os.open(full_path, os.O_WRONLY | os.O_CREAT, mode)

    def open(self, path, flags):
        print "open, ", path
        container, prefix = split_head_tail(path)
        full_path = self._get_cache(prefix)
        try:
            fh = os.open(full_path, flags)
        except Exception as ex:
               _opts = options.copy()
               _opts['prefix'] = None
               _opts['out_directory'] = None
               container, obj = split_head_tail(path)
               cache_path = self._get_cache(prefix)
               try:
                   os.stat(cache_path)
               except:
                   _opts['out_file'] = cache_path
                   _opts = bunchify(_opts)
                   args1 = [container, obj.strip('/')]
                   try:
                       vaultswift.st_download(args1, _opts)
                   except Exception as ex:
                       LOG.exception(ex)
                   self.chmod(full_path, 0751)
                   fh = os.open(full_path, flags)
        return fh

    def read(self, path, length, offset, fh):
        print "read, ", path

        _opts = options.copy()
        _opts['prefix'] = None
        _opts['out_directory'] = None

        container, obj = split_head_tail(path)
        cache_path = self._get_cache(obj)
        try:
            os.stat(cache_path)
        except Exception as ex:
            _opts['out_file'] = cache_path
            _opts = bunchify(_opts)
            args = [container, obj.strip('/')]
            try:
                vaultswift.st_download(args, _opts)
            except Exception as ex:
                LOG.exception(ex)

        buf = ''
        # We need to seek to the right offset before read
        # otherwise random access to file does not work.
        # very import for qemu-img convert command. otherwise
        # restores don't work
        os.lseek(fh, offset, os.SEEK_SET)
        buf = os.read(fh, length)
        return buf

    def write(self, path, buf, offset, fh):
        os.lseek(fh, offset, os.SEEK_SET)
        print "write, %s " % path
        return os.write(fh, buf)

    def truncate(self, path, length, fh=None):
        print "truncate, %s, %d" % (path, length)
        container, obj = split_head_tail(path)
        cache_path = self._get_cache(obj)
        with open(cache_path, 'r+') as f:
            f.truncate(length)

    def flush(self, path, fh):
        print "flush, %s" % (path)
        return 0

    def release(self, path, fh):
        print "release, %s" % (path)
        container, obj = split_head_tail(path)
        full_path = self._get_cache(obj)
        _opts = options.copy()
        _opts['segment_size'] = CONF.vault_swift_segment_size
        _opts['object_name'] = obj.rstrip('/')
        _opts = bunchify(_opts)
        args1 = [container, full_path.rstrip('/')]
        try:
            vaultswift.st_upload(args1, _opts)
        except Exception as ex:
            LOG.exception(ex)
            return 0

        os.remove(full_path)

        return 0

    def fsync(self, path, fdatasync, fh):
        print "fsync, %s" % (path)
        return 0

def main(mountpoint):
    try:
        try:
            command = ['sudo', 'umount', '-l', mountpoint]
            subprocess.call(command, shell=False)
        except:
               pass
        if os.path.isdir(mountpoint):
           command = ['sudo', 'rm', '-rf', os.path.join(mountpoint,'*')]
           subprocess.call(command, shell=False) 
        else:
             command = ['sudo', 'mkdir', mountpoint]
             subprocess.call(command, shell=False)
             command = ['sudo', 'chown', FUSE_USER+':'+FUSE_USER, mountpoint]
             subprocess.call(command, shell=False)
    except Exception as ex:
           pass
    FUSE(TrilioVault(mountpoint), mountpoint, nothreads=True, foreground=True, nonempty=True)

if __name__ == '__main__':
    main(CONF.vault_data_directory)
