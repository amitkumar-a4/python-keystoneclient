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
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(host, port, user, password)
        LOG.debug(_( 'Connected to ' +host +' on port ' + str(port)+ '...'))
        stdin, stdout, stderr = client.exec_command("nodetool status")
        if stderr.read() != '':
            raise Exception(_("Cassandra service is not running on %s"), host)

    except Exception, e:
        LOG.error(_( 'There was an error connecting to cassandra node. Error %s. Try again...'), str(e))
        raise e
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
    stdin, stdout, stderr = connection.exec_command("nodetool status")
    cassout = stdout.read(),

    cassout = cassout[0].replace(" KB", "KB")
    cassout = cassout.replace(" (", "(")
    cassout = cassout.replace(" ID", "ID")
 
    # Sample output
    #cassout =Datacenter: 17
    #==============
    #Status=Up/Down
    #|/ State=Normal/Leaving/Joining/Moving
    #--  Address      Load       Owns (effective)  Host ID                               Token                                    Rack
    #UN  172.17.17.2  55.56 KB   0.2%              7d62d900-f99d-4b88-8012-f06cb639fc02  0                                        17
    #UN  172.17.17.4  76.59 KB   100.0%            75917649-6caa-4c66-b003-71c0eb8c09e8  -9210152678340971410                     17
    #UN  172.17.17.5  86.46 KB   99.8%             a03a1287-7d32-42ed-9018-8206fc295dd9  -9218601096928798970                     17

    cassout = cassout.split("\n")
    for idx, val in enumerate(cassout):
        if val.startswith("Datacenter"):
           break

    cassout = cassout[idx:]
    casskeys = cassout[4].split()

    cassnodes = []
    for n in cassout[5:]:
        desc = n.split()
        if len(desc) == 0:
            continue
        node = {}
        for idx, k in enumerate(casskeys):
            node[k] = desc[idx]

        # Sample output
        # =============
        # Token            : (invoke with -T/--tokens to see all 256 tokens)
        # ID               : f64ced33-2c01-40a3-9979-cf0a0b60d7af
        # Gossip active    : true
        # Thrift active    : true
        # Native Transport active: true
        # Load             : 148.13 KB
        # Generation No    : 1399521595
        # Uptime (seconds) : 36394
        # Heap Memory (MB) : 78.66 / 992.00
        # Data Center      : 17
        # Rack             : 17
        # Exceptions       : 0
        # Key Cache        : size 1400 (bytes), capacity 51380224 (bytes), 96 hits, 114 requests, 0.842 recent hit rate, 14400 save period in seconds
        # Row Cache        : size 0 (bytes), capacity 0 (bytes), 0 hits, 0 requests, NaN recent hit rate, 0 save period in seconds

        stdin, stdout, stderr = connection.exec_command("nodetool -h " + node['Address'] + " info")
        output = stdout.read()
        output = output.split("\n")
        for l in output:
            fields = l.split(":")
            if len(fields) > 1:
                node[fields[0].strip()] = fields[1]

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

    interfaces = {}
    for ip in ips:
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if password == '':
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(ip, port=int(port), username=username, password=password)
                stdin, stdout, stderr = client.exec_command('ifconfig eth0 | grep HWaddr')
                interfaces[stdout.read().split('HWaddr')[1].strip()] = ip
            except:
                pass
        finally:
            client.close()

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
                #this is our vm
                hypervisor_hostname = None
                hypervisor_type = None
                for hypervisor in hypervisors:
                    if hypervisor.hypervisor_hostname == instance.__dict__['OS-EXT-SRV-ATTR:hypervisor_hostname']:
                        hypervisor_hostname = hypervisor.hypervisor_hostname
                        hypervisor_type = hypervisor.hypervisor_type
                        break
                if _if['OS-EXT-IPS-MAC:mac_addr'] in interfaces:
                   
                    utils.append_unique(vms, {'vm_id' : instance.id,
                                              'vm_name' : instance.name,
                                              'vm_metadata' : instance.metadata,                                                
                                              'vm_flavor_id' : instance.flavor['id'],
                                              'hostname' : interfaces[_if['OS-EXT-IPS-MAC:mac_addr']],
                                              'vm_power_state' : instance.__dict__['OS-EXT-STS:power_state'],
                                              'hypervisor_hostname' : hypervisor_hostname,
                                              'hypervisor_type' :  hypervisor_type}, 
                                              "vm_id")
    return vms

class SnapshotNode(task.Task):

    def execute(self, CassandraNode, SSHPort, Username, Password):
        try:
            self.client = connect_server(CassandraNode, int(SSHPort), Username, Password)
            LOG.debug(_('SnapshotNode:'))
            stdin, stdout, stderr = self.client.exec_command("nodetool snapshot")
            out = stdout.read(),
            LOG.debug(_("nodetool snapshot output:" + str(out)))
        except:
            LOG.warning(_("Cannot run nodetool snapshot command on %s"), CassandraNode)
            LOG.warning(_("Either node is down or cassandra service is not running on the node %s"), CassandraNode)

        return 

    def revert(self, *args, **kwargs):
        if not isinstance(kwargs['result'], misc.Failure):
            LOG.debug(_("Reverting SnapshotNode"))
            stdin, stdout, stderr = self.client.exec_command("nodetool clearsnapshot")
            out = stdout.read(),
            LOG.debug(_("revert Snapshotnode nodetool clearsnapshot output:" + str(out)))

class ClearSnapshot(task.Task):

    def execute(self, CassandraNode, SSHPort, Username, Password):
        try:
            self.client = connect_server(CassandraNode, int(SSHPort), Username, Password)
            LOG.debug(_('ClearSnapshot:'))
            stdin, stdout, stderr = self.client.exec_command("nodetool clearsnapshot")
            out = stdout.read(),

            LOG.debug(_("ClearSnapshot nodetool clearsnapshot output:" + str(out)))
        except:
            LOG.warning(_("Cannot run nodetool clearsnapshot command on %s"), CassandraNode)
            LOG.warning(_("Either node is down or cassandra service is not running on the node %s"), CassandraNode)

        return 

def UnorderedSnapshotNode(instances):
    flow = uf.Flow("snapshotnodeuf")
    for index,item in enumerate(instances):
        flow.add(SnapshotNode("SnapshotNode_" + item['vm_name'], rebind=('CassandraNodeName_'+item['vm_id'], "SSHPort", "Username", "Password")))
    return flow

def UnorderedClearSnapshot(instances):
    flow = uf.Flow("clearsnapshotuf")
    for index,item in enumerate(instances):
        flow.add(ClearSnapshot("ClearSnapshot_" + item['vm_name'], rebind=('CassandraNodeName_'+item['vm_id'], "SSHPort", "Username", "Password")))
    return flow

class CassandraWorkflow(workflow.Workflow):
    """"
      Cassandra Workflow
    """

    def __init__(self, name, store):
        super(CassandraWorkflow, self).__init__(name)
        self._store = store
        
    def find_first_alive_node(self):
        # Iterate thru all hosts and pick the one that is alive
        if 'hostnames' in self._store:
            for host in self._store['hostnames'].split(";"):
                try:
                    connection = connect_server(host, 
                                                int(self._store['SSHPort']),
                                                self._store['Username'],
                                                self._store['Password'])
                    self._store['CassandraNode'] = host
                    LOG.debug(_( 'Chose "' + host +'" for cassandra nodetool'))
                    return
                except:
                    LOG.debug(_( '"' + host +'" appears to be offline'))
                    pass
        LOG.warning(_( 'Cassandra cluster appears to be offline'))

    def initflow(self):
        self.find_first_alive_node()
        cntx = amqp.RpcContext.from_dict(self._store['context'])

        self._store['instances'] =  get_cassandra_nodes(cntx, self._store['CassandraNode'], 
                 int(self._store['SSHPort']), self._store['Username'], self._store['Password'])
        for index,item in enumerate(self._store['instances']):
            self._store['instance_'+item['vm_id']] = item
            self._store['CassandraNodeName_'+item['vm_id']] = item['vm_name']
        
        snapshotvms = lf.Flow('cassandrawf')
        
        # Enable safemode on the namenode
        snapshotvms.add(UnorderedSnapshotNode(self._store['instances']))
    
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
    
        # enable profiling to the level before the flow started
        snapshotvms.add(UnorderedClearSnapshot(self._store['instances']))

        super(CassandraWorkflow, self).initflow(snapshotvms)


    def topology(self):
        LOG.debug(_( 'Connecting to cassandra node ' + self._store['CassandraNode']))
        self.find_first_alive_node()

        connection = connect_server(self._store['CassandraNode'], int(self._store['SSHPort']), self._store['Username'], self._store['Password'])
        cassnodes = getcassandranodes(connection)
        dcs = {'name': "Cassandra Cluster", "datacenters":{}, "input":[]}
        for n in cassnodes:
            # We discovered this datacenter for the first time, add it
            if not n['Data Center'] in dcs["datacenters"]:
                dcs['datacenters'][n['Data Center']] = {'name': n['Data Center'], "racks":{}, "input":[]}

            # We discovered this rack for the first time, add it
            if not n['Rack'] in dcs["datacenters"][n['Data Center']]["racks"]:
                dcs["datacenters"][n['Data Center']]["racks"][n['Rack']] = {'name': n['Rack'], "nodes":{}, "input":[]}

            #if not n['Address'] in dcs["datacenters"][n['Data Center']]["racks"][n['Rack']]["nodes"]:
            n['name'] = n['Address']
            n['status'] = n.pop('Status', None)
            n["input"] = []
            n['input'].append(["Load", n['Load']])
            #n['input'].append(["State", n['State']])
            dcs["datacenters"][n['Data Center']]["racks"][n['Rack']]["nodes"][n['Address']] = {'name': n['Address'], "node": n}


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
        self.find_first_alive_node()
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = get_cassandra_nodes(cntx, self._store['CassandraNode'], int(self._store['SSHPort']), self._store['Username'], self._store['Password'])
        for instance in instances:
            del instance['hypervisor_hostname']
            del instance['hypervisor_type']
        return dict(instances=instances)
    
    def execute(self):
        if self._store['source_platform'] == "vmware":
            compute_service = nova.API(production=True)
            search_opts = {}
            search_opts['deep_discover'] = '1'
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            compute_service.get_servers(cntx, search_opts=search_opts)

        # Iterate thru all hosts and pick the one that is alive
        self.find_first_alive_node()

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
#print json.dumps(cwf.discover())
#print json.dumps(cwf.topology())
cwf.initflow()
#import pdb;pdb.set_trace()
print json.dumps(cwf.details())

#result = engines.load(cwf._flow, engine_conf='parallel', backend={'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8'}, store=store)

#print cwf.execute()
'''
