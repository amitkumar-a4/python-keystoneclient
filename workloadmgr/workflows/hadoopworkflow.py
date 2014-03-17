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

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp

import vmtasks
import workflow

LOG = logging.getLogger(__name__)

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)

def InitFlow(store):
    pass

#from workloadmgr import exception
# 
# Function that create the connection to the mongos server to be use as
# primary source of information in order to pick the servers. host, port
# user and password should be fed into the flow and other tasks should use
# them as needed.
#
def connect_server(host, port, user, password):
    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy)
        client.connect(host, port, user, password)
        LOG.debug(_( 'Connected to ' +host +' on port ' + str(port)+ '...'))

    except Exception, e:
        LOG.error(_( 'There was an error connecting to hadoop namenode. Error %s. Try again...'), str(e))
    return client

def getnodenames(connection):
    stdin, stdout, stderr = connection.exec_command("hadoop/bin/hadoop dfsadmin -report")
    dfsout = stdout.read(),

    #parse dfs output for hadoop nodes
    dfsout = dfsout[0].split("\n")
    line = '-------------------------------------------------'
    hcluster = dfsout[:dfsout.index(line)]
    dfsout = dfsout[dfsout.index(line) + 1:]
    totalnode = int(dfsout.pop(0).split(":")[1].strip().split(" ")[0])

    dfsout.pop(0)
    datanodes = []
    for _ in range(totalnode):
       x = dfsout.index("")
       node = dfsout[:x]
       datanodes.append(node)
       x = x + 2
       dfsout = dfsout[x:]

    hnodes = []
    for node in datanodes:
       dnode = {}
       for s in node:
          dnode[s.split(":")[0]] = s.split(":")[1]
       hnodes.append(dnode)

    nodenames = []
    for node in hnodes:
       nodenames.append(node["Name"].strip())

    return nodenames

def _append_unique(list, new_item, key):
    for item in list:
       if (item[key] == new_item[key]):
           return

    list.append(new_item)
    return

def get_hadoop_nodes(cntx, host, port, username, password):
    #
    # Creating connection to hadoop namenode 
    #
    connection = connect_server(host, port, username, password)
    LOG.debug(_( 'Connected to hadoop name server: ' + host))

    #
    # Getting sharding information
    #
    nodenames = getnodenames(connection)
    LOG.debug(_('Discovered hadoop nodes: ' + str(nodenames)))

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
           IP(name)
           ips[name] = 1
        except Exception, e:
           # we got hostnames
           import socket
           ips[socket.gethostbyname(name)] = 1

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
                        if hypervisor.hypervisor_hostname == instance.__dict__['OS-EXT-SRV-ATTR:host']:
                            hypervisor_hostname = hypervisor.hypervisor_hostname
                            hypervisor_type = hypervisor.hypervisor_type
                            break
                   
                    _append_unique(vms, {'vm_id' : instance.id,
                          'vm_name' : instance.name,
                          'vm_flavor_id' : instance.flavor['id'],
                          'hypervisor_hostname' : hypervisor_hostname,
                          'hypervisor_type' :  hypervisor_type}, "vm_id")
    return vms

class EnableSafemode(task.Task):

    def execute(self, Namenode, NamenodeSSHPort, Username, Password):
        self.client = connect_server(Namenode, int(NamenodeSSHPort), Username, Password)
        # Make sure the cluster is set to safemode

        LOG.debug(_('EnableSafemode:' + Namenode))
        stdin, stdout, stderr = self.client.exec_command("hadoop/bin/hadoop dfsadmin -safemode get")
        try:
            stdout.read().index("ON")
            safemode=True
        except Exception, e:
            safemode=False

        stdin, stdout, stderr = self.client.exec_command("hadoop/bin/hadoop dfsadmin -safemode enter")
        stdout.read()

        return safemode

    def revert(self, *args, **kwargs):
        # Read profile level from the flow record?
        if not isinstance(kwargs['result'], misc.Failure):
            if not kwargs['result']:
                # our workflow set the cluster to safemode
                # revert back
                stdin, stdout, stderr = self.client.exec_command("hadoop/bin/hadoop dfsadmin -safemode leave")
                stdout.read()
              
class DisableSafemode(task.Task):

    def execute(self, Namenode, NamenodeSSHPort, Username, Password, safemode):
        if not safemode:
           self.client = connect_server(Namenode, int(NamenodeSSHPort), Username, Password)
           # Make sure the cluster is set to safemode

           LOG.debug(_('DisableSafemode:' + Namenode))
           stdin, stdout, stderr = self.client.exec_command("hadoop/bin/hadoop dfsadmin -safemode leave")
           mode = stdout.read()
           LOG.debug(_(mode))

class HadoopWorkflow(workflow.Workflow):
    """"
      Hadoop Workflow
    """

    def __init__(self, name, store):
        super(HadoopWorkflow, self).__init__(name)
        self._store = store

    #
    # Hadoop workflowflow is a linear flow
    # :param host - hadoop name node
    # : port - ssh port of hadoop
    # : usename/password - username and password to authenticate to the namenode
    #
    def initflow(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        self._store['instances'] =  get_hadoop_nodes(cntx, self._store['Namenode'], 
                 int(self._store['NamenodeSSHPort']), self._store['Username'], self._store['Password'])
        for index,item in enumerate(self._store['instances']):
            self._store['instance_'+str(index)] = item
        
        self._flow = lf.Flow('hadoopwf')
        
        #create a network snapshot
        self._flow.add(vmtasks.SnapshotVMNetworks("SnapshotVMNetworks"))
        
        #snapshot flavors of VMs
        self._flow.add(vmtasks.SnapshotVMFlavors("SnapshotVMFlavors"))   
    
        # Enable safemode on the namenode
        self._flow.add(EnableSafemode('EnableSafemore', provides='safemode'))
    
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
        self._flow.add(DisableSafemode('DisableSafemode'))
    
        # Now lazily copy the snapshots of VMs to tvault appliance
        self._flow.add(vmtasks.UnorderedUploadSnapshot(self._store['instances']))
    
        # block commit any changes back to the snapshot
        self._flow.add(vmtasks.UnorderedPostSnapshot(self._store['instances']))


    def topology(self):
        return dict(topology={})

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
        instances = get_hadoop_nodes(cntx, self._store['Namenode'], int(self._store['NamenodeSSHPort']), self._store['Username'], self._store['Password'])
        return dict(instances=instances)
    
    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
    
"""
#test code
import json

#HadoopWorkflow Requires the following inputs in store:

store = {
    'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8',
    # Instanceids will to be discovered automatically
    'Namenode': 'hadoop1',            # namenode
    'NamenodeSSHPort': '22',                   # ssh port of namenode
    'Username': 'hduser',         # namenode user
    'Password': 'ubuntu',         # namenode password if ssh key is not set
}

c = nova.novaclient(None, production=True, admin=True);
context = context.RequestContext("c852956b1d5743fb81a350a31282d32e", #admin user id
                                 c.client.projectid,
                                 is_admin = True,
                                 auth_token=c.client.auth_token)
store["context"] = context.__dict__
store["context"]["conf"] = None
hwf = HadoopWorkflow("testflow", store)
print json.dumps(hwf.discover())
hwf.initflow()
print json.dumps(hwf.details())
print json.dumps(hwf.topology())

import pdb;pdb.set_trace()
result = engines.load(hwf._flow, engine_conf='parallel', backend={'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8'}, store=store)

print hwf.execute()
"""