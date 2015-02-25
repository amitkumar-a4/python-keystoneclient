# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

import contextlib
import os
import os.path
import yaml
import glob
import random
import sys
import time
import re
import shutil
import socket

import datetime 
import json
import paramiko
import uuid
import cPickle as pickle
from tempfile import mkstemp
import subprocess

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
from workloadmgr import autolog
from workloadmgr import exception

import vmtasks
import workflow
import restoreworkflow
import vmtasks_openstack
import vmtasks_vcloud

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)

def InitFlow(store):
    pass

def _exec_command(connection, command):
    stdin, stdout, stderr = connection.exec_command('bash -c "' + command + '"', timeout=120)
    err_msg = stderr.read()
    if err_msg != '':
        stdin, stdout, stderr = connection.exec_command(command, timeout=120)
        err_msg = stderr.read()
        if err_msg != '':
            raise Exception(_("Error connecting to Cassandra Service on %s - %s") % (str(connection), err_msg))
    return stdin, stdout, stderr
    
def connect_server(host, port, user, password):
    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(host, port, user, password, timeout=120)
        LOG.info(_( 'Connected to ' +host +' on port ' + str(port)+ '...'))
        stdin, stdout, stderr = _exec_command(client, "nodetool status")
    except Exception as ex:
        LOG.error(_( 'There was an error connecting to cassandra node. Error %s. Try again...'), str(ex))
        raise ex
    return client

class SnapshotNode(task.Task):

    def execute(self, CassandraNode, SSHPort, Username, Password):
        try:
            self.client = connect_server(CassandraNode, int(SSHPort), Username, Password)
            LOG.info(_('SnapshotNode:'))
            stdin, stdout, stderr = _exec_command(self.client, "nodetool snapshot")
            out = stdout.read(),
            LOG.info(_("nodetool snapshot output:" + str(out)))
            self.client.close()
        except:
            LOG.warning(_("Cannot run nodetool snapshot command on %s"), CassandraNode)
            LOG.warning(_("Either node is down or cassandra service is not running on the node %s"), CassandraNode)

        return 

    def revert(self, *args, **kwargs):
        if not isinstance(kwargs['result'], misc.Failure):
            LOG.info(_("Reverting SnapshotNode"))
            stdin, stdout, stderr = _exec_command(self.client, "nodetool clearsnapshot")
            out = stdout.read(),
            LOG.info(_("revert Snapshotnode nodetool clearsnapshot output:" + str(out)))
            self.client.close()

class ClearSnapshot(task.Task):

    def execute(self, CassandraNode, SSHPort, Username, Password):
        try:
            self.client = connect_server(CassandraNode, int(SSHPort), Username, Password)
            LOG.info(_('ClearSnapshot:'))
            stdin, stdout, stderr = _exec_command(self.client, "nodetool clearsnapshot")
            out = stdout.read(),
            LOG.info(_("ClearSnapshot nodetool clearsnapshot output:" + str(out)))
            self.client.close()
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


def get_cassandra_nodes(cntx, store, findpartitiontype = 'False'):
    LOG.info(_('Enter get_cassandra_nodes'))
    try:    
        fh, outfile_path = mkstemp()
        os.close(fh)
        fh, errfile_path = mkstemp()
        os.close(fh)        
        cmdspec = ["python", "/opt/stack/workloadmgr/workloadmgr/workflows/cassnodes.py",
                   "--config-file", "/etc/workloadmgr/workloadmgr.conf",
                   "--defaultnode", store['CassandraNode'],
                   "--port", store['SSHPort'],
                   "--username", store['Username'],
                   "--password", "******",]

        if store.get('hostnames', None):
            cmdspec.extend(["--addlnodes", store.get('hostnames', "")])
        if store.get('preferredgroup', None):
            cmdspec.extend(["--preferredgroups", store.get('preferredgroup', "")])
        
        cmdspec.extend(["--findpartitiontype", findpartitiontype,
                        "--outfile", outfile_path,
                        "--errfile", errfile_path,
                       ])
        cmd = " ".join(cmdspec)
        for idx, opt in enumerate(cmdspec):
            if opt == "--password":
                cmdspec[idx+1] = store['Password']
                break
        process = subprocess.Popen(cmdspec,shell=False)
        stdoutdata, stderrdata = process.communicate()
        if process.returncode != 0:
            reason = 'Error discovering Cassandra nodes'
            try:
                with open(errfile_path, 'r') as fh:
                    reason = fh.read()
                    LOG.info(_('Error discovering Cassandra nodes: ' + reason))
                os.remove(errfile_path)
            finally:
                raise exception.ErrorOccured(reason=reason)
    
        cassandra_nodes = None
        clusterinfo = None
        with open(outfile_path, 'r') as fh:
            clusterinfo = json.loads(fh.read())
            LOG.info(_('Discovered Cassandra Nodes: ' + str(clusterinfo)))
        
        if os.path.isfile(outfile_path):
            os.remove(outfile_path)
        if os.path.isfile(errfile_path):
            os.remove(errfile_path)
        
        return clusterinfo['cassandranodes'], clusterinfo

    finally:
        LOG.info(_('Exit get_cassandra_nodes'))    
    
def get_cassandra_instances(cntx, store, findpartitiontype = 'False'):
    LOG.info(_('Enter get_cassandra_instances'))
    try:    
        cassandra_nodes, clusterinfo = get_cassandra_nodes(cntx, store, findpartitiontype = findpartitiontype)
        
        interfaces = {}
        root_partition_type = {}
        for node in cassandra_nodes:
            if 'MacAddresses' in node:
                for macaddress in node['MacAddresses']:
                    interfaces[macaddress.lower()] = node['IPAddress']
                    root_partition_type[macaddress.lower()] = node.get('root_partition_type', 'lvm')
        
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
                    if _if['OS-EXT-IPS-MAC:mac_addr'].lower() in interfaces:
                        utils.append_unique(vms, {'vm_id' : instance.id,
                                                  'vm_name' : instance.name,
                                                  'vm_metadata' : instance.metadata,                                                
                                                  'vm_flavor_id' : instance.flavor['id'],
                                                  'hostname' : interfaces[_if['OS-EXT-IPS-MAC:mac_addr'].lower()],
                                                  'root_partition_type' : root_partition_type[_if['OS-EXT-IPS-MAC:mac_addr'].lower()],
                                                  'vm_power_state' : instance.__dict__['OS-EXT-STS:power_state'],
                                                  'hypervisor_hostname' : hypervisor_hostname,
                                                  'hypervisor_type' :  hypervisor_type}, 
                                                  "vm_id")
        LOG.info(_('Discovered Cassandra Virtual Machines: ' + str(vms)))
        return vms            
    finally:
        LOG.info(_('Exit get_cassandra_instances'))    
            
class CassandraWorkflow(workflow.Workflow):
    """"
    Cassandra Workflow
    """

    def __init__(self, name, store):
        super(CassandraWorkflow, self).__init__(name)
        self._store = store
        
    def initflow(self, composite=False):
        try:
            cntx = amqp.RpcContext.from_dict(self._store['context'])

            self._store['instances'] =  get_cassandra_instances(cntx, self._store, findpartitiontype = 'True')
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

            super(CassandraWorkflow, self).initflow(snapshotvms, composite=composite)

        finally:
            pass

    def topology(self):
        try:
            LOG.info(_( 'Connecting to cassandra node ' + self._store['CassandraNode']))
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            cassnodes, clusterinfo = get_cassandra_nodes(cntx, self._store, findpartitiontype = 'False')

            dcs = {'name': clusterinfo['Name'], "datacenters":{}, "input":[]}
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
        finally:
            pass

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
        try:
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            instances = get_cassandra_instances(cntx, self._store, findpartitiontype = 'False')
            for instance in instances:
                del instance['hypervisor_hostname']
                del instance['hypervisor_type']
            return dict(instances=instances)
        finally:
            pass
    
    def execute(self):
        if self._store['source_platform'] == "vmware":
            compute_service = nova.API(production=True)
            search_opts = {}
            search_opts['deep_discover'] = '1'
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            compute_service.get_servers(cntx, search_opts=search_opts)

        # Iterate thru all hosts and pick the one that is alive
        connection = self.find_first_alive_node()
        if connection:            
            connection.close()        

        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
    
def update_cassandra_yaml(mountpath, clustername, nodeip, ips):
    # modify the cassandra.yaml
    configpath = ""
    if os.path.exists(os.path.join(mountpath, 'usr/share/dse/resources/cassandra/conf/')):
        # This one appears to be DSE installation
        configpath = 'usr/share/dse/resources/cassandra/conf/'
    else:
        configpath = 'etc/cassandra'

    yamlpath = os.path.join(mountpath, configpath, 'cassandra.yaml')
    yamlbakpath = os.path.join(mountpath, configpath, 'cassandra.yaml.bak')

    os.rename(yamlpath, yamlbakpath)
    with open(yamlbakpath, 'r') as f:
        doc = yaml.load(f)

    if doc['cluster_name'] != clustername:
        # User chose a new cluster name
        # clean up the system directory
        for path in doc['data_file_directories']:
            if os.path.isabs(path):
                path = path[1:]
            syspath = os.path.join(path, 'system')
            syspath = os.path.join(mountpath, syspath)
            for subdir in os.listdir(syspath):
                shutil.rmtree(os.path.join(syspath, subdir))

    doc['cluster_name'] = clustername
    if 'listen_address' in doc and doc['listen_address'] != None \
       and doc['listen_address'] != "0.0.0.0":
        doc['listen_address'] = nodeip

    if 'rpc_address' in doc and doc['rpc_address'] != None \
       and doc['rpc_address'] != "0.0.0.0":
        doc['rpc_address'] = nodeip

    doc['seed_provider'][0]['parameters'][0]['seeds'] =  ips
    with open(yamlpath, 'w') as f:
        f.write(yaml.safe_dump(doc))

def update_cassandra_topology_yaml(mountpath, address, broadcast):

    configpath = ""
    if os.path.exists(os.path.join(mountpath, 'usr/share/dse/resources/cassandra/conf/')):
        # This one appears to be DSE installation
        configpath = 'usr/share/dse/resources/cassandra/conf/'
    else:
        configpath = 'etc/cassandra'

    yamlpath = os.path.join(mountpath, configpath, 'cassandra-topology.yaml')
    yamlbakpath = os.path.join(mountpath, configpath, 'cassandra-topology.yaml.bak')

    # modify the cassandra-topology.yaml
    os.rename(yamlpath, yamlbakpath)
    with open(yamlbakpath, 'r') as f:
        doc = yaml.load(f)

    doc['topology'][0]['racks'][0]['nodes'][0]['dc_local_address'] = address
    doc['topology'][0]['racks'][0]['nodes'][0]['broadcast_address'] = broadcast
    with open(yamlpath, 'w') as f:
        f.write(yaml.safe_dump(doc))

def update_cassandra_topology_properties(mountpath, addresses):

    # modify the cassandra-topology.properties
    configpath = ""
    if os.path.exists(os.path.join(mountpath, 'usr/share/dse/resources/cassandra/conf/')):
        # This one appears to be DSE installation
        configpath = 'usr/share/dse/resources/cassandra/conf/'
    else:
        configpath = 'etc/cassandra'

    topopath = os.path.join(mountpath, configpath, 'cassandra-topology.properties')
    topobakpath = os.path.join(mountpath, configpath, 'cassandra-topology.properties.bak')

    os.rename(topopath, topobakpath)

    with open(topopath, 'w') as f:
        f.write("# Updated the addresses by TrilioVault restore process\n")
        for addr in addresses.split(","):
            f.write(addr + "=DC1:RAC1\n")

def update_cassandra_env_sh(mountpath, hostname):
    # modify the cassandra-env.sh
    configpath = ""
    if os.path.exists(os.path.join(mountpath, 'usr/share/dse/resources/cassandra/conf/')):
        # This one appears to be DSE installation
        configpath = 'usr/share/dse/resources/cassandra/conf/'
    else:
        configpath = 'etc/cassandra'

    envpath = os.path.join(mountpath, configpath, 'cassandra-env.sh')
    envbakpath = os.path.join(mountpath, configpath, 'cassandra-env.sh.bak')

    os.rename(envpath, envbakpath)

    with open(envbakpath, 'r') as f:
        with open(envpath, 'w') as fout:
            for line in f:
                if "java.rmi.server.hostname" in line:
                    line = 'JVM_OPTS="$JVM_OPTS -Djava.rmi.server.hostname=' + hostname + '"\n'
                fout.write(line)

def update_hostname(mountpath, hostname):
    #modify hostname
    os.rename(mountpath + '/etc/hostname',
              mountpath + '/etc/hostname.bak')
    with open(mountpath + '/etc/hostname', 'w') as fout:
        fout.write(hostname)

def update_hostsfile(mountpath, hostnames, ipaddresses):
    with open(mountpath + '/etc/hosts', 'a') as f:
        ips = ipaddresses.split(",")
        hosts = hostnames.split(",")
        for index, item in enumerate(hosts):
            f.write(ips[index] + "    " + item + "\n")

def create_interface_stanza(interface, address, netmask,
                            broadcast, gateway):
    stanza = []
    stanza.append("auto " + interface)
    stanza.append("    iface " + interface + " inet static")
    stanza.append("    address " + address)
    stanza.append("    netmask " + netmask)
    stanza.append("    broadcast " + broadcast)
    stanza.append("    gateway " + gateway)
    stanza.append("    up ip link set $IFACE promisc on")
    stanza.append("    down ip link set $IFACE promisc off")
    return stanza

def update_network_interfaces(mountpath, interface, address, netmask,
                              broadcast, gateway):
    # modify network interfaces 
    # this could be specific to each linux distribution.
    # we are doing it for ubuntu now
    os.rename(mountpath + '/etc/network/interfaces',
              mountpath + '/etc/network/interfaces.bak')
    with open(mountpath + '/etc/network/interfaces.bak', 'r') as f:
        with open(mountpath + "/etc/network/interfaces", 'w') as newinf:
            line = f.readline()
            while line:
                if line.startswith("source"):
                    # open the file that is specified by the source
                    dirname = line.replace("source ", "")
                    dirname = dirname.rstrip("\n")
                    for filename in glob.glob(mountpath + dirname):
                        os.rename(filename,
                                  filename + ".bak")
                        with open(filename + ".bak", 'r') as ethfile:
                            with open(filename, 'w') as newethfile:
                                stanza = create_interface_stanza(interface, address,
                                                                 netmask, broadcast,
                                                                 gateway)
                                newethfile.write("\n".join(stanza))
                                newethfile.write("\n")
                                for l in ethfile:
                                    skip = False
                                    for pat in ["auto", "iface", "address", 
                                                 "netmask", "network", "broadcast", "gateway"]:
                                        if l.lstrip().startswith(pat):
                                            skip = True
                                            break
                                    if not skip:
                                        newethfile.write(l)
                        break
                    newinf.write(line)
                    line = f.readline()
                            
                elif line.strip().startswith("auto"):
                    if line.split()[1].strip().rstrip() == "lo":
                        newinf.write(line)
                        line = f.readline()
                        while not line.strip().startswith("auto") and \
                              not line.strip().startswith("source"):
                            newinf.write(line)
                            line = f.readline()
                    else:
                        stanza = create_interface_stanza(interface, address, netmask,
                                                         broadcast, gateway)
                        newinf.write("\n".join(stanza))
                        newinf.write("\n")
                        while not line.strip().startswith("auto"):
                            skip = False
                            for pat in ["auto", "iface", "address", 
                                        "netmask", "network", "broadcast", "gateway"]:
                                if l.lstrip().startswith(pat):
                                    skip = True
                                    break
                            if not skip:
                                newinf.write(line)
                            line = f.readline()
                        break 
                else:
                    # comments and everything else
                    newinf.write(line)
                    line = f.readline()

class CassandraRestoreNode(task.Task):

    def execute(self, context, instance, restore, restore_options, ipaddress, hostname):
        return self.execute_with_log(context, instance, restore, restore_options, ipaddress, hostname)
    
    def revert(self, *args, **kwargs):
        return self.revert_with_log(*args, **kwargs)
    
    @autolog.log_method(Logger, 'CassandraRestoreNode.execute')
    def execute_with_log(self, context, instance, restore, restore_options, ipaddress, hostname):
        # pre processing of snapshot
        cntx = amqp.RpcContext.from_dict(context)
        process, mountpath = vmtasks_vcloud.mount_instance_root_device(cntx, instance, restore)
        try:
            update_cassandra_yaml(mountpath, restore_options['NewClusterName'],
                                  ipaddress,
                                  restore_options['IPAddresses'])
            update_cassandra_topology_yaml(mountpath, ipaddress,
                                           restore_options['Broadcast'])
            update_cassandra_topology_properties(mountpath,
                                  restore_options['IPAddresses'])
            update_cassandra_env_sh(mountpath, hostname)
            update_hostname(mountpath, hostname)

            update_hostsfile(mountpath, restore_options['Nodenames'],
                             restore_options['IPAddresses'])

            update_network_interfaces(mountpath, "eth0", ipaddress,
                                      restore_options['Netmask'],
                                      restore_options['Broadcast'],
                                      restore_options['Gateway'])
        finally:
            vmtasks_vcloud.umount_instance_root_device(process)

    @autolog.log_method(Logger, 'CassandraRestoreNode.revert')
    def revert_with_log(self, *args, **kwargs):
        if not isinstance(kwargs['result'], misc.Failure):
            process = amqp.RpcContext.from_dict(kwargs['process'])
            vmtasks_vcloud.umount_instance_root_device(process)
        
def LinearCassandraRestoreNodes(workflow):
    flow = lf.Flow("cassandrarestoreuf")
    for index, item in enumerate(workflow._store['instances']):
        rebind_dict = dict(instance = "restored_instance_" + str(index),\
                           ipaddress = "ipaddress_"+str(item['vm_name']),\
                           hostname = "hostname_"+str(item['vm_name']))
        flow.add(CassandraRestoreNode("CassandraRestoreNode_" + item['vm_id'], rebind=rebind_dict))

    return flow

class CassandraRestore(restoreworkflow.RestoreWorkflow):

    def initflow(self):
        options = pickle.loads(self._store['restore']['pickle'].encode('ascii', 'ignore'))
        if 'restore_options' in options and options['restore_options'] != {}:
            restore_options = options['restore_options']
            self._store['restore_options'] = restore_options

            addresses = []
            for vmname, item in restore_options['IPAddress'].iteritems():
                self._store['ipaddress_' + str(vmname)] = item
                addresses.append(item)

            self._store['restore_options']['IPAddresses'] = ",".join(addresses)

            restore_options['Nodenames'] = None
            hostnames = []
            if 'Nodename' in restore_options:
                for vmname, hostname in restore_options['Nodename'].iteritems():
                    if hostname == "":
                        self._store['hostname_'+str(vmname)] = vmname+"_restored"
                    else:
                        self._store['hostname_'+str(vmname)] = hostname
                    hostnames.append(self._store['hostname_'+str(vmname)])
            else:
                for index, item in enumerate(self._store['instances']):
                    self._store['hostname_'+str(index)] = item['vm_name'] + "_restored"
                    hostnames.append(item['vm_name'] + "_restored")
    
            self._store['restore_options']['Nodenames'] = ",".join(hostnames)

            super(CassandraRestore, self).initflow(pre_poweron=LinearCassandraRestoreNodes(self))
        else:
            super(CassandraRestore, self).initflow(pre_poweron=lf.Flow("cassandrarestoreuf"))

    def execute(self):
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
        restore = pickle.loads(self._store['restore']['pickle'].encode('ascii','ignore'))
        if 'type' in restore and restore['type'] == "vmware":
            compute_service = nova.API(production=True)
            search_opts = {}
            search_opts['deep_discover'] = '1'
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            compute_service.get_servers(cntx, search_opts=search_opts)
        

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

