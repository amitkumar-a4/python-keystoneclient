# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Command-line flag library.

Emulates gflags by wrapping cfg.ConfigOpts.

The idea is to move fully to cfg eventually, and this wrapper is a
stepping stone.

"""

import os
import socket
import sys
import multiprocessing

try:
   from oslo_config import cfg
except ImportError:
   from oslo.config import cfg

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import version

FLAGS = cfg.CONF


def parse_args(argv, default_config_files=None):
    FLAGS(argv[1:], project='workloadmgr',
          version=version.version_string(),
          default_config_files=default_config_files)


class UnrecognizedFlag(Exception):
    pass


def DECLARE(name, module_string, flag_values=FLAGS):
    if module_string not in sys.modules:
        __import__(module_string, globals(), locals())
    if name not in flag_values:
        raise UnrecognizedFlag('%s not defined by %s' % (name, module_string))


def _get_my_ip():
    """
    Returns the actual ip of the local machine.

    This code figures out what source address would be used if some traffic
    were to be sent out to some well known address on the Internet. In this
    case, a Google DNS server is used, but the specific address does not
    matter much.  No traffic is actually sent.
    """
    try:
        csock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        csock.connect(('8.8.8.8', 80))
        (addr, port) = csock.getsockname()
        csock.close()
        return addr
    except socket.error:
        return "127.0.0.1"


core_opts = [
    cfg.StrOpt('connection_type',
               default=None,
               help='Virtualization api connection type : libvirt, xenapi, '
                    'or fake'),
    cfg.StrOpt('sql_connection',
               default='sqlite:///$state_path/$sqlite_db',
               help='The SQLAlchemy connection string used to connect to the '
                    'database',
               secret=True),
    cfg.IntOpt('sql_connection_debug',
               default=0,
               help='Verbosity of SQL debugging information. 0=None, '
                    '100=Everything'),
    cfg.StrOpt('api_paste_config',
               default="api-paste.ini",
               help='File name for the paste.deploy config for workloadmgr-api'),
    cfg.StrOpt('pybasedir',
               default=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                    '../')),
               help='Directory where the workloadmgr python module is installed'),
    cfg.StrOpt('bindir',
               default='$pybasedir/bin',
               help='Directory where workloadmgr binaries are installed'),
    cfg.StrOpt('state_path',
               default='$pybasedir',
               help="Top-level directory for maintaining workloadmgr's state"), ]

debug_opts = [
]

FLAGS.register_cli_opts(core_opts)
FLAGS.register_cli_opts(debug_opts)

global_opts = [
    cfg.StrOpt('my_ip',
               default=_get_my_ip(),
               help='ip address of this host'),
    cfg.StrOpt('scheduler_topic',
               default='workloadmgr-scheduler',
               help='the topic scheduler nodes listen on'),
    cfg.StrOpt('workloads_topic',
               default='workloadmgr-workloads',
               help='the topic workload nodes listen on'),
    cfg.BoolOpt('enable_v1_api',
                default=True,
                help=_("Deploy v1 of the WorkloadMgr API. ")),
    cfg.BoolOpt('api_rate_limit',
                default=True,
                help='whether to rate limit the api'),
    cfg.ListOpt('osapi_workloadmgr_ext_list',
                default=[],
                help='Specify list of extensions to load when using osapi_'
                     '_extension option with workloadmgr.api.contrib.'
                     'select_extensions'),
    cfg.MultiStrOpt('osapi_workloadmgr_extension',
                    default=['workloadmgr.api.contrib.standard_extensions'],
                    help='osapi workloadmgr extension to load'),
    cfg.StrOpt('osapi_workloadmgr_base_URL',
               default=None,
               help='Base URL that will be presented to users in links '
                    'to the OpenStack Workload Manager API'),
    cfg.IntOpt('osapi_max_limit',
               default=1000,
               help='the maximum number of items returned in a single '
                    'response from a collection resource'),
    # cfg.StrOpt('sqlite_db',
    # default='workloadmgr.sqlite',
    # help='the filename to use with sqlite'),
    # cfg.BoolOpt('sqlite_synchronous',
    # default=True,
    # help='If passed, use synchronous mode for sqlite'),
    cfg.IntOpt('sql_idle_timeout',
               default=3600,
               help='timeout before idle sql connections are reaped'),
    cfg.IntOpt('sql_max_retries',
               default=10,
               help='maximum db connection retries during startup. '
                    '(setting -1 implies an infinite retry count)'),
    cfg.IntOpt('sql_retry_interval',
               default=10,
               help='interval between retries of opening a sql connection'),
    cfg.StrOpt('workloads_manager',
               default='workloadmgr.workloads.manager.WorkloadMgrManager',
               help='full class name for the Manager for workloadmgr'),
    cfg.StrOpt('scheduler_manager',
               default='workloadmgr.scheduler.manager.SchedulerManager',
               help='full class name for the Manager for scheduler'),
    cfg.StrOpt('host',
               default=socket.gethostname(),
               help='Name of this node.  This can be an opaque identifier.  '
                    'It is not necessarily a hostname, FQDN, or IP address.'),
    # NOTE(vish): default to nova for compatibility with nova installs
    cfg.StrOpt('storage_availability_zone',
               default='nova',
               help='availability zone of this node'),
    cfg.ListOpt('memcached_servers',
                default=None,
                help='Memcached servers or None for in process cache.'),
    cfg.StrOpt('root_helper',
               default='sudo',
               help='Deprecated: command to use for running commands as root'),
    cfg.StrOpt('rootwrap_config',
               default=None,
               help='Path to the rootwrap configuration file to use for '
                    'running commands as root'),
    cfg.BoolOpt('monkey_patch',
                default=False,
                help='Whether to log monkey patching'),
    cfg.ListOpt('monkey_patch_modules',
                default=[],
                help='List of modules/decorators to monkey patch'),
    cfg.IntOpt('service_down_time',
               default=60,
               help='maximum time since last check-in for up service'),
    cfg.StrOpt('workloads_api_class',
               default='workloadmgr.workloads.api.API',
               help='The full class name of the volume API class to use'),
    cfg.StrOpt('auth_strategy',
               default='noauth',
               help='The strategy to use for auth. Supports noauth, keystone, '
                    'and deprecated.'),
    cfg.IntOpt('workloads_workers',
               default=multiprocessing.cpu_count(),
               help='Parallel processing of workloads '
                    'depending on cpus'),
]

FLAGS.register_opts(global_opts)
