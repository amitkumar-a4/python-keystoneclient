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
from cachetools import LRUCache
import json
import vaultswift
import shutil
import functools
import subprocess
from tempfile import mkstemp

from contego import utils
from swiftclient.service import (
   get_conn
)

from swiftclient.utils import (
    config_true_value, ReadableToIterable, LengthWrapper, EMPTY_ETAG,
)

from fuse import FUSE, FuseOSError, Operations
from pwd import getpwnam

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
                help='Log output to standard error'),
    cfg.IntOpt('rate_limit_burst',
                default=1,
                help='Burst limit')
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
    cfg.StrOpt('tmpfs_mount_path',
               default='tmpfs',
               help='Location with respect to CONF.vault_data_directory_old'
                    'where tmpfs is mounted'),
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
    cfg.StrOpt('region_name_for_services',
                default='RegionOne',
                help='Swift Region Name'),
    cfg.StrOpt('vault_swift_domain_id',
               default='default',
               help='Swift domain id'),
    cfg.StrOpt('vault_swift_domain_name',
               default='Default',
               help='Swift domain name'),
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
    cfg.IntOpt('vault_segment_size',
               default=32 * 1024 * 1024,
               help='vault swift object segmentation size'),
    cfg.IntOpt('vault_cache_size',
               default=5,
               help='Number of segments of an object that need to be cached'),
    cfg.StrOpt('rootwrap_conf',
               default='/etc/nova/rootwrap.conf',
               metavar='PATH',
               help='rootwrap config file'),
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
                          u'region_name': None,
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
           'os_cacert': os.environ.get('OS_CACERT'),
           'os_cert': os.environ.get('OS_CERT'),
           'os_key': os.environ.get('OS_KEY'),
           #'insecure': config_true_value(os.environ.get('SWIFTCLIENT_INSECURE')),
           'os_tenant_name': '',
           'os_auth_url': '',
           'os_auth_token': None,
           'insecure': True,
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
       if CONF.vault_swift_domain_id != "":
          options['os_options']['user_domain_id'] = CONF.vault_swift_domain_id
          options['os_options']['domain_id'] = CONF.vault_swift_domain_id
       elif CONF.vault_swift_domain_name != "":
            options['os_options']['user_domain_name'] = CONF.vault_swift_domain_name
            options['os_options']['domain_name'] = CONF.vault_swift_domain_name

    options['os_options']['project_name'] = CONF.vault_swift_tenant
    options['os_auth_url'] = CONF.vault_swift_auth_url
    options['os_username'] = CONF.vault_swift_username
    options['os_password'] = CONF.vault_swift_password
    options['os_domain_id'] = CONF.vault_swift_domain_id
    options['os_user_domain_id'] = CONF.vault_swift_domain_id
    options['os_tenant_name'] = CONF.vault_swift_tenant
    options['os_project_name'] = CONF.vault_swift_tenant
    options['os_region_name'] = CONF.region_name_for_services

    # needed to create Connection object
    options['authurl'] = CONF.vault_swift_auth_url
    options['auth'] = CONF.vault_swift_auth_url
    options['user'] = CONF.vault_swift_username
    options['key'] = CONF.vault_swift_password


CACHE_LOW_WATERMARK = 10
CACHE_HIGH_WATERMARK = 20

SEGMENT_FORMAT = "%016x.%08x"
lrucache = {}


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


class tmpfsfile():
    def __init__(self, remove=False):
        self.remove = remove
        pass

    def __enter__(self):
        tmpfs_mountpath = os.path.join(CONF.vault_data_directory_old,
                                       CONF.tmpfs_mount_path)
        fh, self.open_file = mkstemp(dir=tmpfs_mountpath)
        os.close(fh)
        if self.remove:
            os.remove(self.open_file)
        return self.open_file

    def __exit__(self, *args):
        os.remove(self.open_file)


class ObjectRepository(object):
    def __init__(self, root, **kwargs):
        self.root = root
        pass

    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path

    def object_open(self, object_name, flags):
        pass

    def object_upload(self, object_name, off, buf):
        pass

    def object_download(self, object_name, offset):
        pass

    def object_delete(self, object_name):
        pass

    def object_close(self, object_name, fh):
        pass

    def object_truncate(self, object_name, length, fh=None):
        pass

    def object_getattr(self, object_name, fh=None):
        pass

    def object_readdir(self, path, fh):
        pass

    def object_access(self, path, mode):
        pass

    def object_unlink(self, path):
        pass

    def object_statfs(self, path):
        pass


class SwiftRepository(ObjectRepository):
    def __init__(self, root, **kwargs):
        super(SwiftRepository, self).__init__(root, **kwargs)
        self.user_id = getpwnam(FUSE_USER).pw_uid
        self.group_id = getpwnam(FUSE_USER).pw_gid
        self.manifest = {}

    def split_head_tail(self, path):
        head, tail = os.path.split(path)
        prefix = ''
        while head not in ('', '/'):
            if prefix != '':
               prefix = os.path.join(tail, prefix)
            else:
                 prefix = tail
            head, tail = os.path.split(head)

        return tail, prefix

    def _get_head(self, path):
        head, tail = os.path.split(path)
        return head

    def _get_cache(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        if not os.path.isdir(self.root):
           try:
               command = ['sudo', 'mkdir', self.root]
               subprocess.call(command, shell=False)
               command = ['sudo', 'chown',
                          str(self.user_id)+':'+str(self.group_id),
                          self.root]
               subprocess.call(command, shell=False)
           except:
               pass
        else:
             stat_info = os.stat(self.root)
             if stat_info.st_uid != self.user_id or \
                 stat_info.st_gid != self.group_id:
                command = ['sudo', 'chown',
                           str(self.user_id)+':'+str(self.group_id),
                           CONF.vault_data_directory_old]
                subprocess.call(command, shell=False)

        #mount /var/triliovault/tmpfs
        try:
            tmpfs_mountpath = os.path.join(CONF.vault_data_directory_old,
                                           CONF.tmpfs_mount_path)
            if not os.path.isdir(tmpfs_mountpath):
                utils.ensure_tree(tmpfs_mountpath)

            if not os.path.ismount(tmpfs_mountpath):
                command = ['timeout', '-sKILL', '30', 'sudo', 'mount',
                           '-t', 'tmpfs', '-o', 'size=200M,mode=0777',
                           "tmpfs", tmpfs_mountpath]
                subprocess.check_call(command, shell=False)
        except:
            pass

        path = os.path.join(self.root, partial)
        return path

    def _read_object_manifest(self, object_name):

        container, prefix = self.split_head_tail(object_name)
        put_headers = {}
        mr = {}
        _opts = options.copy()
        _opts['object_name'] = prefix
        _opts = bunchify(_opts)
        conn = get_conn(_opts)
        conn.get_auth()
        rsp = conn.get_object(
                  container, prefix,
                  headers=put_headers,
                  query_string='multipart-manifest=get',
                  response_dict=mr
                  )

        manifest = rsp[1]

        return manifest

    def _write_object_manifest(self, object_name, object_manifest,
                               metadata={}):
        container, prefix = self.split_head_tail(object_name)
        put_headers = {}
        mr = {}
        put_headers['x-static-large-object'] = 'true'

        _opts = options.copy()
        _opts['object_name'] = prefix
        for key, value in metadata.iteritems():
            put_headers['X-Object-Meta-'+key] = value
        _opts = bunchify(_opts)
        conn = get_conn(_opts)
        conn.put_object(
            container, prefix, object_manifest,
            headers=put_headers,
            query_string='multipart-manifest=put',
            response_dict=mr
            )

        return

    def _get_object_metadata(self, object_name):
        container, prefix = self.split_head_tail(object_name)
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

        st = vaultswift.st_stat(args, _opts)
        metadata = {}
        for key, value in st['headers'].iteritems():
            if 'x-object-meta' in key:
                metadata[key.split('x-object-meta-')[1]] = value

        return metadata

    def object_open(self, object_name, flags):
        container, prefix = self.split_head_tail(object_name)
        full_path = self._full_path(object_name)

        self.manifest[object_name] = {}
        self.manifest[object_name]['readonly'] = flags == os.O_RDONLY or flags in (int('8000', 16), int('8800', 16))
 
        if flags == os.O_RDONLY or flags in (int('8000', 16), int('8800', 16)) or \
           flags == int('8401', 16) or \
           flags == os.O_RDWR or flags in (int('8002', 16), int('8802', 16)):
            # load manifst

            manifest = self._read_object_manifest(object_name)
            manifest = json.loads(manifest)
            for seg in manifest:
                offstr = seg['name'].split('-segments/')[1].split('.')[0]
                offset = int(offstr, 16)
                seg['modified'] = False
                self.manifest[object_name][offset] = seg

            metadata = self._get_object_metadata(object_name)
            self.manifest[object_name]['segments-dir'] = \
                metadata['segments-dir']

            try:
                segment_dir = self._full_path(self.manifest[object_name]['segments-dir'])
                os.makedirs(segment_dir)
            except:
                pass

            with open(full_path, "w") as f:
                f.write(json.dumps(manifest))

        else:
            # this is either write or create request
            if flags in (int('8001', 16), int('8801', 16), int('0001', 16)):
                try:
                    self.object_unlink(object_name)
                except:
                    pass

            if flags & os.O_WRONLY:
                with open(full_path, "w") as f:
                    pass

            try:
                segment_dir = self._full_path(object_name + "-segments")
                os.makedirs(segment_dir)
            except:
                pass

        return os.open(full_path, flags)

    def object_close(self, object_name, fh):

        try:
            segments_dir = self.manifest[object_name].get('segments-dir',
                                            object_name + "-segments")
            container, prefix = self.split_head_tail(segments_dir)
            object_manifest = []
            segments_list = {}
 
            if not self.manifest[object_name]['readonly']:
                offset = 0
                while True:
                    if offset not in self.manifest[object_name]:
                        break
                    if self.manifest[object_name][offset]['modified']:

                        st = self.object_getattr(self.manifest[object_name][offset]['name'], fh)
                        stat = bunchify(st)
                        object_manifest.append({"path": self.manifest[object_name][offset]['name'],
                                                "etag": stat.etag,
                                                "size_bytes": min(stat.st_size, CONF.vault_segment_size)})
                    else:
                        object_manifest.append({"path": self.manifest[object_name][offset]['name'],
                                                "etag": self.manifest[object_name][offset]['hash'],
                                                "size_bytes": self.manifest[object_name][offset]['bytes']})

                    offset += CONF.vault_segment_size 

                object_manifest = json.dumps(object_manifest)
                self._write_object_manifest(object_name, object_manifest,
                                            metadata={'segments-dir': segments_dir})

                offset = 0
                while True:
                    objects = self.segment_list(container, prefix, offset)
                    if len(objects) == 0:
                        break

                    objects = sorted(objects)
                    c, p = self.split_head_tail(self.manifest[object_name][offset]['name'])
                    for obj in list(set(objects) - set([p])):
                        self.object_delete(os.path.join(container, obj))

                    offset += CONF.vault_segment_size 
            try:
                os.close(fh)
            except:
                pass

            try:
                os.remove(self._full_path(object_name))
            except:
                pass

            try:
                shutil.rmtree(self._full_path(segments_dir))
            except:
                pass

            return
        except Exception as ex:
            LOG.exception(ex)
            pass

    def object_upload(self, object_name, offset, buf):
        if offset in self.manifest[object_name] and \
                self.manifest[object_name][offset]['modified'] is True:
            seg_fullname = self.manifest[object_name][offset]['name']
        else:
            segname = self.next_segname_from_offset(object_name, offset)
            segments_dir = self.manifest[object_name].get('segments-dir',
                                             object_name + "-segments")

            seg_fullname = os.path.join(segments_dir, segname)

        container, obj = self.split_head_tail(seg_fullname)
        cache_path = self._get_cache(seg_fullname)

        with tmpfsfile() as tempfs:
            with open(tempfs, "w") as f:
                f.write(buf)

            _opts = options.copy()
            _opts['segment_size'] = len(buf)
            _opts['object_name'] = obj.rstrip('/')
            _opts = bunchify(_opts)
            args1 = [container, tempfs]
            try:
                vaultswift.st_upload(args1, _opts)
            except Exception as ex:
                LOG.exception(ex)
                raise
        if offset not in self.manifest[object_name]:
            self.manifest[object_name][offset] = {}

        self.manifest[object_name][offset]['name'] = seg_fullname
        self.manifest[object_name][offset]['modified'] = True

    @disable_logging
    def object_download(self, object_name, offset):
        if offset not in self.manifest[object_name]:
            raise Exception('object %s not found' % object_name + SEGMENT_FORMAT % (int(offset), int(0)))
 
        seg_fullname = self.manifest[object_name][offset]['name']

        container, obj = self.split_head_tail(seg_fullname.rstrip('/'))
        # make sure that tmpfs is mounted
        cache_path = self._get_cache(seg_fullname)

        try:
            os.makedirs(self._full_path(segments_dir),  mode=0751)
        except:
            pass

        with tmpfsfile(remove=True) as tempfs:
            _opts = options.copy()
            _opts['prefix'] = None
            _opts['out_directory'] = None
            _opts['out_file'] = tempfs.rstrip('/')
            _opts = bunchify(_opts)
            args1 = [container, obj]
            try:
                vaultswift.st_download(args1, _opts)
                with open(tempfs.rstrip('/'), "rb") as f:
                    buf = f.read()
                return bytearray(buf)
            except Exception as ex:
                LOG.exception(ex)
                raise

    def object_delete(self, object_name):

        container, obj = self.split_head_tail(object_name)
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

    def object_truncate(self, object_name, length, fh=None):
        pass

    def segment_list(self, container, segments_dir, offset):
        _opts = options.copy()
        _opts['delimiter'] =  None
        _opts['human'] = False
        _opts['totals'] = False
        _opts['long'] = False
        _opts['prefix'] = os.path.join(segments_dir, "%016x" % int(offset))
        args = []
        if container == '':
            args = []
        else:
            args = [container]

        _opts = bunchify(_opts)
        return vaultswift.st_list(args, _opts)

    def next_segname_from_offset(self, path, offset):
        container, prefix = self.split_head_tail(path)
        segments_dir = self.manifest[path].get('segments-dir', None)
        if segments_dir:
            c, p = self.split_head_tail(segments_dir)
            segments_dir = p
        else:
            segments_dir = prefix + "-segments"
        files = self.segment_list(container, segments_dir, offset)
        if len(files) == 0:
            return SEGMENT_FORMAT % (int(offset), int(0))

        return SEGMENT_FORMAT % (int(offset),
            int(sorted(files)[-1].split(segments_dir)[1].split('.')[1], 16) + 1)
        pass

    def curr_segname_from_offset(self, path, offset):
        container, prefix = self.split_head_tail(path)

        if self.manifest.get(path, None) and \
            offset in self.manifest[path]:
            seg = self.manifest[path][offset]['name']
            return seg.split('-segments/')[1]

        segments_dir = self.manifest[path].get('segments-dir', None)
        if segments_dir:
            c, p = self.split_head_tail(segments_dir)
            segments_dir = p
        else:
            segments_dir = prefix + "-segments"

        files = self.segment_list(container, segments_dir, offset)
        if len(files) == 0:
            return SEGMENT_FORMAT % (int(offset), int(0))

        return SEGMENT_FORMAT % (int(offset),
            int(sorted(files)[-1].split(segments_dir)[1].split('.')[1], 16))

    def object_getattr(self, object_name, fh=None):
        full_path = self._full_path(object_name)
        container, prefix = self.split_head_tail(object_name)
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
            d['etag'] = st['headers'].get('etag', "")
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
                if not os.path.exists(self._get_cache(container)):
                    container_path = self._get_cache(container)
                    os.mkdir(container_path, 0751)
        except Exception as ex:
            if prefix is None:
                prefix = container
            full_path = self._get_cache(os.path.join(container, prefix))
            mkdirs = self._get_head(prefix)
            try:
                st = os.lstat(full_path)
            except:
                args1 = args
                if len(args1) > 1:
                    args1.pop()
                try:
                    _opts['prefix'] = os.path.join(_opts['prefix'], '')
                    st = vaultswift.st_list(args1, _opts)
                    if len(st) > 0:
                        os.mkdir(full_path, 0751)
                    else:
                        os.mkdir(container, 0751)
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
        return d

    def object_readdir(self, object_name, fh):
        listing = []
        container, prefix = self.split_head_tail(object_name)
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

        dirents = []
        _opts = bunchify(_opts)
        listing += vaultswift.st_list(args, _opts)
        for lst in listing:
            if prefix and prefix not in lst:
                continue
            if prefix:
                component, rest = self.split_head_tail(lst.split(prefix, 1)[1])
            else:
                component, rest = self.split_head_tail(lst)
            if component != '' or rest != '':
                mkdirs = os.path.join(container, self._get_head(lst))
                try:
                    os.makedirs(mkdirs, mode=0751)
                except:
                    pass
            if component is not None and component != '' and \
                not '-segments' in component and not '_segments' in component:
               if component not in dirents:
                   dirents.append(component) 
        for r in list(dirents):
            yield r

    def object_access(self, object_name, mode):
        pass

    def object_unlink(self, object_name, leave_segments=False):
        container, obj = self.split_head_tail(object_name)
        options['leave_segments'] = leave_segments
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

    def object_statfs(self, object_name):
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

    def mkdir(self, path, mode, ist=False):
        LOG.debug(("mkdir, %s" % path))
        container, obj = self.split_head_tail(path)
        if (obj == '' or obj == '/') and ist is False:
           _opts = options.copy()
           _opts = bunchify(_opts)
           args1 = [container]
           try:
               vaultswift.st_post(args1, _opts)
           except Exception as ex:
               LOG.exception(ex)
               return 0
           return 0

        cache_path = self._get_cache(path)
        if ist is False:
           cache_path = self._get_cache(os.path.join(container, obj))

        try:
            os.makedirs(cache_path, mode)
        except Exception as ex:
            pass
        return 0

    def rmdir(self, path):
        LOG.debug(("rmdir, %s" % path))
        container, obj = self.split_head_tail(path)
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

        cache_path = self._get_cache(path)
        return os.rmdir(cache_path)

    def chmod(self, path, mode):
        LOG.debug(("chmod, %s" % path))
        try:
            container, prefix = self.split_head_tail(path)
            cache_path = self._get_cache(os.path.join(container, prefix))
            return os.chmod(cache_path, mode)
        except:
            pass

    def chown(self, path, uid, gid):
        LOG.debug(("chown, %s" % path))
        try:
            container, prefix = self.split_head_tail(path)
            cache_path = self._get_cache(os.path.join(container, prefix))
            return os.chown(cache_path, uid, gid)
        except:
            pass

    def symlink(self, name, target):
        raise Exception("Not Applicable")

    def rename(self, old, new):
        LOG.debug(( "rename, %s -> %s" % (old, new)))
        #make a copy of the manifest
        try:
            manifest = self._read_object_manifest(old)
            metadata = self._get_object_metadata(old)
            segments_dir = metadata.get('segments-dir', old + '-segments')
 
            manifest = json.loads(manifest)
            new_manifest = []
            for man in manifest:
                new_manifest.append({"path": man['name'],
                                     "etag": man['hash'],
                                     "size_bytes": man['bytes']})
            new_manifest = json.dumps(new_manifest)
            self._write_object_manifest(new, new_manifest,
                                        metadata={'segments-dir': segments_dir})
            self.object_unlink(old, leave_segments=True)
        except:
            self.object_unlink(new, leave_segments=True)

        return 0

    def link(self, target, name):
        LOG.debug(( "link, %s" % target))
        container, prefix = split_head_tail(target)
        cache_path_target = self._get_cache(os.path.join(container, prefix))
        container, prefix = split_head_tail(name)
        cache_path_name = self._get_cache(os.path.join(container, prefix))
        return os.link(cache_path_target, cache_path_name)

    def utimens(self, path, times=None):
        LOG.debug(( "utimens, %s" % path))
        container, prefix = split_head_tail(path)
        cache_path = self._get_cache(path)
        """ This file won't be existing until not downloaded for writing/reading"""
        try:
            os.utime(cache_path, times)
        except:
            return 0

        return 0

    def destroy(self, path):
        try:
            tmpfs_mountpath = os.path.join(CONF.vault_data_directory_old,
                                           CONF.tmpfs_mount_path)
            if os.path.isdir(tmpfs_mountpath) and \
               os.path.ismount(tmpfs_mountpath):
                command = ['timeout', '-sKILL', '30', 'sudo', 'umount',
                           tmpfs_mountpath]
                subprocess.check_call(command, shell=False)
        except:
            pass

        if vaultswift.swift_list: vaultswift.swift_list.__exit__(None, None, None)
        if vaultswift.swift_stat: vaultswift.swift_stat.__exit__(None, None, None)
        if vaultswift.swift_upload: vaultswift.swift_upload.__exit__(None, None, None)
        if vaultswift.swift_download: vaultswift.swift_download.__exit__(None, None, None)
        if vaultswift.swift_delete: vaultswift.swift_delete.__exit__(None, None, None)
        if vaultswift.swift_post: vaultswift.swift_post.__exit__(None, None, None)
        if vaultswift.swift_cap: vaultswift.swift_cap.__exit__(None, None, None) 
        shutil.rmtree(self.root)
        return 0

class FileRepository(ObjectRepository):
    def __init__(self, root, **kwargs):
        super(FileRepository, self).__init__(root, **kwargs)

    def object_open(self, object_name, flags):
        if flags & (os.O_CREAT | os.O_WRONLY):
            self.object_delete(object_name)
        try:
            segment_dir = self._full_path(object_name) + "-segments"
            os.makedirs(segment_dir)
        except:
            pass

        full_path = self._full_path(object_name)
        return os.open(full_path, flags)

    def object_upload(self, object_name, off, buf):
        # always bump current version
        segname = self.next_segname_from_offset(object_name, off)
        segment_dir = self._full_path(object_name + "-segments")
        seg_fullname = os.path.join(segment_dir, segname)
        with open(seg_fullname, "w") as segf:
            segf.write(buf)

    def object_download(self, object_name, offset):
        segment_dir = self._full_path(object_name + "-segments")
        segname = self.curr_segname_from_offset(object_name, offset)
        object_name = os.path.join(segment_dir, segname)
        with open(object_name, "r") as segf:
            return bytearray(segf.read())

    def object_delete(self, object_name):
        manifest_filename = self._full_path(object_name) + ".manifest"
        try:
            shutil.rmtree(manifest_filename.split(".manifest")[0] + "-segments")
            os.remove(manifest_filename)
        except:
            pass

    def object_close(self, object_name, fh):
        full_path = self._full_path(object_name)
        manifest = full_path + ".manifest"
        segment_dir = self._full_path(object_name + "-segments")
        object_manifest = []
        segments_list = {}
        offset = 0
        while True:
            segments_list[offset] = objects = self.segment_list(segment_dir, offset)
            if len(objects) == 0:
                break

            objects = sorted(objects)
            stat = os.stat(objects[-1])
            object_manifest.append({"path": objects[-1],
                                    "etag": "etagoftheobjectsegment1",
                                    "size_bytes": min(stat.st_size, CONF.vault_segment_size)})
            offset += CONF.vault_segment_size 

        with open(manifest, "w") as manf:
            manf.write(json.dumps(object_manifest))

        offset = 0
        while True:
            objects = segments_list[offset]
            if len(objects) == 0:
                break

            objects = sorted(objects)
            for obj in list(set(objects) - set([objects[-1]])):
                os.remove(obj) 

            offset += CONF.vault_segment_size 

        os.close(fh)
        return

    def object_truncate(self, object_name, length, fh=None):
        full_path = self._full_path(object_name)
        with open(full_path, 'r+') as f:
            f.truncate(length)

    def segment_list(self, segment_dir, offset):
        return glob.glob(os.path.join(segment_dir, '%016x.[0-9a-f]*' % int(offset)))

    def next_segname_from_offset(self, path, offset):
        segment_dir = self._full_path(path) + "-segments"
        files = self.segment_list(segment_dir, offset)
        if len(files) == 0:
            return SEGMENT_FORMAT % (int(offset), int(0))
        else:
            manifestfile = self._full_path(path) + ".manifest"
            with open(manifestfile, "r") as manf:
                manifest = json.load(manf)
                for obj in manifest:
                    segnum = '/%016x' % offset
                    if segnum in obj['path']:
                        segname = obj['path'].split(segment_dir)[1]
                        version = int(segname.split('.')[1], 16) + 1
                        return SEGMENT_FORMAT % (int(offset), int(version))

        return SEGMENT_FORMAT % (int(offset), int(sorted(files)[-1].split(segment_dir)[1].split('.')[1], 16) + 1)

    def curr_segname_from_offset(self, path, offset, forread=False):
        segment_dir = self._full_path(path) + "-segments"
        files = self.segment_list(segment_dir, offset)
        if len(files) == 0:
            if forread:
                raise Exception("Segment does not exists")
            return SEGMENT_FORMAT % (int(offset), int(0))
        else:
            manifestfile = self._full_path(path) + ".manifest"
            with open(manifestfile, "r") as manf:
                manifest = json.load(manf)
                for obj in manifest:
                    segnum = '/%016x' % offset
                    if segnum in obj['path']:
                        segname = obj['path'].split(segment_dir)[1]
                        version = int(segname.split('.')[1], 16)
                        return SEGMENT_FORMAT % (int(offset), int(version))

        return SEGMENT_FORMAT % (int(offset), int(sorted(files)[-1].split(segment_dir)[1].split('.')[1], 16))

    def object_getattr(self, object_name, fh=None):
        full_path = self._full_path(object_name)
        st = os.lstat(full_path)
        attrs = dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                     'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

        try:
            with open(full_path + ".manifest") as manf:
                attrs['st_size'] = 0
                for seg in json.load(manf):
                    attrs['st_size'] += seg['size_bytes']
        except:
            pass
        return attrs

    def object_readdir(self, path, fh):
        full_path = self._full_path(path)
        dirents = []
        if os.path.isdir(full_path):
            listing = []
            for d in os.listdir(full_path):
                if ".manifest" in d:
                    listing.append(d.split(".manifest")[0])
            dirents.extend(listing)

        return dirents

    def object_access(self, path, mode):
        full_path = self._full_path(path)
        if not os.access(full_path, mode):
            raise FuseOSError(errno.EACCES)

    def object_unlink(self, path):
        return self.object_delete(path)

    def object_statfs(self, path):
        full_path = self._full_path(path)
        stv = os.statvfs(full_path)
        return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))

    def destroy(self, path):
        shutil.rmtree(self.root)
        return 0


class FuseCache(object):
    def __init__(self, root, repository):
        global lrucache
        self.root = root
        self.repository = repository
        self.lrucache = lrucache

    def object_open(self, object_name, flags):
        fh = self.repository.object_open(object_name, flags)
        if self.lrucache.get(fh, None):
            self.lrucache.pop(fh)

        self.lrucache[fh] = {'lrucache': LRUCache(maxsize=CONF.vault_cache_size),
                             'object_name': object_name}
        return fh
     
    def object_flush(self, object_name, fh):
        item = self.lrucache[fh]
        assert item['object_name'] == object_name
        cache = item['lrucache']
        try:
            while True:
                off, item = cache.popitem()
                if item['modified'] == True:
                    self.repository.object_upload(object_name, off, item['data'])
        except:
            pass

    def object_close(self, object_name, fh):
        self.object_flush(object_name, fh)
        self.repository.object_close(object_name, fh)
        self.lrucache.pop(fh)
        return

    def object_truncate(self, object_name, length, fh=None):
        self.repository.object_truncate(object_name, length, fh)

    def _walk_segments(self, offset, length):
        while length != 0:
            seg_offset = offset/CONF.vault_segment_size * CONF.vault_segment_size
            base = offset - seg_offset
            seg_len = min(length, CONF.vault_segment_size - base)
            yield seg_offset, base, seg_len
            offset += seg_len
            length -= seg_len

    def object_read(self, object_name, length, offset, fh):
        #if len(cache) == CONF.vault_cache_size:
            #off, item = cache.popitem()
            #segname = next_segname_from_offset(off)
            #object_name = os.path.join(SEGMENT_DIR, segname)
            # if modified upload to object store. We assume 
            # it is not modified for now
            #object_upload(object_name, item)
        assert self.lrucache[fh]['object_name'] == object_name
        output_buf = bytearray()
        for segoffset, base, seg_len in self._walk_segments(offset, length):
            try:
                segdata = self.lrucache[fh]['lrucache'][segoffset]['data']
            except:
                try:
                    # cache miss. free up a cache slot 
                    cache = self.lrucache[fh]['lrucache']
                    if len(cache) == CONF.vault_cache_size:
                        # cache overflow
                        # kick an item so we can accomodate new one
                        off, item = cache.popitem()
                        if item['modified'] == True:
                            self.repository.object_upload(object_name, off, item['data'])
  
                    segdata = self.repository.object_download(object_name, segoffset)
                    self.lrucache[fh]['lrucache'][segoffset] = {'modified': False, 'data': segdata }
                except:
                    # end of file
                    return 0

            output_buf += segdata[base:base+seg_len]

        return str(output_buf)

    def object_write(self, object_name, buf, offset, fh):
 
        length = len(buf)
        assert self.lrucache[fh]['object_name'] == object_name
        bufptr = 0
        for segoffset, base, seg_len in self._walk_segments(offset, length):

            cache = self.lrucache[fh]['lrucache']
            if segoffset not in cache:
                if len(cache) == CONF.vault_cache_size:
                    # cache overflow
                    # kick an item so we can accomodate new one
                    off, item = cache.popitem()
                    if item['modified'] == True:
                        self.repository.object_upload(object_name, off, item['data'])
  
                # we need to handle offset that is not object segment boundary
                # read the segment before modifying it
                try:
                    # populate cache
                    segdata = self.repository.object_download(object_name, segoffset)
                    if segdata is None:
                        raise Exception("Object not found")

                    cache[segoffset] = {'modified': False, 'data': segdata}
                except:
                    # we have not written the segment to the repository yet
                    segdata = bytearray(1)
                    cache[segoffset] = {'modified': True, 'data': segdata}
            else:
                segdata = cache[segoffset]['data']

            if len(segdata) < base:
                segdata.extend('\0' * (base+seg_len - len(segdata)))
            segdata[base:base+seg_len] = buf[bufptr:bufptr+seg_len]

            cache[segoffset]['modified'] = True
            bufptr += seg_len

        return len(buf)

    def mkdir(self, path, mode):
        return os.mkdir(self._full_path(path), mode)

    def rmdir(self, path):
        full_path = self._full_path(path)
        return os.rmdir(full_path)

    def chmod(self, path, mode):
        full_path = self._full_path(path)
        return os.chmod(full_path, mode)

    def chown(self, path, uid, gid):
        full_path = self._full_path(path)
        return os.chown(full_path, uid, gid)


class TrilioVault(Operations):
    def __init__(self, root, repository=None):
        self.root = root
        self.repository = repository or SwiftRepository(root)
        self.cache = FuseCache(root, self.repository)

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        self.repository.object_access(path, mode)

    def chmod(self, path, mode):
        return self.repository.chmod(path, mode)

    def chown(self, path, uid, gid):
        return self.repository.chown(path, uid, gid)

    @disable_logging
    def getattr(self, path, fh=None):
        return self.repository.object_getattr(path, fh)

    def readdir(self, path, fh):
        dirents = ['.', '..']
        dirents.extend(self.repository.object_readdir(path, fh))
        for r in dirents:
            yield r

    def readlink(self, path):
        pathname = os.readlink(self._full_path(path))
        if pathname.startswith("/"):
            # Path name is absolute, sanitize it.
            return os.path.relpath(pathname, self.root)
        else:
            return pathname

    def mknod(self, path, mode, dev):
        return os.mknod(self._full_path(path), mode, dev)

    def rmdir(self, path):
        return self.repository.rmdir(path)

    def mkdir(self, path, mode):
        return self.repository.mkdir(path, mode)

    def statfs(self, path):
        return self.repository.object_statfs(path)

    def unlink(self, path):
        return self.repository.object_unlink(path)

    def symlink(self, name, target):
        return self.repository.symlink(name, target)

    def rename(self, old, new):
        return self.repository.rename(old, new)

    def link(self, target, name):
        return self.repository.link(target, name)

    def utimens(self, path, times=None):
        return self.repository.utimens(path, times)

    # File methods
    # ============

    def open(self, path, mode):
        return self.cache.object_open(path, mode)

    def create(self, path, mode, fi=None):
        return self.open(path, os.O_CREAT)

    def read(self, path, length, offset, fh):
        buf = self.cache.object_read(path, length, offset, fh)
        return buf

    def write(self, path, buf, offset, fh):
        return self.cache.object_write(path, buf, offset, fh)

    def truncate(self, path, length, fh=None):
        self.cache.object_truncate(path, length, fh=fh)

    def flush(self, path, fh):
        self.cache.object_flush(path, fh)

    def release(self, path, fh):
        self.cache.object_close(path, fh)
        return

    def fsync(self, path, fdatasync, fh):
        return self.cache.object_flush(path, fh)

    def destroy(self, path):
          LOG.debug( "destroy, %s" % path)
          return self.repository.destroy(path)


def fuse_conf():
    with open('/etc/fuse.conf', 'r') as f:
         found = 0
         for line in f:
             if 'user_allow_other' in line and '#user_allow_other' not in line:
                found = 1
                break
    if found == 0:
       with open('/etc/fuse.conf', 'rt') as f:
            s = f.read() + '\n' + 'user_allow_other \n'
       with open('/tmp/fuse.conf.tmp', 'wt') as outf:
            outf.write(s)
       os.system('sudo mv /tmp/fuse.conf.tmp /etc/fuse.conf')
       os.system('sudo chown root:root /etc/fuse.conf')
      
def main(mountpoint, cacheroot):
    try:
        try:
            command = ['sudo', 'umount', '-l', mountpoint]
            subprocess.call(command, shell=False)
        except:
               pass
        if os.path.isdir(mountpoint):
           os.system('sudo chown -R '+ FUSE_USER+':'+FUSE_USER+' '+ mountpoint)
        else:
             command = ['sudo', 'mkdir', mountpoint]
             subprocess.call(command, shell=False)
             command = ['sudo', 'chown', FUSE_USER+':'+FUSE_USER, mountpoint]
             subprocess.call(command, shell=False)
    except Exception as ex:
           pass

    tvaultplugin =  TrilioVault(cacheroot,
                      repository=SwiftRepository(cacheroot))
    FUSE(tvaultplugin, mountpoint,
         nothreads=True, foreground=True, nonempty=True,
         big_writes=True, direct_io=True, allow_other=True)

if __name__ == '__main__':
    fuse_conf()
    main(CONF.vault_data_directory, CONF.vault_data_directory_old )
