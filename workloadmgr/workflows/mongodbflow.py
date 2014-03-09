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

import datetime 
import paramiko
import uuid

from taskflow import engines
from taskflow.utils import misc
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import graph_flow as gf
from taskflow import task
from taskflow import flow
from taskflow.utils import reflection

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp

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
        if user!='':
            auth = 'mongodb://' + user + ':' + password + '@' + host + ':' + str(port)
            connection = MongoClient(auth)
        else:
            auth=''
            connection = MongoClient(host,port)

        if verbose:
            print 'Connected to ', host, ' on port ',port, '...'

    except Exception, e:
        print 'Oops!  There was an error.  Try again...'
        print  e
        #raise e
    return connection

def getShards(conn):
    try:
        db = conn.config
        collection = db.shards
        shards = collection.find()
        return shards
    except Exception, e:
        print '\tOops!  There was an error.  Try again...'
        print '\t',e

class DisableProfiling(task.Task):

    def execute(self, host, port, username, password):
        self.client = connect_server(host, port, username, password)
        # Make sure profile is disabled, but also save current
        # profiling state in the flow record? so revert as well
        # as ResumeDB task sets the right profiling level
        print 'DisableProfiling:'
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')
        
        cfghost = cfgsrvs[0].split(':')[0]
        cfgport = cfgsrvs[0].split(':')[1]
        self.cfgclient = connect_server(cfghost, int(cfgport), username, password)
        
        proflevel = self.cfgclient.admin.profiling_level()
        
        # diable profiling
        self.cfgclient.admin.set_profiling_level(pymongo.OFF)
        return proflevel

    def revert(self, *args, **kwargs):
        # Read profile level from the flow record?
        if not isinstance(kwargs['result'], misc.Failure):
            self.cfgclient.admin.set_profiling_level(kwargs['result'])

class EnableProfiling(task.Task):

    def execute(self, host, port, username, password, proflevel):
        print 'EnableProfiling'
        self.client = connect_server(host, port, username, password)
    
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')
    
        cfghost = cfgsrvs[0].split(':')[0]
        cfgport = cfgsrvs[0].split(':')[1]
        self.cfgclient = connect_server(cfghost, int(cfgport), username, password)
    
        # Read profile level from the flow record?
        self.cfgclient.admin.set_profiling_level(proflevel)


class PauseDBInstance(task.Task):

    def execute(self, h, username, password):
        print 'PauseDBInstance'
        # Flush the database and hold the write # lock the instance.
        host_info = h['secondaryReplica'].split(':')
        print host_info
        self.client = connect_server(host_info[0], int(host_info[1]), '', '')
        self.client.fsync(lock = True)
    
        # Add code to wait until the fsync operations is complete
    
    def revert(self, *args, **kwargs):
        # Resume DB
        self.client.unlock()


class ResumeDBInstance(task.Task):

    def execute(self, h, username, password):
        print 'ResumeDBInstance'
        host_info = h['secondaryReplica'].split(':')
        print host_info
        self.client = connect_server(host_info[0], int(host_info[1]), '', '')
        self.client.unlock()

class PauseBalancer(task.Task):

    def execute(self, host, port, username, password):
        print 'PauseBalancer'
        self.client = connect_server(host, port, username, password)
        # Pause the DB
        db = self.client.config
    
        db.settings.update({'_id': 'balancer'}, {'$set': {'stopped': True}}, true);
        balancer_info = db.locks.find_one({'_id': 'balancer'})
        while int(str(balancer_info['state'])) > 0:
            print '\t\twaiting for migration'
            balancer_info = db.locks.find_one({'_id': 'balancer'})
    
    def revert(self, *args, **kwargs):
        # Resume DB
        db = self.client.config
        db.settings.update({'_id': 'balancer'}, {'$set': {'stopped': False}});

class ResumeBalancer(task.Task):

    def execute(self, host, port, username, password):
        print 'ResumeBalancer'
        self.client = connect_server(host, port, username, password)
        # Resume DB
    
        db = self.client.config
        db.settings.update({'_id': 'balancer'}, {'$set': {'stopped': False}});

class ShutdownConfigServer(task.Task):

    #
    #db.runCommand('getShardMap')
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
    def execute(self, host, port, username, password, hostuser, hostpassword, sshport=22, usesudo=False):
        # Get the list of config servers 
        # shutdown one of them
        self.client = connect_server(host, port, username, password)
        
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')
        
        cfghost = cfgsrvs[0].split(':')[0]
        cfgport = cfgsrvs[0].split(':')[1]
        self.cfgclient = connect_server(cfghost, int(cfgport), username, password)
        
        cmdlineopts = self.cfgclient.admin.command('getCmdLineOpts')
        
        command = 'mongod --shutdown --port ' + cfgport + ' --configsvr'
        if usesudo:
            command = 'sudo ' + command
        
        print 'ShutdownConfigServer'
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.WarningPolicy)
            client.connect(cfghost, port=sshport, username=hostuser, password=hostpassword)
            
            stdin, stdout, stderr = client.exec_command(command)
            print stdout.read(),
        finally:
            client.close()
    
        # Also make sure the config server command line operations are saved
        return cfgsrvs[0], cmdlineopts

        def revoke(self, *args, **kwargs):
            # Make sure all config servers are resumed
            import pdb;pdb.set_trace()
            cfghost = kwargs['result']['cfgsrv'].split(':')[0]
            
            #ssh into the cfg host and start the config server
            if not isinstance(kwargs['result'], misc.Failure):
                port = kwargs['sshport']
                
                command = ''
                for c in cfgsrvcmdline['argv']:
                    command  = command + c + ' '
                
                try:
                    client = paramiko.SSHClient()
                    client.load_system_host_keys()
                    client.set_missing_host_key_policy(paramiko.WarningPolicy)
                    client.connect(cfghost, port=port, username=kwargs['hostuser'], password=kwargs['hostpassword'])
                
                    stdin, stdout, stderr = client.exec_command(command)
                    print stdout.read(),
                finally:
                    client.close()
            
            print 'ShutdownConfigServer:revert'

class ResumeConfigServer(task.Task):

    def execute(self, cfgsrv, cfgsrvcmdline, hostuser, hostpassword, sshport=22, usesudo=False):
        # Make sure all config servers are resumed
        cfghost = cfgsrv.split(':')[0]
        port = 22
    
        command = ''
        for c in cfgsrvcmdline['argv']:
            command  = command + c + ' '
    
        if usesudo:
            command = 'sudo ' + command
    
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.WarningPolicy)
            client.connect(cfghost, port=sshport, username=hostuser, password=hostpassword)
    
            stdin, stdout, stderr = client.exec_command(command)
            print stdout.read(),
        finally:
            client.close()
    
        #ssh into the cfg host and start the config server
        print 'ResumeConfigServer'

# Assume there is no ordering dependency between instances
# pause each VM in parallel.
def PauseDBInstances(hosts_list):
    flow = uf.Flow('PauseDBInstances')
 
    for index, h in enumerate(hosts_list):
        host_info = h['secondaryReplica'].split(':')
        flow.add(PauseDBInstance('PauseDBInstance' + h['secondaryReplica'], rebind=['secondary_' + str(index), 'username', 'password']))

    return flow

def ResumeDBInstances(hosts_list):
    flow = uf.Flow('ResumeDBInstances')
 
    for index, h in enumerate(hosts_list):
        host_info = h['secondaryReplica'].split(':')
        flow.add(ResumeDBInstance('ResumeDBInstance' + h['secondaryReplica'], rebind=['secondary_' + str(index), 'username', 'password']))

    return flow

def secondaryhosts_to_backup(cntx, host, port, username, password):
    #
    # Creating connection to mongos server
    #
    print 'Connecting to mongos server ', host
    connection = connect_server(host, port, username, password)
    print ''

    #
    # Getting sharding information
    #
    print 'Getting sharding configuration'
    shards = getShards(connection)
    print ''

    #
    # Getting the secondaries list
    #
    hosts_to_backup = []
    for s in shards:
        hosts = str(s['host'])
        hosts = hosts.replace(str(s['_id']), '').strip()
        hosts = hosts.replace('/', '').strip()
        #print 'Getting secondary from hosts in ', hosts
        # Get the replica set for each shard
        c = MongoClient(hosts,
                    read_preference=ReadPreference.SECONDARY)
        status = c.admin.command('replSetGetStatus')
        hosts_list = []
        for m in status['members']:
            if m['stateStr'] == 'SECONDARY':
                hosts_to_backup.append({'replicaSetName': status['set'], 'secondaryReplica': m['name']})
                break

    return hosts_to_backup

def get_vms(cntx, host, port, username, password):
    #
    # Creating connection to mongos server
    #
    print 'Connecting to mongos server ', host
    connection = connect_server(host, port, username, password)
    print ''

    #
    # Getting sharding information
    #
    print 'Getting sharding configuration'
    shards = getShards(connection)
    print ''

    #
    # Getting the secondaries list
    #
    hostnames = {}
    for s in shards:
        hosts = str(s['host'])
        hosts = hosts.replace(str(s['_id']), '').strip()
        hosts = hosts.replace('/', '').strip()
        for h in hosts.split(','):
            hostname = h.split(':')[0]
            if not hostname in hostnames:
                hostnames[hostname] = 1
    
    interfaces = {}
    for hostname in hostnames:
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.WarningPolicy)
            client.connect(hostname, port=22, username='ubuntu', password='')
            stdin, stdout, stderr = client.exec_command('ifconfig eth0 | grep HWaddr')
            interfaces[stdout.read().split('HWaddr')[1].strip()] = hostname
        finally:
            client.close()


    # query VM by ethernet and get instance info here
    # call nova list
    compute_service = nova.API(production=True)
    instances = compute_service.get_servers(cntx, admin=True)
    hypervisors = compute_service.get_hypervisors(cntx)

    vms = []
    # call nova interface-list <instanceid> to build the list of instances ids
    for instance in instances:
        ifs = instance.addresses
        for addr in instance.addresses:
            ifs = instance.addresses[addr]
            for _if in ifs:
                if _if['OS-EXT-IPS-MAC:mac_addr'] in interfaces:
                    #this is our vm
                    hypervisor_hostname = None
                    hypervisor_type = None
                    for hypervisor in hypervisors:
                        if hypervisor.hypervisor_hostname == instance.__dict__['OS-EXT-SRV-ATTR:host']:
                            hypervisor_hostname = hypervisor.hypervisor_hostname
                            hypervisor_type = hypervisor_type
                            break
                   
                    vm = {'vm_id' : instance.id,
                          'vm_name' : instance.name,
                          'vm_flavor_id' : instance.flavor['id'],
                          'hypervisor_hostname' : hypervisor_hostname,
                          'hypervisor_type' :  hypervisor_type}
                    vms.append(vm)
    return vms

#
# MongoDB flow is an directed acyclic flow. 
# :param host - One of the mongo db node in the cluster that has mongos 
#               service running and will be used to discover the mongo db
#               shards, their replicas etc
# : port - port at which mongos service is running
# : usename/password - username and password to authenticate to the database
#
                 
def InitFlow(store):
    
    cntx = amqp.RpcContext.from_dict(store['context'])
    host = store['host']
    port = store['port']
    username = store['username']
    password = store['password']
    
    
    store['instances'] =  get_vms(cntx, host, port, username, password)
    hosts_to_backup = secondaryhosts_to_backup(cntx, host, port, username, password)
    for index,item in enumerate(store['instances']):
        store['instance_'+str(index)] = item
    for index, item in enumerate(hosts_to_backup):
        store['secondary_'+str(index)] = item
    
    flow = lf.Flow('mongodbwf')
    
    #create an entry for the VM in the workloadmgr database
    flow.add(vmtasks.CreateVMSnapshotDBEntries("CreateVMSnapshotDBEntries_" + store['snapshot']['id']))
    
    #create a network snapshot
    flow.add(vmtasks.SnapshotVMNetworks("SnapshotVMNetworks" + store['snapshot']['id']))
    
    #snapshot flavors of VMs
    flow.add(vmtasks.SnapshotVMFlavors("SnapshotVMFlavors" + store['snapshot']['id']))    

    # Add disable profile task. Stopping balancer fails if profile process
    # is running
    flow.add(DisableProfiling('DisableProfiling', provides='proflevel'))

    # This will be a flow that needs to be added to mongo db flow.
    # This is a flow that pauses all related VMs in unordered pattern
    flow.add(PauseDBInstances(hosts_to_backup))

    flow.add(ShutdownConfigServer('ShutdownConfigServer', provides=('cfgsrv', 'cfgsrvcmdline')))

    # This is an unordered pausing of VMs. This flow is created in
    # common tasks library. This routine takes instance ids from 
    # openstack. Workload manager should provide the list of 
    # instance ids
    flow.add(vmtasks.UnorderedPauseVMs(store['instances']))

    # This is again unorder snapshot of VMs. This flow is implemented in
    # common tasks library
    flow.add(vmtasks.UnorderedSnapshotVMs(store['instances']))

    flow.add(vmtasks.UnorderedResumeVMs(store['instances']))

    # Restart the config servers so metadata changes can happen
    flow.add(ResumeConfigServer('ResumeConfigServer'))

    # unlock all locekd replicas so it starts receiving all updates from primary and
    # will eventually get into sync with primary
    flow.add(ResumeDBInstances(hosts_to_backup))

    # enable profiling to the level before the flow started
    flow.add(EnableProfiling('EnableProfiling'))

    # Now lazily copy the snapshots of VMs to tvault appliance
    flow.add(vmtasks.UnorderedUploadSnapshots(store['instances']))

    # block commit any changes back to the snapshot
    flow.add(vmtasks.UnorderedBlockCommit(store['instances']))

    return flow

'''
MongoDBWorkflow Requires the following inputs in store:

    'connection': FLAGS.sql_connection,     # taskflow persistence connection
    'context': context_dict,                # context dictionary
    'snapshot': snapshot,                   # snapshot dictionary
                    
    # Instanceids will to be discovered automatically
    'host': 'mongodb1',              # one of the nodes of mongodb cluster
    'port': 27017,                   # listening port of mongos service
    'username': 'ubuntu',            # mongodb admin user
    'password': 'ubuntu',            # mongodb admin password
    'hostuser': 'ubuntu',            # username on the host for ssh operations
    'hostpassword': '',              # username on the host for ssh operations
    'sshport' : 22,                  # ssh port that defaults to 22
    'usesudo' : True,                # use sudo when shutdown and restart of mongod instances
'''

class MongoDBWorkflow(workflow.Workflow):
    """
      MongoDB workflow
    """

    def __init__(self, name, store):
        super(MongoDBWorkflow, self).__init__(name)
        # Provide the initial variable inputs from the mysql database
        #
        self._store = store
        self._flow = InitFlow(self._store)

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
        print 'Connecting to mongos server ', store['host']
        connection = connect_server(self._store['host'], self._store['port'], self._store['username'], self._store['password'])
        print ''

        #
        # Getting sharding information
        #
        print 'Getting sharding configuration'
        shards = getShards(connection)
        print ''

        # Get the replica set for each shard
        replicas = []
        for s in shards:
            hosts = str(s['host'])
            hosts = hosts.replace(str(s['_id']), '').strip()
            hosts = hosts.replace('/', '').strip()
            print 'Getting secondary from hosts in ', hosts
            # Get the replica set for each shard
            c = MongoClient(hosts,
                        read_preference=ReadPreference.SECONDARY)
            status = c.admin.command('replSetGetStatus')
            c = MongoClient(hosts,
                        read_preference=ReadPreference.SECONDARY)
            status = c.admin.command('replSetGetStatus')
            replicas.append(status)

        # Covert the topology into generic topology that can be 
        # returned as restful payload
        return replicas

    def details(self):
        # Details the flow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            
            if isinstance(item, task.Task):
                return [{'name':str(item), 'type':'Task'}]

            flowdetails = {}
            flowdetails['name'] = str(item)
            flowdetails['type'] = item.__class__.__name__
            flowdetails['children'] = []
            for it in item:
                flowdetails['children'].append(recurseflow(it))

            return flowdetails

        return recurseflow(self._flow)

    def discover(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        return get_vms(cntx, self._store['host'], self._store['port'], self._store['username'], self._store['password'])

    def execute(self):
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)


'''
#test code
c = nova.novaclient(None, production=True, admin=True);
context = context.RequestContext('fc5e4f521b6a464ca401c456d59a3f61',
                                 c.client.projectid,
                                 is_admin = True,
                                 auth_token=c.client.auth_token)
mwf = MongoDBWorkflow('testflow', context, store)
import pdb;pdb.set_trace()
print mwf.details()
print mwf.discover()
print mwf.topology()
#print mwf.execute()
'''
