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
from workloadmgr import utils

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
            connection = MongoClient(host,int(port))

        if verbose:
            LOG.debug(_('Connected to ' + host +  ' on port ' + port +  '...'))

    except Exception, e:
        LOG.error(_('Oops!  There was an error.  Try again...'))
        LOG.error(_(e))
        raise e
    return connection

def getShards(conn):
    try:
        db = conn.config
        collection = db.shards
        shards = collection.find()
        return shards
    except Exception, e:
        LOG.error('There was an error getting shards:' + str(e) + 'Try again...')

class DisableProfiling(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword):
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)
        # Make sure profile is disabled, but also save current
        # profiling state in the flow record? so revert as well
        # as ResumeDB task sets the right profiling level
        LOG.debug(_('DisableProfiling:'))
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')
        
        cfghost = cfgsrvs[0].split(':')[0]
        cfgport = cfgsrvs[0].split(':')[1]
        self.cfgclient = connect_server(cfghost, int(cfgport), DBUser, DBPassword)
        
        proflevel = self.cfgclient.admin.profiling_level()
        
        # diable profiling
        self.cfgclient.admin.set_profiling_level(pymongo.OFF)
        return proflevel

    def revert(self, *args, **kwargs):
        # Read profile level from the flow record?
        if not isinstance(kwargs['result'], misc.Failure):
            self.cfgclient.admin.set_profiling_level(kwargs['result'])

class EnableProfiling(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword, proflevel):
        LOG.debug(_('EnableProfiling'))
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)
    
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')
    
        cfghost = cfgsrvs[0].split(':')[0]
        cfgport = cfgsrvs[0].split(':')[1]
        self.cfgclient = connect_server(cfghost, int(cfgport), DBUser, DBPassword)
    
        # Read profile level from the flow record?
        self.cfgclient.admin.set_profiling_level(proflevel)


class PauseDBInstance(task.Task):

    def execute(self, h, DBUser, DBPassword):
        LOG.debug(_('PauseDBInstance'))
        # Flush the database and hold the write # lock the instance.
        host_info = h['secondaryReplica'].split(':')
        LOG.debug(_(host_info))
        self.client = connect_server(host_info[0], int(host_info[1]), '', '')
        self.client.fsync(lock = True)
    
        # Add code to wait until the fsync operations is complete
    
    def revert(self, *args, **kwargs):
        # Resume DB
        if self.client.is_locked:
            self.client.unlock()


class ResumeDBInstance(task.Task):

    def execute(self, h, DBUser, DBPassword):
        LOG.debug(_('ResumeDBInstance'))
        host_info = h['secondaryReplica'].split(':')
        LOG.debug(_(host_info))
        self.client = connect_server(host_info[0], int(host_info[1]), '', '')
        self.client.unlock()

class PauseBalancer(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword):
        LOG.debug(_('PauseBalancer'))
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)
        # Pause the DB
        db = self.client.config
    
        db.settings.update({'_id': 'balancer'}, {'$set': {'stopped': True}}, true);
        balancer_info = db.locks.find_one({'_id': 'balancer'})
        while int(str(balancer_info['state'])) > 0:
            LOG.debug(_('\t\twaiting for migration'))
            balancer_info = db.locks.find_one({'_id': 'balancer'})
    
    def revert(self, *args, **kwargs):
        # Resume DB
        db = self.client.config
        db.settings.update({'_id': 'balancer'}, {'$set': {'stopped': False}});

class ResumeBalancer(task.Task):

    def execute(self, DBHost, DBPort, DBUser, DBPassword):
        LOG.debug(_('ResumeBalancer'))
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)
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
    def execute(self, DBHost, DBPort, DBUser, DBPassword, HostUsername, HostPassword, HostSSHPort=22, RunAsRoot=False):
        # Get the list of config servers 
        # shutdown one of them
        self.client = connect_server(DBHost, DBPort, DBUser, DBPassword)
        
        dbmap = self.client.admin.command('getShardMap')
        cfgsrvs = dbmap['map']['config'].split(',')
        
        cfghost = cfgsrvs[0].split(':')[0]
        cfgport = cfgsrvs[0].split(':')[1]
        self.cfgclient = connect_server(cfghost, int(cfgport), DBUser, DBPassword)
        
        cmdlineopts = self.cfgclient.admin.command('getCmdLineOpts')
        
        command = 'mongod --shutdown --port ' + cfgport + ' --configsvr'
        if RunAsRoot:
            command = 'sudo ' + command
        
        LOG.debug(_('ShutdownConfigServer'))
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if HostPassword == '':
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(cfghost, port=HostSSHPort, username=HostUsername, password=HostPassword)
            
            stdin, stdout, stderr = client.exec_command(command)
            LOG.debug(_(stdout.read()))
        finally:
            client.close()
    
        # Also make sure the config server command line operations are saved
        return cfgsrvs[0], cmdlineopts

        def revoke(self, *args, **kwargs):
            # Make sure all config servers are resumed
            cfghost = kwargs['result']['cfgsrv'].split(':')[0]
            
            #ssh into the cfg host and start the config server
            if not isinstance(kwargs['result'], misc.Failure):
                port = kwargs['HostSSHPort']
                
                command = ''
                for c in cfgsrvcmdline['argv']:
                    command  = command + c + ' '
                
                try:
                    client = paramiko.SSHClient()
                    client.load_system_host_keys()
                    if HostPassword == '':
                        client.set_missing_host_key_policy(paramiko.WarningPolicy())
                    else:
                        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(cfghost, port=kwargs['HostSSHPort'], username=kwargs['HostUsername'], password=kwargs['HostPassword'])
                
                    stdin, stdout, stderr = client.exec_command(command)
                    LOG.debug(_(stdout.read()))
                finally:
                    client.close()
            
            LOG.debug(_('ShutdownConfigServer:revert'))

class ResumeConfigServer(task.Task):

    def execute(self, cfgsrv, cfgsrvcmdline, HostUsername, HostPassword, HostSSHPort=22, RunAsRoot=False):
        # Make sure all config servers are resumed
        cfghost = cfgsrv.split(':')[0]
        port = 22
    
        command = ''
        for c in cfgsrvcmdline['argv']:
            command  = command + c + ' '
    
        if RunAsRoot:
            command = 'sudo ' + command
    
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if HostPassword == '':
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(cfghost, port=HostSSHPort, username=HostUsername, password=HostPassword)
    
            stdin, stdout, stderr = client.exec_command(command)
            LOG.debug(_(stdout.read()))
        finally:
            client.close()
    
        #ssh into the cfg host and start the config server
        LOG.debug(_('ResumeConfigServer'))

# Assume there is no ordering dependency between instances
# pause each VM in parallel.
def PauseDBInstances(hosts_list):
    flow = uf.Flow('PauseDBInstances')
 
    for index, h in enumerate(hosts_list):
        host_info = h['secondaryReplica'].split(':')
        flow.add(PauseDBInstance('PauseDBInstance_' + h['secondaryReplica'], rebind=['secondary_' + str(index), 'DBUser', 'DBPassword']))

    return flow

def ResumeDBInstances(hosts_list):
    flow = uf.Flow('ResumeDBInstances')
 
    for index, h in enumerate(hosts_list):
        host_info = h['secondaryReplica'].split(':')
        flow.add(ResumeDBInstance('ResumeDBInstance_' + h['secondaryReplica'], rebind=['secondary_' + str(index), 'DBUser', 'DBPassword']))

    return flow

def secondaryhosts_to_backup(cntx, host, port, username, password):
    #
    # Creating connection to mongos server
    #
    LOG.debug(_('Connecting to mongos server ' + host))
    connection = connect_server(host, port, username, password)

    #
    # Getting sharding information
    #
    LOG.debug(_('Getting sharding configuration'))
    shards = getShards(connection)

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

def get_vms(cntx, dbhost, dbport, mongodbusername, mongodbpassword, sshport, hostusername, hostpassword):
    #
    # Creating connection to mongos server
    #
    LOG.debug(_('Connecting to mongos server ' + dbhost))
    connection = connect_server(dbhost, dbport, mongodbusername, mongodbpassword)

    #
    # Getting sharding information
    #
    LOG.debug(_('Getting sharding configuration'))
    shards = getShards(connection)

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
            if hostpassword == '':
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname, port=int(sshport), username=hostusername, password=hostpassword)
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
                        if hypervisor.hypervisor_hostname == instance.__dict__['OS-EXT-SRV-ATTR:hypervisor_hostname']:
                            hypervisor_hostname = hypervisor.hypervisor_hostname
                            hypervisor_type = hypervisor.hypervisor_type
                            break
                   
                    utils.append_unique(vms, {'vm_id' : instance.id,
                                              'vm_name' : instance.name,
                                              'vm_metadata' : instance.metadata,                                                
                                              'vm_flavor_id' : instance.flavor['id'],
                                              'vm_power_state' : instance.__dict__['OS-EXT-STS:power_state'],
                                              'hypervisor_hostname' : hypervisor_hostname,
                                              'hypervisor_type' :  hypervisor_type}, 
                                              "vm_id")
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

    #
    # MongoDB flow is an directed acyclic flow. 
    # :param host - One of the mongo db node in the cluster that has mongos 
    #               service running and will be used to discover the mongo db
    #               shards, their replicas etc
    # : port - port at which mongos service is running
    # : usename/password - username and password to authenticate to the database
    #
    def initflow(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        self._store['instances'] =  get_vms(cntx, self._store['DBHost'], self._store['DBPort'], self._store['DBUser'], self._store['DBPassword'], self._store['HostSSHPort'], self._store['HostUsername'], self._store['HostPassword'])
        hosts_to_backup = secondaryhosts_to_backup(cntx, self._store['DBHost'], self._store['DBPort'], self._store['DBUser'], self._store['DBPassword'])
        for index,item in enumerate(self._store['instances']):
            #self._store['instance_'+str(index)] = item
            self._store['instance_'+item['vm_id']] = item
        for index, item in enumerate(hosts_to_backup):
            self._store['secondary_'+str(index)] = item
        
        snapshotvms = lf.Flow('mongodbwf')
        
        # Add disable profile task. Stopping balancer fails if profile process
        # is running
        snapshotvms.add(DisableProfiling('DisableProfiling', provides='proflevel'))
    
        # This will be a flow that needs to be added to mongo db flow.
        # This is a flow that pauses all related VMs in unordered pattern
        snapshotvms.add(PauseDBInstances(hosts_to_backup))
    
        snapshotvms.add(ShutdownConfigServer('ShutdownConfigServer', provides=('cfgsrv', 'cfgsrvcmdline')))
    
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
        snapshotvms.add(ResumeConfigServer('ResumeConfigServer'))
    
        # unlock all locekd replicas so it starts receiving all updates from primary and
        # will eventually get into sync with primary
        snapshotvms.add(ResumeDBInstances(hosts_to_backup))
    
        # enable profiling to the level before the flow started
        snapshotvms.add(EnableProfiling('EnableProfiling'))

        super(MongoDBWorkflow, self).initflow(snapshotvms)

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
        LOG.debug(_( 'Connecting to mongos server ' + self._store['DBHost']))
        connection = connect_server(self._store['DBHost'], self._store['DBPort'], self._store['DBUser'], self._store['DBPassword'])

        #
        # Getting sharding information
        #
        LOG.debug(_( 'Getting sharding configuration'))
        shards = getShards(connection)

        # Get the replica set for each shard
        replicas = []
        for s in shards:
            hosts = str(s['host'])
            hosts = hosts.replace(str(s['_id']), '').strip()
            hosts = hosts.replace('/', '').strip()
            LOG.debug(_('Getting secondary from hosts in ' + hosts))
            # Get the replica set for each shard
            c = MongoClient(hosts,
                        read_preference=ReadPreference.SECONDARY)
            status = c.admin.command('replSetGetStatus')
            c = MongoClient(hosts,
                        read_preference=ReadPreference.SECONDARY)
            status = c.admin.command('replSetGetStatus')
            status["date"] = str(status["date"])
            status["children"] = status.pop("members")
            status["name"] = status.pop("set")
            status["status"] = "OK:"+str(status["ok"])
            status["input"] = []
            status["input"].append([])
            status["input"][0].append("myState")
            status["input"][0].append(status["myState"])
            for m in status["children"]:
                m["optimeDate"] = str(m["optimeDate"])
                m["status"] = m.pop("stateStr")
                if ('electionDate' in m):
                    m.pop('electionDate')
                if ('electionTime' in m):
                    m.pop('electionTime')
                if ("lastHeartbeatRecv" in m):
                    m["lastHeartbeatRecv"] = str(m["lastHeartbeatRecv"])
                if ("lastHeartbeat" in m):
                    m["lastHeartbeat"] = str(m["lastHeartbeat"])
                if ("optime" in m):
                    m["optime"] = str(m["optime"])
                m["input"] = []
                m["input"].append([])
                m["input"].append([])
                m["input"].append([])
                if ("syncingTo" in m):
                    m["input"][0].append("syncingTo")
                    m["input"][0].append(m["syncingTo"])
                m["input"][1].append("state")
                m["input"][1].append(m["state"])
                m["input"][2].append("health")
                m["input"][2].append(m["health"])
            replicas.append(status)

        # Covert the topology into generic topology that can be 
        # returned as restful payload
        mongodb = {"name": "MongoDB", "children":replicas, "input":[]}
        return dict(topology=mongodb)

    def details(self):
        # workflow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            if isinstance(item, task.Task):
                taskdetails = {'name':item._name.split("_")[0], 'type':'Task'}
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
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = get_vms(cntx, self._store['DBHost'], self._store['DBPort'], self._store['DBUser'], self._store['DBPassword'], self._store['HostSSHPort'], self._store['HostUsername'], self._store['HostPassword'])
        for instance in instances:
            del instance['hypervisor_hostname']
            del instance['hypervisor_type']
        return dict(instances=instances)

    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)

        #workloadmgr --os-auth-url http://$KEYSTONE_AUTH_HOST:5000/v2.0 --os-tenant-name admin --os-username admin --os-password $ADMIN_PASSWORD workload-type-create --metadata HostUsername=string --metadata HostPassword=password --metadata HostSSHPort=string --metadata DBHost=string --metadata DBPort=string --metadata DBUser=string --metadata DBPassword=password --metadata RunAsRoot=boolean --metadata capabilities='discover:topology' --display-name "MongoDB" --display-description "MongoDB workload description" --is-public True

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

import pdb;pdb.set_trace()
result = engines.load(mwf._flow, engine_conf='parallel', backend={'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8'}, store=store)

print mwf.execute()
"""
