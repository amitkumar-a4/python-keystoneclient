# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

import contextlib
import os
import random
import sys
import time

import datetime 
import paramiko
import uuid

from IPy import IP
from taskflow import engines
from taskflow.utils import misc
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import graph_flow as gf
from taskflow import task
from taskflow import flow
from taskflow.utils import reflection
from taskflow import exceptions

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp
from workloadmgr import utils

import vmtasks
import workflow

LOG = logging.getLogger(__name__)

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)

def InitFlow(store):
    pass

def connect_server(host, port, user, password):
    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy)
        client.connect(host, port, user, password)
        LOG.debug(_( 'Connected to ' +host +' on port ' + str(port)+ '...'))

    except Exception, e:
        LOG.error(_( 'There was an error connecting to cassandra node. Error %s. Try again...'), str(e))
    return client

def getnodeinfo(host, port, user, password):

    connection = connect_server(host, port, username, password)
    LOG.debug(_( 'Connected to cassandra node: ' + host))

    stdin, stdout, stderr = connection.exec_command("nodetool info")
    cassout = stdout.read(),

    cassout = cassout[0].split("\n")
    nodehash = {}
   
    for c in cassout:
       if len(c.split(":")) == 0:
          continue;

       nodehash[c.split(":")[0].strip()] = c.split(":")[1].strip()

    nodeinput = []
    nodeinput.append(['Gossip', str(nodehash['Gossip active'])])
    nodeinput.append(['Thrift', str(nodehash['Thrift active'])])

def getcassandranodes(connection):
    stdin, stdout, stderr = connection.exec_command("nodetool ring")
    cassout = stdout.read(),

    cassout = cassout[0].replace(" KB", "KB")
    #cassout= 'Address         DC          Rack        Status State   Load            Effective-Ownership Token                                      \n 124990069569720904109033691828482613006    \n 172.17.17.4     datacenter1 rack1       Up     Normal  26.9KB         0.00%               58281912783313757041398740202718796887     \n 172.17.17.2     datacenter1 rack1       Up     Normal  31.52KB        0.00%               78612805388309300046348770475254928516     \n 172.17.17.5     datacenter1 rack1       Up     Normal  26.9KB         0.00%               124990069569720904109033691828482613006    \n 172.17.17.6     datacenter1 rack2       Up     Normal  26.9KB         0.00%               58281912783313757041398740202718796887     \n 172.17.17.7     datacenter1 rack2       Up     Normal  31.52KB        0.00%               78612805388309300046348770475254928516     \n 172.17.17.8     datacenter1 rack2       Up     Normal  26.9KB         0.00%               124990069569720904109033691828482613006    \n 172.17.17.9     datacenter2 rack1       Up     Normal  26.9KB         0.00%               58281912783313757041398740202718796887     \n 172.17.17.10     datacenter2 rack1       Up     Normal  31.52KB        0.00%               78612805388309300046348770475254928516     \n 172.17.17.11     datacenter2 rack1       Up     Normal  26.9KB         0.00%               124990069569720904109033691828482613006    \n 172.17.17.12     datacenter2 rack2       Up     Normal  26.9KB         0.00%               58281912783313757041398740202718796887     \n 172.17.17.13     datacenter2 rack2       Up     Normal  31.52KB        0.00%               78612805388309300046348770475254928516     \n 172.17.17.14     datacenter2 rack2       Up     Normal  26.9KB         0.00%               124990069569720904109033691828482613006    \n'
    #parse nodetool output for cassandra nodes

    cassout = cassout.split("\n")

    casskeys = cassout[0].split()

    cassnodes = []
    for n in cassout[2:]:
        desc = n.split()
        if len(desc) == 0:
           continue
        node = {}
        for idx, k in enumerate(casskeys):
           node[k] = desc[idx]
        cassnodes.append(node)

    return cassnodes

def get_cassandra_nodes(cntx, host, port, username, password):
    #
    # Creating connection to cassandra namenode 
    #
    connection = connect_server(host, port, username, password)
    LOG.debug(_( 'Connected to cassandra node: ' + host))

    #
    # Getting sharding information
    #
    nodenames = getcassandranodes(connection)
    
    LOG.debug(_('Discovered cassandra nodes: ' + str(nodenames)))

    #
    # Resolve the node name to VMs
    # Usually Hadoop spits out nodes IP addresses. These
    # IP addresses need to be resolved to VM IDs by 
    # querying the VM objects from nova
    #
    ips = {}
    for name in nodenames:
        # if the name is host name, resolve it to IP address
        try :
           IP(name['Address'])
           ips[name['Address']] = 1
        except Exception, e:
           # we got hostnames
           import socket
           ips[socket.gethostbyname(name['Address'])] = 1

    # call nova list
    compute_service = nova.API(production=True)
    instances = compute_service.get_servers(cntx, admin=True)
    hypervisors = compute_service.get_hypervisors(cntx)

    vms = []
    # call nova interface-list <instanceid> to build the list of instances ids
    # if node names are host names then lookup the VMid based on the 
    for instance in instances:
        ifs = instance.addresses
        for addr in instance.addresses:
            # IP Addresses
            ifs = instance.addresses[addr]
            for _if in ifs:
                if _if['addr'] in ips:
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
                                              'vm_flavor_id' : instance.flavor['id'],
                                              'hypervisor_hostname' : hypervisor_hostname,
                                              'hypervisor_type' :  hypervisor_type}, 
                                        "vm_id")
    return vms

class SnapshotNode(task.Task):

    def execute(self, CassandraNode, SSHPort, Username, Password):
        self.client = connect_server(CassandraNode, int(SSHPort), Username, Password)
        # Make sure profile is disabled, but also save current
        # profiling state in the flow record? so revert as well
        # as ResumeDB task sets the right profiling level
        LOG.debug(_('SnapshotNode:'))
        stdin, stdout, stderr = self.client.exec_command("nodetool snapshot")
        out = stdout.read(),
        LOG.debug(_("nodetool snapshot output:" + str(out)))

        #find out if it is successful or not. If failure, throw exception
        return 

    def revert(self, *args, **kwargs):
        # Read profile level from the flow record?
        if not isinstance(kwargs['result'], misc.Failure):
            LOG.debug(_("Reverting SnapshotNode"))
            stdin, stdout, stderr = self.client.exec_command("nodetool clearsnapshot")
            out = stdout.read(),
            LOG.debug(_("revert Snapshotnode nodetool clearsnapshot output:" + str(out)))

class ClearSnapshot(task.Task):

    def execute(self, CassandraNode, SSHPort, Username, Password):
        self.client = connect_server(CassandraNode, int(SSHPort), Username, Password)
        # Make sure profile is disabled, but also save current
        # profiling state in the flow record? so revert as well
        # as ResumeDB task sets the right profiling level
        LOG.debug(_('ClearSnapshot:'))
        stdin, stdout, stderr = self.client.exec_command("nodetool clearsnapshot")
        out = stdout.read(),

        LOG.debug(_("ClearSnapshot nodetool clearsnapshot output:" + str(out)))

        return 

def UnorderedSnapshotNode(instances):
    flow = uf.Flow("snapshotnodeuf")
    for index,item in enumerate(instances):
        flow.add(SnapshotNode("SnapshotNode" + item['vm_name']))
    return flow

def UnorderedClearSnapshot(instances):
    flow = uf.Flow("clearsnapshotuf")
    for index,item in enumerate(instances):
        flow.add(ClearSnapshot("ClearSnapshot" + item['vm_name']))
    return flow

class CassandraWorkflow(workflow.Workflow):
    """"
      Cassandra Workflow
    """

    def __init__(self, name, store):
        super(CassandraWorkflow, self).__init__(name)
        self._store = store
        
    def initflow(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        self._store['instances'] =  get_cassandra_nodes(cntx, self._store['CassandraNode'], 
                 int(self._store['SSHPort']), self._store['Username'], self._store['Password'])
        for index,item in enumerate(self._store['instances']):
            self._store['instance_'+str(index)] = item
        
        self._flow = lf.Flow('cassandrawf')
        
        #create a network snapshot
        self._flow.add(vmtasks.SnapshotVMNetworks("SnapshotVMNetworks"))
        
        #snapshot flavors of VMs
        self._flow.add(vmtasks.SnapshotVMFlavors("SnapshotVMFlavors"))   
    
        # Enable safemode on the namenode
        self._flow.add(UnorderedSnapshotNode(self._store['instances']))
    
        # This is an unordered pausing of VMs. This flow is created in
        # common tasks library. This routine takes instance ids from 
        # openstack. Workload manager should provide the list of 
        # instance ids
        self._flow.add(vmtasks.UnorderedPauseVMs(self._store['instances']))
    
        # This is again unorder snapshot of VMs. This flow is implemented in
        # common tasks library
        self._flow.add(vmtasks.UnorderedSnapshotVMs(self._store['instances']))
    
        # This is an unordered pausing of VMs.
        self._flow.add(vmtasks.UnorderedUnPauseVMs(self._store['instances']))
    
        # enable profiling to the level before the flow started
        self._flow.add(UnorderedClearSnapshot(self._store['instances']))

        #calculate the size of the snapshot
        self._flow.add(vmtasks.UnorderedSnapshotDataSize(self._store['instances']))        
    
        # Now lazily copy the snapshots of VMs to tvault appliance
        self._flow.add(vmtasks.UnorderedUploadSnapshot(self._store['instances']))
    
        # block commit any changes back to the snapshot
        self._flow.add(vmtasks.UnorderedPostSnapshot(self._store['instances']))


    def topology(self):

        LOG.debug(_( 'Connecting to cassandra node ' + self._store['CassandraNode']))
        connection = connect_server(self._store['CassandraNode'], int(self._store['SSHPort']), self._store['Username'], self._store['Password'])
        cassnodes = getcassandranodes(connection)
        dcs = {'name': "Cassandra Cluster", "datacenters":{}, "input":[]}
        for n in cassnodes:
           # We discovered this datacenter for the first time, add it
           if not n['DC'] in dcs["datacenters"]:
              dcs['datacenters'][n['DC']] = {'name': n['DC'], "racks":{}, "input":[]}

           # We discovered this rack for the first time, add it
           if not n['Rack'] in dcs["datacenters"][n['DC']]["racks"]:
              dcs["datacenters"][n['DC']]["racks"][n['Rack']] = {'name': n['Rack'], "nodes":{}, "input":[]}

           #if not n['Address'] in dcs["datacenters"][n['DC']]["racks"][n['Rack']]["nodes"]:
           n['name'] = n['Address']
           n['status'] = n.pop('Status', None)
           n["input"] = []
           n['input'].append(["Load", n['Load']])
           n['input'].append(["State", n['State']])
           dcs["datacenters"][n['DC']]["racks"][n['Rack']]["nodes"][n['Address']] = {'name': n['Address'], "node": n}


        dcs["children"] = []
        for d, dv in dcs["datacenters"].iteritems():
           dcs["children"].append(dv)
           dv["children"] = []
           for r, rv in dv["racks"].iteritems():
              dv["children"].append(rv)
              rv["children"] = []
              for n, nv in rv["nodes"].iteritems():
                 rv["children"].append(nv['node'])

        for d, dv in dcs["datacenters"].iteritems():
           for r, rv in dv["racks"].iteritems():
              rv.pop("nodes", None)
           dv.pop("racks", None)
        dcs.pop("datacenters", None)
        return dict(topology=dcs)

    def details(self):
        # workflow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            if isinstance(item, task.Task):
                return {'name':str(item), 'type':'Task'}

            flowdetails = {}
            flowdetails['name'] = str(item)
            flowdetails['type'] = str(item).split('.')[2]
            flowdetails['children'] = []
            for it in item:
                flowdetails['children'].append(recurseflow(it))

            return flowdetails

        workflow = recurseflow(self._flow)
        return dict(workflow=workflow)

    def discover(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = get_cassandra_nodes(cntx, self._store['CassandraNode'], int(self._store['SSHPort']), self._store['Username'], self._store['Password'])
        return dict(instances=instances)
    
    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
    
'''
#test code
import json

#CassandraWorkflow Requires the following inputs in store:

store = {
    'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8',
    # Instanceids will to be discovered automatically
    'CassandraNode': 'cass1',   # cassandra node
    'SSHPort': '22',            # ssh port of namenode
    'Username': 'ubuntu',       # namenode user
    'Password': 'ubuntu',       # namenode password if ssh key is not set
}

c = nova.novaclient(None, production=True, admin=True);
context = context.RequestContext("4ca3ffa7849a4665b73e114907986e58", #admin user id
                                 c.client.projectid,
                                 is_admin = True,
                                 auth_token=c.client.auth_token)
store["context"] = context.__dict__
store["context"]["conf"] = None
cwf = CassandraWorkflow("testflow", store)
print json.dumps(cwf.discover())
print json.dumps(cwf.topology())
cwf.initflow()
print json.dumps(cwf.details())

#import pdb;pdb.set_trace()
#result = engines.load(cwf._flow, engine_conf='parallel', backend={'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8'}, store=store)

#print cwf.execute()
'''
