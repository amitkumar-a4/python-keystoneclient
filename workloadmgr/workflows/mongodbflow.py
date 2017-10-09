# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

'''
Workflow for taking snapshot of mongodb instances
'''

import contextlib
import os
import random
import sys
import time

import json
import datetime
import paramiko
import uuid
from tempfile import mkstemp
import subprocess

from taskflow import engines
from taskflow.utils import misc
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import graph_flow as gf
from taskflow import task
from taskflow import flow

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import utils
from workloadmgr import exception
from workloadmgr import settings

import vmtasks
import workflow

import pymongo
from pymongo import MongoClient
from pymongo import MongoReplicaSetClient
from pymongo import MongoClient, ReadPreference


LOG = logging.getLogger(__name__)

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)

#from workloadmgr import exception
#
# Function that create the connection to the mongos server to be use as
# primary source of information in order to pick the servers. host, port
# user and password should be fed into the flow and other tasks should use
# them as needed.
#


def connect_server(host, port, user, password, verbose=False):
    try:
        connection = None
        if user != '':
            auth = 'mongodb://' + user + ':' + \
                password + '@' + host + ':' + str(port)
            connection = MongoClient(auth)
        else:
            auth = ''
            connection = MongoClient(host, int(port))

        if verbose:
            LOG.debug(_('Connected to ' + host + ' on port ' + port + '...'))

    except Exception as ex:
        LOG.error(_('Oops!  There was an error.  Try again...'))
        LOG.error(_(ex))
        if ex.__class__.__name__ == 'ConnectionFailure':
            error = _('Failed to connect MongoDB node %s') % (str(host))
        elif ex.__class__.__name__ == 'ConfigurationError':
            error = _(
                'Wrong username/password entered for MongoDB node  %s') % (str(host))
        else:
            error = _('Failed to connect MongoDB node %s') % (str(host))

        raise exception.ErrorOccurred(reason=error)

    return connection


def isShardedCluster(conn):
    try:
        status = conn.admin.command("ismaster")
        return not ('primary' in status and 'secondary' in status)
    except Exception as ex:
        LOG.exception(ex)
        raise exception.ErrorOccurred(reason=_(
            "Cannot connect to mongos server.Check database settings in Credentials tab and try again"))


def getShards(conn):
    try:
        db = conn.config
        collection = db.shards
        shards = collection.find()
        return shards
    except Exception as e:
        LOG.error(
            'There was an error getting shards:' +
            str(e) +
            'Try again...')


class DisableProfiling(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword):
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)
        # Make sure profile is disabled, but also save current
        # profiling state in the flow record? so revert as well
        # as ResumeDB task sets the right profiling level
        LOG.debug(_('DisableProfiling:'))
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')

        for cfgsrv in cfgsrvs:
            cfghost = cfgsrv.split(':')[0]
            cfgport = cfgsrv.split(':')[1]
            try:
                self.cfgclient = connect_server(cfghost, int(cfgport),
                                                DBUser, DBPassword)
                proflevel = self.cfgclient.admin.profiling_level()
                # diable profiling
                self.cfgclient.admin.set_profiling_level(pymongo.OFF)
                return proflevel
            except BaseException:
                LOG.debug(_('"' + cfghost + '" appears to be offline'))
                pass

        LOG.error(_("Cannot find config server to disable profiling. \
                           Make sure your mongodb cluster is up and running"))
        raise Exception(_("Cannot find config server to disable profiling. \
                           Make sure your mongodb cluster is up and running"))

    def revert(self, *args, **kwargs):
        try:
            # Read profile level from the flow record?
            if not isinstance(kwargs['result'], misc.Failure):
                self.cfgclient.admin.set_profiling_level(kwargs['result'])
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass


class EnableProfiling(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword, proflevel):
        LOG.debug(_('EnableProfiling'))
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)

        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')

        for cfgsrv in cfgsrvs:
            cfghost = cfgsrv.split(':')[0]
            cfgport = cfgsrv.split(':')[1]
            try:
                self.cfgclient = connect_server(cfghost, int(cfgport),
                                                DBUser, DBPassword)
                # Read profile level from the flow record?
                self.cfgclient.admin.set_profiling_level(proflevel)
                return
            except BaseException:
                LOG.debug(_('"' + cfghost + '" appears to be offline'))
                pass

        LOG.error(_("Cannot enable profiling. \
                    Make sure your mongodb cluster is up and running"))
        raise Exception(_("Cannot enable profiling. \
                           Make sure your mongodb cluster is up and running"))


class PauseDBInstance(task.Task):

    def execute(self, h, DBUser, DBPassword):
        LOG.debug(_('PauseDBInstance'))
        # Flush the database and hold the write # lock the instance.
        host_info = h['secondaryReplica'].split(':')
        LOG.debug(_(host_info))
        self.client = connect_server(
            host_info[0], int(
                host_info[1]), DBUser, DBPassword)
        self.client.fsync(lock=True)

        # Add code to wait until the fsync operations is complete

    def revert(self, *args, **kwargs):
        try:
            # Resume DB
            if self.client.is_locked:
                self.client.unlock()
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass


class ResumeDBInstance(task.Task):

    def execute(self, h, DBUser, DBPassword):
        LOG.debug(_('ResumeDBInstance'))
        host_info = h['secondaryReplica'].split(':')
        LOG.debug(_(host_info))
        self.client = connect_server(
            host_info[0], int(
                host_info[1]), DBUser, DBPassword)
        self.client.unlock()


class PauseBalancer(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword):
        LOG.debug(_('PauseBalancer'))
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)

        # Pause the DB
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')

        for cfgsrv in cfgsrvs:
            cfghost = cfgsrv.split(':')[0]
            cfgport = cfgsrv.split(':')[1]
            try:
                self.client = connect_server(
                    cfghost, cfgport, DBUser, DBPassword)
                db = self.client.config

                timeout = settings.get_settings().get('mongodb_stop_balancer_timeout', '300')
                currtime = time.time()
                db.settings.update({'_id': 'balancer'}, {
                                   '$set': {'stopped': True}}, True);
                balancer_info = db.locks.find_one({'_id': 'balancer'})
                while int(str(balancer_info['state'])) > 0 and\
                        time.time() - currtime < timeout:
                    time.sleep(5)
                    LOG.debug(_('\t\twaiting for balancer to stop...'))
                    balancer_info = db.locks.find_one({'_id': 'balancer'})

                if int(str(balancer_info['state'])) > 0:
                    LOG.error(_("Cannot stop the balancer with in the \
                                mongodb_stop_balancer_timeout(%d) interval") %
                              mongodb_stop_balancer_timeout)
                    raise Exception(_("Cannot stop the balancer with in the \
                                mongodb_stop_balancer_timeout(%d) interval") %
                                    mongodb_stop_balancer_timeout)
                return
            except BaseException:
                LOG.debug(_('"' + cfghost + '" appears to be offline'))
                pass
        LOG.error(_("Cannot pause balancer. \
                    Make sure your mongodb cluster is up and running"))
        raise Exception(_("Cannot pause balancer. \
                           Make sure your mongodb cluster is up and running"))

    def revert(self, *args, **kwargs):
        try:
            # Resume DB
            db = self.client.config
            db.settings.update({'_id': 'balancer'}, {
                               '$set': {'stopped': False}}, True);
        except Exception as ex:
            LOG.exception(ex)
        finally:
            pass


class ResumeBalancer(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword):
        LOG.debug(_('ResumeBalancer'))
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)
        # Resume DB
        # Pause the DB
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')

        for cfgsrv in cfgsrvs:
            cfghost = cfgsrv.split(':')[0]
            cfgport = cfgsrv.split(':')[1]
            try:
                self.client = connect_server(
                    cfghost, cfgport, DBUser, DBPassword)

                db = self.client.config
                db.settings.update({'_id': 'balancer'}, {
                                   '$set': {'stopped': False}}, True);
                return
            except BaseException:
                LOG.debug(_('"' + cfghost + '" appears to be offline'))
                pass

        LOG.error(_("Cannot resume balancer. \
                    Make sure your mongodb cluster is up and running"))
        raise Exception(_("Cannot resume balancer. \
                           Make sure your mongodb cluster is up and running"))


class ShutdownConfigServer(task.Task):

    #
    # db.runCommand('getShardMap')
    #{
    #'map' : {
        #'node2:27021' : 'node2:27021',
        #'node3:27021' : 'node3:27021',
        #'node4:27021' : 'node4:27021',
        #'config' : 'node2:27019,node3:27019,node4:27019',
        #'shard0000' : 'node2:27021',
        #'shard0001' : 'node3:27021',
        #'shard0002' : 'node4:27021'
    #},
    #'ok' : 1
    #}
    #'''
    def execute(self, DBHost, DBPort, DBUser, DBPassword,
                HostUsername, HostPassword, HostSSHPort=22, RunAsRoot=False):
        # Get the list of config servers
        # shutdown one of them
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)

        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')

        for cfgsrv in cfgsrvs:
            cfghost = cfgsrv.split(':')[0]
            cfgport = cfgsrv.split(':')[1]
            try:
                self.cfgclient = connect_server(cfghost, int(cfgport),
                                                DBUser, DBPassword)

                cmdlineopts = self.cfgclient.admin.command('getCmdLineOpts')

                command = 'mongod --shutdown --port ' + cfgport + ' --configsvr'
                if RunAsRoot:
                    command = 'sudo ' + command

                LOG.debug(_('ShutdownConfigServer'))
                try:
                    client = paramiko.SSHClient()
                    client.load_system_host_keys()
                    if HostPassword == '':
                        client.set_missing_host_key_policy(
                            paramiko.WarningPolicy())
                    else:
                        client.set_missing_host_key_policy(
                            paramiko.AutoAddPolicy())
                    client.connect(
                        cfghost,
                        port=HostSSHPort,
                        username=HostUsername,
                        password=HostPassword,
                        timeout=120)

                    stdin, stdout, stderr = client.exec_command(
                        command, timeout=120)
                    LOG.debug(_(stdout.read()))
                finally:
                    client.close()

                # Also make sure the config server command line operations are
                # saved
                return cfgsrv, cmdlineopts
            except BaseException:
                LOG.debug(_('"' + cfghost + '" appears to be offline'))
                pass
        LOG.error(_("Cannot shutdown configsrv. \
                    Make sure your mongodb cluster is up and running"))
        raise Exception(_("Cannot shutdown configsrv. \
                           Make sure your mongodb cluster is up and running"))

        def revert(self, *args, **kwargs):
            client = None
            try:
                # Make sure all config servers are resumed
                cfghost = kwargs['result']['cfgsrv'].split(':')[0]

                # ssh into the cfg host and start the config server
                if not isinstance(kwargs['result'], misc.Failure):
                    port = kwargs['HostSSHPort']

                    command = ''
                    for c in kwargs['cfgsrvcmdline']['argv']:
                        command = command + c + ' '

                    client = paramiko.SSHClient()
                    client.load_system_host_keys()
                    if HostPassword == '':
                        client.set_missing_host_key_policy(
                            paramiko.WarningPolicy())
                    else:
                        client.set_missing_host_key_policy(
                            paramiko.AutoAddPolicy())
                    client.connect(
                        cfghost,
                        port=kwargs['HostSSHPort'],
                        username=kwargs['HostUsername'],
                        password=kwargs['HostPassword'],
                        timeout=120)

                    stdin, stdout, stderr = client.exec_command(
                        command, timeout=120)
                    LOG.debug(_(stdout.read()))

                LOG.debug(_('ShutdownConfigServer:revert'))

            except Exception as ex:
                LOG.exception(ex)
            finally:
                if client:
                    client.close()


class ResumeConfigServer(task.Task):

    def execute(self, cfgsrv, cfgsrvcmdline, HostUsername,
                HostPassword, HostSSHPort=22, RunAsRoot=False):
        # Make sure all config servers are resumed
        cfghost = cfgsrv.split(':')[0]
        port = 22

        command = ''
        for c in cfgsrvcmdline['argv']:
            command = command + c + ' '

        if RunAsRoot:
            command = 'sudo ' + command

        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if HostPassword == '':
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                cfghost,
                port=HostSSHPort,
                username=HostUsername,
                password=HostPassword,
                timeout=120)

            stdin, stdout, stderr = client.exec_command(command, timeout=120)
            LOG.debug(_(stdout.read()))
        finally:
            client.close()

        # ssh into the cfg host and start the config server
        LOG.debug(_('ResumeConfigServer'))

# Assume there is no ordering dependency between instances
# pause each VM in parallel.


def PauseDBInstances(hosts_list):
    flow = uf.Flow('PauseDBInstances')

    for index, h in enumerate(hosts_list):
        host_info = h['secondaryReplica'].split(':')
        flow.add(
            PauseDBInstance(
                'PauseDBInstance_' +
                h['secondaryReplica'],
                rebind=[
                    'secondary_' +
                    str(index),
                    'DBUser',
                    'DBPassword']))

    return flow


def ResumeDBInstances(hosts_list):
    flow = uf.Flow('ResumeDBInstances')

    for index, h in enumerate(hosts_list):
        host_info = h['secondaryReplica'].split(':')
        flow.add(
            ResumeDBInstance(
                'ResumeDBInstance_' +
                h['secondaryReplica'],
                rebind=[
                    'secondary_' +
                    str(index),
                    'DBUser',
                    'DBPassword']))

    return flow


def secondaryhosts_to_backup(
        cntx, host, port, username, password, preferredgroup):
    #
    # Creating connection to mongos server
    #
    LOG.debug(_('Connecting to mongos server ' + host))
    connection = connect_server(host, port, username, password)

    pgroup = []
    if preferredgroup:
        pgroup = json.loads(preferredgroup)

    #
    # Getting the secondaries list
    #
    hosts_to_backup = []
    if isShardedCluster(connection):
        #
        # Getting sharding information
        #
        LOG.debug(_('Getting sharding configuration'))
        shards = getShards(connection)

        for s in shards:
            hosts = str(s['host'])
            hosts = hosts.replace(str(s['_id']), '').strip()
            hosts = hosts.replace('/', '').strip()

            # print 'Getting secondary from hosts in ', hosts
            # Get the replica set for each shard
            if username != '':
                c = pymongo.MongoClient("mongodb://" + username + ":" +
                                        password + "@" + hosts,
                                        read_preference=ReadPreference.SECONDARY)
            else:
                c = pymongo.MongoClient(hosts,
                                        read_preference=ReadPreference.SECONDARY)

            status = c.admin.command('replSetGetStatus')

            # If user specified preferred group, backup only those
            # replicas
            if preferredgroup and len(pgroup) > 0:
                preferredreplica = None
                for member in pgroup:
                    if member['replica'] == status['set']:
                        preferredreplica = member['name']

                # Select a replica member only when user specifies a replica
                if preferredreplica:
                    for m in status['members']:
                        if m['name'] != preferredreplica:
                            continue
                        if m['stateStr'] == 'SECONDARY':
                            hosts_to_backup.append({'replicaSetName': status['set'],
                                                    'secondaryReplica': m['name']})
                        else:
                            LOG.error(_(preferredreplica + " state is " +
                                        m['stateStr'] +
                                        ". Will pick next secondary for backup"))
                            for m in status['members']:
                                if m['stateStr'] == 'SECONDARY':
                                    hosts_to_backup.append({'replicaSetName': status['set'],
                                                            'secondaryReplica': m['name']})
                                    break
                            break
            else:
                # if user did not specify preferred group, backup entire
                # cluster
                for m in status['members']:
                    if m['stateStr'] == 'SECONDARY':
                        hosts_to_backup.append({'replicaSetName': status['set'],
                                                'secondaryReplica': m['name']})
                        break
    else:
        status = connection.admin.command('replSetGetStatus')
        preferredreplica = None
        if preferredgroup and len(pgroup) > 0:
            for member in pgroup:
                if member['replica'] == status['set']:
                    preferredreplica = member['name']

        # Select a replica member only when user specifies a replica
        if preferredreplica:
            for m in status['members']:
                if m['name'] != preferredreplica:
                    continue
                if m['stateStr'] == 'SECONDARY':
                    hosts_to_backup.append({'replicaSetName': status['set'],
                                            'secondaryReplica': m['name']})
                else:
                    LOG.error(_(preferredreplica + " state is " +
                                m['stateStr'] +
                                ". Will pick next secondary for backup"))
                    for m in status['members']:
                        if m['stateStr'] == 'SECONDARY':
                            hosts_to_backup.append({'replicaSetName': status['set'],
                                                    'secondaryReplica': m['name']})
                            break
                break
        else:
            # if user did not specify preferred group, backup entire cluster
            for m in status['members']:
                if m['stateStr'] == 'SECONDARY':
                    hosts_to_backup.append({'replicaSetName': status['set'],
                                            'secondaryReplica': m['name']})
                    break

    if len(hosts_to_backup) == 0:
        raise Exception(_("Could not identify any hosts to backup. \
                           Please make sure mongodb cluster is in a stable \
                           and try again"))

    return hosts_to_backup


def get_vms(cntx, dbhost, dbport, mongodbusername,
            mongodbpassword, sshport,
            hostusername, hostpassword):
    #
    # Creating connection to mongos server
    #
    LOG.debug(_('Connecting to mongos server ' + dbhost))
    connection = connect_server(
        dbhost,
        dbport,
        mongodbusername,
        mongodbpassword)

    #
    # Getting sharding information
    #
    LOG.debug(_('Getting sharding configuration'))
    shards = getShards(connection)

    #
    # Getting the secondaries list
    #
    hostnames = {}

    # This is a sharded cluster
    if isShardedCluster(connection):
        for s in shards:
            hosts = str(s['host'])
            hosts = hosts.replace(str(s['_id']), '').strip()
            hosts = hosts.replace('/', '').strip()
            for h in hosts.split(','):
                hostname = h.split(':')[0]
                if not hostname in hostnames:
                    hostnames[hostname] = 1

        # Add config servers to the mix
        dbmap = connection.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')

        for cfgsrv in cfgsrvs:
            cfghost = cfgsrv.split(':')[0]
            cfgport = cfgsrv.split(':')[1]
            if not cfghost in hostnames:
                hostnames[cfghost] = 1

        if not dbhost in hostnames:
            hostnames[dbhost] = 1
    else:
        # this is a replica set
        status = connection.admin.command('replSetGetStatus')

        # If user specified preferred group, backup only those
        # replicas
        for m in status['members']:
            hostname = m['name'].split(":")[0]
            hostnames[hostname] = 1

    interfaces = {}
    for hostname in hostnames:
        try:
            mac_addresses = utils.get_mac_addresses(hostname, sshport,
                                                    username=hostusername,
                                                    password=hostpassword, timeout=120)
            for mac in mac_addresses:
                interfaces[mac.lower()] = hostname

        except Exception as ex:
            LOG.exception(ex)
            LOG.info(
                _('"' + hostname + '" appears to be offline. Cannot exec ifconfig'))

    if len(interfaces) == 0:
        LOG.info(
            _("Unabled to login to VMs to discover MAC Addresses. Please check username/passwor and try again."))
        raise Exception(
            _("Unabled to login to VMs to discover MAC Addresses. Please check username/passwor and try again."))

    # query VM by ethernet and get instance info here
    # call nova list
    compute_service = nova.API(production=True)
    instances = compute_service.get_servers(cntx, admin=True)
    vms = []

    # call nova interface-list <instanceid> to build the list of instances ids
    for instance in instances:
        # The following logic helps for VMware VMs. For OpenStack instances,
        # look at the instance interfaces.
        for addr in json.loads(instance.metadata['networks']):
            # IP Addresses
            # this is our vm
            if addr['macAddress'].lower() in interfaces:
                hypervisor_hostname = None
                hypervisor_type = "VMware vCenter Server"
                clustername = "Unknown"

                if 'cluster' in instance.metadata and instance.metadata['cluster']:
                    if json.loads(instance.metadata['cluster']):
                        clusprop = json.loads(instance.metadata['cluster'])[0]
                        clustername = clusprop['name']

                hypervisor_hostname = clustername
                utils.append_unique(vms, {'vm_id': instance.id,
                                          'vm_name': instance.name,
                                          'vm_metadata': instance.metadata,
                                          'vm_flavor_id': instance.flavor['id'],
                                          'hostname': interfaces[addr['macAddress'].lower()],
                                          'vm_power_state': instance.__dict__['OS-EXT-STS:power_state'],
                                          'hypervisor_hostname': hypervisor_hostname,
                                          'hypervisor_type': hypervisor_type},
                                    "vm_id")
                break

    if len(vms) == 0:
        LOG.info(
            _("No VMs are discovered in tvault inventory. Please run discover and try again"))
        raise Exception(
            _("No instances are discovered in tvault inventory. Please run discover and try again"))
    return vms


"""
MongoDBWorkflow Requires the following inputs in store:

    'connection': FLAGS.sql_connection,     # taskflow persistence connection
    'context': context_dict,                # context dictionary
    'snapshot': snapshot,                   # snapshot dictionary

    # Instanceids will to be discovered automatically
    'host': 'mongodb1',              # one of the nodes of mongodb cluster
    'port': 27017,                   # listening port of mongos service
    'username': 'ubuntu',            # mongodb admin user
    'password': 'ubuntu',            # mongodb admin password
    'hostusername': 'ubuntu',            # username on the host for ssh operations
    'hostpassword': '',              # username on the host for ssh operations
    'sshport' : 22,                  # ssh port that defaults to 22
    'usesudo' : True,                # use sudo when shutdown and restart of mongod instances
"""


class MongoDBWorkflow(workflow.Workflow):
    """
      MongoDB workflow
    """

    def __init__(self, name, store):
        super(MongoDBWorkflow, self).__init__(name)
        self._store = store

    def find_first_alive_node(self):
        # Iterate thru all hosts and pick the one that is alive
        if 'hostnames' in self._store:
            for host in [self._store['DBHost']] + \
                    json.loads(self._store['hostnames']):
                try:
                    connection = connect_server(host,
                                                int(self._store['DBPort']),
                                                self._store['DBUser'],
                                                self._store['DBPassword'])
                    self._store['DBHost'] = host
                    LOG.debug(_('Chose "' + host + '" for mongodb connection'))
                    return
                except BaseException:
                    LOG.debug(_('"' + host + '" appears to be offline'))
                    pass
        #LOG.warning(_( 'MongoDB cluster appears to be offline'))

    #
    # MongoDB flow is an directed acyclic flow.
    # :param host - One of the mongo db node in the cluster that has mongos
    #               service running and will be used to discover the mongo db
    #               shards, their replicas etc
    # : port - port at which mongos service is running
    # : usename/password - username and password to authenticate to the database
    #
    def initflow(self, composite=False):
        connection = connect_server(self._store['DBHost'], self._store['DBPort'],
                                    self._store['DBUser'], self._store['DBPassword'])
        isMongos = isShardedCluster(connection)
        self.find_first_alive_node()
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = get_vms(cntx, self._store['DBHost'],
                            self._store['DBPort'],
                            self._store['DBUser'],
                            self._store['DBPassword'],
                            self._store['HostSSHPort'],
                            self._store['HostUsername'],
                            self._store['HostPassword'])
        self._store['topology'] = self.topology()
        hosts_to_backup = secondaryhosts_to_backup(cntx,
                                                   self._store['DBHost'],
                                                   self._store['DBPort'],
                                                   self._store['DBUser'],
                                                   self._store['DBPassword'],
                                                   self._store['preferredgroup'])

        self._store['instances'] = []

        # Filter the VMs based on the preferred secondary replica
        for index, vm in enumerate(instances):
            for index, srep in enumerate(hosts_to_backup):
                if srep['secondaryReplica'].split(':')[0] == vm['hostname']:
                    self._store['instance_' + vm['vm_id']] = vm
                    self._store['instances'].append(vm)
                    break

        for index, item in enumerate(hosts_to_backup):
            self._store['secondary_' + str(index)] = item

        # Add config server if the server is not already part
        # of the instances
        if isMongos:
            dbmap = connection.admin.command('getShardMap')
            cfgsrvs = dbmap['map']['config'].split(',')

            cfgincluded = False
            for cfgsrv in cfgsrvs:
                cfghost = cfgsrv.split(':')[0]
                cfgport = cfgsrv.split(':')[1]
                for inst in self._store['instances']:
                    if inst['hostname'] == cfghost:
                        cfgincluded = True
                        break
                if cfgincluded:
                    break

            if not cfgincluded:
                cfgadded = False
                for index, vm in enumerate(instances):
                    for cfgsrv in cfgsrvs:
                        cfghost = cfgsrv.split(':')[0]
                        cfgport = cfgsrv.split(':')[1]
                        if cfghost == vm['hostname']:
                            self._store['instance_' + vm['vm_id']] = vm
                            self._store['instances'].append(vm)
                            cfgadded = True
                            break
                    if cfgadded:
                        break

        snapshotvms = lf.Flow('mongodbwf')

        # Add disable profile task. Stopping balancer fails if profile process
        # is running
        if isMongos:
            snapshotvms.add(
                DisableProfiling(
                    'DisableProfiling',
                    provides='proflevel'))
            snapshotvms.add(PauseBalancer('PauseBalancer'))

        # This will be a flow that needs to be added to mongo db flow.
        # This is a flow that pauses all related VMs in unordered pattern
        snapshotvms.add(PauseDBInstances(hosts_to_backup))

        if isMongos:
            snapshotvms.add(
                ShutdownConfigServer(
                    'ShutdownConfigServer',
                    provides=(
                        'cfgsrv',
                        'cfgsrvcmdline')))

        # This is an unordered pausing of VMs. This flow is created in
        # common tasks library. This routine takes instance ids from
        # openstack. Workload manager should provide the list of
        # instance ids
        snapshotvms.add(vmtasks.UnorderedPauseVMs(self._store['instances']))

        # This is again unorder snapshot of VMs. This flow is implemented in
        # common tasks library
        snapshotvms.add(vmtasks.UnorderedSnapshotVMs(self._store['instances']))

        # This is an unordered pausing of VMs.
        snapshotvms.add(vmtasks.UnorderedUnPauseVMs(self._store['instances']))

        # Restart the config servers so metadata changes can happen
        if isMongos:
            snapshotvms.add(ResumeConfigServer('ResumeConfigServer'))

        # unlock all locekd replicas so it starts receiving all updates from primary and
        # will eventually get into sync with primary
        snapshotvms.add(ResumeDBInstances(hosts_to_backup))

        if isMongos:
            snapshotvms.add(ResumeBalancer('ResumeBalancer'))
            # enable profiling to the level before the flow started
            snapshotvms.add(EnableProfiling('EnableProfiling'))

        super(MongoDBWorkflow, self).initflow(snapshotvms, composite=composite)

    def get_databases(self):
        LOG.info(_('Enter get_databases'))
        outfile_path = ''
        errfile_path = ''
        try:
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            db = WorkloadMgrDB().db
            if 'snapshot' in self._store:
                db.snapshot_update(cntx, self._store['snapshot']['id'],
                                   {'progress_msg': 'Discovering MongoDB Databases'})

            fh, outfile_path = mkstemp()
            os.close(fh)
            fh, errfile_path = mkstemp()
            os.close(fh)

            cmdspec = ["python", "/opt/stack/workloadmgr/workloadmgr/workflows/mongodbnodes.py",
                       "--config-file", "/etc/workloadmgr/workloadmgr.conf",
                       "--defaultnode", self._store['DBHost'],
                       "--port", self._store['HostSSHPort'],
                       "--username", self._store['HostUsername'],
                       "--password", "******",
                       "--dbport", self._store["DBPort"],
                       "--dbuser", self._store["DBUser"],
                       "--dbpassword", self._store["DBPassword"], ]

            if self._store.get('hostnames', None):
                hosts = ""
                for host in json.loads(self._store.get('hostnames', "")):
                    hosts += host + ';'

                cmdspec.extend(["--addlnodes", hosts])
            cmdspec.extend(["--outfile", outfile_path,
                            "--errfile", errfile_path,
                            ])
            cmd = " ".join(cmdspec)
            for idx, opt in enumerate(cmdspec):
                if opt == "--password":
                    cmdspec[idx + 1] = self._store['HostPassword']
                    break

            LOG.debug(_('Executing: ' + " ".join(cmdspec)))
            process = subprocess.Popen(cmdspec, shell=False)
            stdoutdata, stderrdata = process.communicate()
            if process.returncode != 0:
                reason = 'Error discovering MongoDB Databases'
                try:
                    with open(errfile_path, 'r') as fh:
                        reason = fh.read()
                        if len(reason) == 0:
                            reason = 'Error discovering MongoDB Databases'
                        LOG.info(
                            _('Error discovering MongoDB Databases: ' + reason))
                    os.remove(errfile_path)
                finally:
                    raise exception.ErrorOccurred(reason=reason)

            databases = None
            with open(outfile_path, 'r') as fh:
                databases = json.loads(fh.read())
                LOG.info(_('Discovered MongoDB Databases: ' + str(databases)))

            return databases

        finally:
            if os.path.isfile(outfile_path):
                os.remove(outfile_path)
            if os.path.isfile(errfile_path):
                os.remove(errfile_path)
            LOG.info(_('Exit get_databases'))

    def topology(self):
        # Discover the shards
        # Discover the replicaset of each shard
        # since mongodb supports javascript and json
        # this implementation should be pretty
        # straight forward

        # discover the number of VMs part of this flow
        # This usually boils down to number of shards of the cluster
        #
        # Creating connection to mongos server
        #
        self.find_first_alive_node()
        LOG.debug(_('Connecting to mongos server ' + self._store['DBHost']))
        connection = connect_server(
            self._store['DBHost'],
            self._store['DBPort'],
            self._store['DBUser'],
            self._store['DBPassword'])

        replicas = []
        replicahosts = {}
        if isShardedCluster(connection):
            #
            # Getting sharding information
            #
            LOG.debug(_('Getting sharding configuration'))
            shards = getShards(connection)

            # Get the replica set for each shard
            for s in shards:
                hosts = str(s['host'])
                hosts = hosts.replace(str(s['_id']), '').strip()
                hosts = hosts.replace('/', '').strip()
                replicahosts[s['_id']] = hosts
        else:
            # Get the replica set for each shard
            status = connection.admin.command('replSetGetStatus')
            s = []
            for m in status['members']:
                s.append(m['name'])
            replicahosts[status['set']] = ",".join(s)

        for replica, hosts in replicahosts.iteritems():
            LOG.debug(_('Getting secondary from hosts in ' + hosts +
                        " for replica " + replica))
            if self._store['DBUser'] != '':
                repl = pymongo.MongoClient("mongodb://" + self._store['DBUser'] + ":" +
                                           self._store['DBPassword'] +
                                           "@" + hosts,
                                           read_preference=ReadPreference.SECONDARY)
            else:
                repl = pymongo.MongoClient(hosts,
                                           read_preference=ReadPreference.SECONDARY)
            status = repl.admin.command('replSetGetStatus')

            replstatus = {}
            replstatus["date"] = str(status["date"])
            replstatus["children"] = []
            replstatus["name"] = status.pop("set")
            replstatus["status"] = "OK:" + str(status["ok"])
            replstatus["input"] = []
            replstatus["input"].append([])
            replstatus["input"][0].append("myState")
            replstatus["input"][0].append(status["myState"])
            replstatus['children'] = []
            for m in status["members"]:
                replchild = {}
                replchild['name'] = m['name']
                replchild['configVersion'] = m['configVersion']
                replchild["optimeDate"] = m["optimeDate"].strftime("%B %d, %Y")
                replchild["status"] = m.pop("stateStr")
                replchild["uptime"] = m.pop("uptime")
                if ('electionDate' in m):
                    m.pop('electionDate')
                if ('electionTime' in m):
                    m.pop('electionTime')
                if ("lastHeartbeatRecv" in m):
                    replchild["lastHeartbeatRecv"] = str(
                        m["lastHeartbeatRecv"])
                if ("lastHeartbeat" in m):
                    replchild["lastHeartbeat"] = str(m["lastHeartbeat"])
                if ("optime" in m):
                    replchild["optime"] = m['optime'].as_datetime(
                    ).strftime("%B %d, %Y")
                replchild["input"] = []
                replchild["input"].append([])
                replchild["input"].append([])
                replchild["input"].append([])
                if ("syncingTo" in m):
                    replchild["input"][0].append("syncingTo")
                    replchild["input"][0].append(m["syncingTo"])
                replchild["input"][1].append("state")
                replchild["input"][1].append(m["state"])
                replchild["input"][2].append("health")
                replchild["input"][2].append(m["health"])
                replstatus['children'].append(replchild)
            replicas.append(replstatus)

        # Covert the topology into generic topology that can be
        # returned as restful payload
        mongodb = {"name": "MongoDB", "children": replicas, "input": []}
        return dict(topology=mongodb,
                    databases=self.get_databases()['databases'])

    def details(self):
        # workflow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            if isinstance(item, task.Task):
                taskdetails = {
                    'name': item._name.split("_")[0],
                    'type': 'Task'}
                taskdetails['input'] = []
                if len(item._name.split('_')) == 2:
                    nodename = item._name.split("_")[1]
                    for n in nodes['instances']:
                        if n['vm_id'] == nodename:
                            nodename = n['vm_name']
                    taskdetails['input'] = [['vm', nodename]]
                return taskdetails

            flowdetails = {}
            flowdetails['name'] = str(item).split("==")[0]
            flowdetails['type'] = str(item).split('.')[2]
            flowdetails['children'] = []
            for it in item:
                flowdetails['children'].append(recurseflow(it))

            return flowdetails

        nodes = self.discover()
        workflow = recurseflow(self._flow)
        return dict(workflow=workflow)

    def discover(self):
        self.find_first_alive_node()
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = get_vms(cntx, self._store['DBHost'],
                            self._store['DBPort'], self._store['DBUser'],
                            self._store['DBPassword'],
                            self._store['HostSSHPort'],
                            self._store['HostUsername'],
                            self._store['HostPassword'])
        for instance in instances:
            del instance['hypervisor_hostname']
            del instance['hypervisor_type']
        return dict(instances=instances, topology=self.topology())

    def execute(self):
        if self._store['source_platform'] == "vmware":
            compute_service = nova.API(production=True)
            search_opts = {}
            search_opts['deep_discover'] = '1'
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            compute_service.get_servers(cntx, search_opts=search_opts)
        self.find_first_alive_node()
        vmtasks.CreateVMSnapshotDBEntries(
            self._store['context'],
            self._store['instances'],
            self._store['snapshot'])
        result = engines.run(
            self._flow,
            engine_conf='parallel',
            backend={
                'connection': self._store['connection']},
            store=self._store)

        # workloadmgr --os-auth-url http://$KEYSTONE_AUTH_HOST:5000/v2.0
        # --os-tenant-name admin --os-username admin --os-password
        # $ADMIN_PASSWORD workload-type-create --metadata HostUsername=string
        # --metadata HostPassword=password --metadata HostSSHPort=string
        # --metadata DBHost=string --metadata DBPort=string --metadata
        # DBUser=string --metadata DBPassword=password --metadata
        # RunAsRoot=boolean --metadata capabilities='discover:topology'
        # --display-name "MongoDB" --display-description "MongoDB workload
        # description" --is-public True


"""
#test code
import json

#MongoDBWorkflow Requires the following inputs in store:

store = {
    'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8',
    #'context': context_dict,                # context dictionary
    #'snapshot': snapshot,                   # snapshot dictionary

    # Instanceids will to be discovered automatically
    'host': 'mongodb1',              # one of the nodes of mongodb cluster
    'port': 27017,                   # listening port of mongos service
    'username': 'ubuntu',            # mongodb admin user
    'password': 'ubuntu',            # mongodb admin password
    'hostusername': 'ubuntu',            # username on the host for ssh operations
    'hostpassword': '',              # username on the host for ssh operations
    'sshport' : 22,                  # ssh port that defaults to 22
    'usesudo' : True,                # use sudo when shutdown and restart of mongod instances
}

c = nova.novaclient(None, production=True, admin=True);
context = context.RequestContext("fc5e4f521b6a464ca401c456d59a3f61",
                                 c.client.projectid,
                                 is_admin = True,
                                 auth_token=c.client.auth_token)
store["context"] = context.__dict__
mwf = MongoDBWorkflow("testflow", context)
print json.dumps(mwf.details())
print json.dumps(mwf.discover())
print json.dumps(mwf.topology())

result = engines.load(mwf._flow, engine_conf='parallel', backend={'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8'}, store=store)

print mwf.execute()
"""
