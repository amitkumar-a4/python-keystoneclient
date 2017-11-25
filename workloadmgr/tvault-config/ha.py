#!/usr/bin/env import pdb;pdb.set_trace()
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

import threading
import sys
import subprocess
import xml.etree.ElementTree as ET
from netaddr import IPAddress

try:
    from oslo_config import cfg
except ImportError:
    from oslo.config import cfg

try:
    from oslo_log import log as logging
except ImportError:
    from nova.openstack.common import log as logging

_DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
import tvault_config_bottle as tv


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

tvault_opts = [
    cfg.StrOpt('enable_ha',
               default='off',
               help='Enbale ha'),
    cfg.StrOpt('rabbit_host',
               default='none',
               help='node ip address'),
    cfg.StrOpt('rabbit_password',
               default='52T8FVYZJse',
               help='password'),
    cfg.StrOpt('region_name_for_services',
               default='RegionOne',
               help='Service region'),
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

CONF = cfg.CONF
CONF.register_cli_opts(tvault_opts)
CONF.register_cli_opts(logging_cli_opts)
CONF.register_cli_opts(generic_log_opts)
CONF.register_cli_opts(log_opts)
CONF.register_cli_opts(common_cli_opts)
CONF(sys.argv[1:], project='ha')
LOG = logging.getLogger(__name__)
logging.setup(cfg.CONF, 'ha')
try:
    LOG.logger.setLevel(logging.ERROR)
except BaseException:
    LOG.logger.setLevel(logging.logging.ERROR)


def enable_ha():
  if CONF.enable_ha == 'on':
     result = subprocess.check_output(['crm','node','status'])
     root = ET.fromstring(result)
     node_list = []
     node_list_ip = []
     configured_host = []
     node_address = CONF.rabbit_host
     node_host_name = ''
     node_name = "galera"
     virtual_ip = ''
     mysql_ha_string = ''
     api_ha_string = ''
     host_string = "\n"
     node_number = 0
     for child in root:
         node_list.append(child.get('uname'))
         for c1 in child.getchildren():
             for c2 in c1.getchildren():
                 if c2.get('name') == 'configured' and c2.get('value') == 'yes':
                    configured_host.append(child.get('uname'))
                 if c2.get('name') == 'virtip':
                    virtual_ip = c2.get('value')
                 if c2.get('name') == 'ip':
                    if c2.get('value') == node_address:
                       node_host_name = child.get('uname')
                       node_number = len(node_list_ip)+1
                       node_name = node_name+str(node_number)
                    node_list_ip.append(c2.get('value'))
                    mysql_ha_string = mysql_ha_string+"server "+child.get('uname')+" "+c2.get('value')+":3306 check port 3306\n"
                    api_ha_string = api_ha_string+"server "+child.get('uname')+" "+c2.get('value')+":8780 check inter 18000 rise 2 fall 5\n"
                    host_string = host_string+child.get('uname')+" "+c2.get('value')+"\n"
     node_str = ",".join(node_list_ip)
     if len(node_list) >= 3 and node_host_name not in configured_host:

        fl = open("/etc/hosts", "a+")
        fl.write(host_string)
        fl.close()

        data = "[mysqld]\nbinlog_format=ROW\ndefault-storage-engine=innodb\ninnodb_autoinc_lock_mode=2\nbind-address="+node_address+"\n# Galera Provider Configuration\nwsrep_on=ON\nwsrep_provider=/usr/lib/galera/libgalera_smm.so\n# Galera Cluster Configuration\nwsrep_cluster_name=\"unique\"\nwsrep_cluster_address=\"gcomm://"+node_str+"\"\n# Galera Synchronization Configuration\nwsrep_sst_method=rsync\n# Galera Node Configuration\nwsrep_node_address=\""+node_address+"\"\nwsrep_node_name=\""+node_name+"\" "
        fl = open("/etc/mysql/conf.d/galera.cnf", "w+")
        fl.write(data)
        fl.close()

        data1 = "global\nchroot  /var/lib/haproxy\ndaemon\ngroup  haproxy\nmaxconn  4000\npidfile  /var/run/haproxy.pid\nuser  haproxy\n\ndefaults\nlog  global\nmaxconn  4000\noption  redispatch\nretries  3\ntimeout  http-request 10s\ntimeout  queue 1m\ntimeout  connect 10s\ntimeout  client 1m\ntimeout  server 1m\ntimeout  check 10s\n\nlisten galera_cluster\n"+virtual_ip+":33308\nbalance roundrobin\noption tcpka\noption mysql-check user haproxy\n"+mysql_ha_string+"\nlisten wlm_api_cluster\nbind "+virtual_ip+":8781\nbalance roundrobin\noption  tcpka\noption  httpchk\n"+api_ha_string
        fl = open("/etc/haproxy/haproxy.cfg", "w+")
        fl.write(data1)
        fl.close()

        fl = open("/etc/default/haproxy", "w+")
        fl.write("START=1")
        fl.close()

        command = 'service rabbitmq-server stop'
        subprocess.check_call(command, shell=True)
        if node_number == 1:
           command = "/sbin/ifconfig eth0 | awk '/Mask:/{ print $4;} '"
           result = subprocess.check_output(command, shell=True)
           netmask = result.replace('\n','').replace('Mask:','')
           netmask = str(IPAddress(netmask).netmask_bits())
           command = 'crm configure primitive vip ocf:heartbeat:IPaddr2 params ip="'+virtual_ip+'" cidr_netmask="'+netmask+'"\
                      op monitor interval="30s"'
           subprocess.check_call(command, shell=True)        
           command = 'crm cib new conf-haproxy'
           subprocess.check_call(command, shell=True)
           command = 'crm configure primitive haproxy lsb:haproxy op monitor interval="1s"'
           subprocess.check_call(command, shell=True)
           command = 'crm configure clone haproxy-clone haproxy'
           subprocess.check_call(command, shell=True)
           command = 'crm configure colocation vip-with-haproxy inf: vip haproxy-clone'
           subprocess.check_call(command, shell=True)
           command = 'crm configure order haproxy-after-vip mandatory: vip haproxy-clone'
           subprocess.check_call(command, shell=True)
           for np in node_list_ip:
               if np != node_address:
                  command = 'sshpass -p "'+CONF.rabbit_password+'" scp /var/lib/rabbitmq/.erlang.cookie root@'+np+':/var/lib/rabbitmq/.erlang.cookie'
                  subprocess.check_call(command, shell=True)


        command = 'chown rabbitmq:rabbitmq /var/lib/rabbitmq/.erlang.cookie'
        subprocess.check_call(command, shell=True)
        command = 'chmod 400 /var/lib/rabbitmq/.erlang.cookie'
        subprocess.check_call(command, shell=True)
        command = 'service rabbitmq-server start'
        subprocess.check_call(command, shell=True)
        command = 'rabbitmqctl stop_app'
        subprocess.check_call(command, shell=True)
        command = 'rabbitqmctl force_reset'
        subprocess.check_call(command, shell=True)
        if node_number != 1:
           command = 'rabbitqmctl join_cluster --ram rabbit@'+node_list[0]
           subprocess.check_call(command, shell=True)
        command = 'rabbitmqctl start_app'
        subprocess.check_call(command, shell=True)       
        command = 'rabbitmqctl change_password guest '+CONF.rabbit_password
        subprocess.check_call(command, shell=True)

        if node_number == 1:
           command = "rabbitmqctl set_policy ha-all '^(?!amq\.).*' '{\"ha-mode\": \"all\"}'"
           subprocess.check_call(command, shell=True)

        command = 'service rabbitmq-server restart'
        subprocess.check_call(command, shell=True)

        command = 'crm attribute '+node_host_name+' set configured yes'
        subprocess.check_call(command, shell=True)
        threading.Timer(5.0, enable_ha).start()

     elif len(configured_host) >= 3:
          if node_number == 1:
             command = "mysql -h"+node_address+" -u root -p"+CONF.rabbit_password+" -e \"SHOW STATUS LIKE 'wsrep_cluster_size'\""
             result = subprocess.check_output(command, shell=True)
             if result == "":
                command = 'service mysql start --wsrep-new-cluster'
                subprocess.check_call(command, shell=True)
             else:
                  command = 'service mysql restart'
                  subprocess.check_call(command, shell=True)
          else:
               command = 'service mysql restart'
               subprocess.check_call(command, shell=True)

          command = "mysql -h"+node_address+" -u root -p"+CONF.rabbit_password+" -e \"SHOW STATUS LIKE 'wsrep_cluster_size'\""
          result = subprocess.check_output(command, shell=True)
          if node_number == 1:
             if result != '' and int(result.split('\n')[1].split('\t')[1]) >= 0:
                command = 'mysql --host='+node_address+' -u root -p'+CONF.rabbit_password+' -e "CREATE USER \'haproxy\'@\''+virtual_ip+'\';'
                subprocess.check_call(command, shell=True)
                command = 'mysql --host='+node_address+' -u root -p'+CONF.rabbit_password+' -e "GRANT ALL PRIVILEGES ON *.* \
                           TO \'root\'@\'%\' IDENTIFIED BY \'galera\' WITH GRANT OPTION;FLUSH PRIVILEGES;'
                subprocess.check_call(command, shell=True)
                command = 'service mysql restart'
                subprocess.check_call(command, shell=True)

          if result != '' and int(result.split('\n')[1].split('\t')[1]) >= 0:
             sql_connection = 'mysql://root:'+CONF.rabbit_password+'@'+virtual_ip+':33308/workloadmgr?charset=utf8'
             tv.replace_line(
                '/etc/workloadmgr/workloadmgr.conf',
                'sql_connection = ',
                'sql_connection = ' +
                sql_connection)

          fl = open('/etc/workloadmgr/workloadmgr.conf', 'r')
          contents = fl.readlines()
          fl.close()

          rb_st = ''
          for np in node_list:
              rb_st= rb_st+np+':5672,'
          rb_st = rb_st[:-1]
          rabbit_str = '\nrabbit_hosts = '+rb_st+'\nrabbit_ha_queues=true\nrabbit_durable_queues=true\n \
                        rabbit_max_retries=0\nrabbit_retry_backoff=2\n  \
                        rabbit_retry_interval=1\n'
          contents.insert(42, rabbit_str)

          fl = open("/etc/workloadmgr/workloadmgr.conf", "w")
          contents = "".join(contents)
          fl.write(contents)
          fl.close()

          if node_number == 1:
             wlm_url = 'http://' + virtual_ip + ':8781' + '/v1/$(tenant_id)s'
             tv.change_service_endpoint(wlm_url, CONF.region_name_for_services)

          command = 'service haproxy restart'
          subprocess.check_call(command, shell=True)     

          command = 'service wml-api restart'
          subprocess.check_call(command, shell=True)  

          command = 'service wlm-scheduler restart'
          subprocess.check_call(command, shell=True)       
  
          command = 'service wlm-workloads restart'
          subprocess.check_call(command, shell=True) 

     else:
          threading.Timer(5.0, enable_ha).start()
  else:
        threading.Timer(50.0, enable_ha).start()
 
if __name__ == '__main__':
   try:
       enable_ha()
   except Exception as ex:
          LOG.exception(ex)
          pass
