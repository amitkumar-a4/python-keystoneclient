# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Workflow for taking snapshot of mongodb instances
"""

import contextlib
import logging
import os
import random
import sys
import time

import datetime 
import pymongo
from pymongo import MongoClient
from pymongo import MongoReplicaSetClient
from pymongo import MongoClient, ReadPreference

import vmtasks

logging.basicConfig(level=logging.ERROR)

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)

from taskflow import engines
from taskflow.utils import misc
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import graph_flow as gf
from taskflow import task
from taskflow.utils import reflection

#from workloadmgr import exception
# 
# Function that create the connection to the mongos server to be use as
# primary source of information in order to pick the servers. host, port
# user and password should be fed into the flow and other tasks should use
# them as needed.
#
def connect_server(host, port, user, password, verbose=False):
    try:
        if user!="":
            auth = "mongodb://" + user + ":" + password + "@"
        else:
            auth=""
        connection = MongoClient(auth + host,port)
        if verbose:
            print "Connected to ", host, " on port ",port, "..."

    except Exception, e:
        print "Oops!  There was an error.  Try again..."
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
        print "\tOops!  There was an error.  Try again..."
        print "\t",e

class DisableProfiling(task.Task):

   def execute(self, host, port, username, password):
       self.client = connect_server(host, port, username, password)
       # Make sure profile is disabled, but also save current
       # profiling state in the flow record? so revert as well
       # as ResumeDB task sets the right profiling level
       print "DisableProfiling:"
       dbmap = self.client.admin.command("getShardMap")
       cfgsrvs = dbmap["map"]["config"].split(",")

       cfghost = cfgsrvs[0].split(":")[0]
       cfgport = cfgsrvs[0].split(":")[1]
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
       print "EnableProfiling"
       self.client = connect_server(host, port, username, password)

       dbmap = self.client.admin.command("getShardMap")
       cfgsrvs = dbmap["map"]["config"].split(",")

       cfghost = cfgsrvs[0].split(":")[0]
       cfgport = cfgsrvs[0].split(":")[1]
       self.cfgclient = connect_server(cfghost, int(cfgport), username, password)

       # Read profile level from the flow record?
       self.cfgclient.admin.set_profiling_level(proflevel)


class PauseDBInstance(task.Task):

   def execute(self, h, username, password):
       print "PauseDBInstance"
       # Flush the database and hold the write # lock the instance.
       host_info = h["secondaryReplica"].split(":")
       self.client = connect_server(host_info[0], int(host_info[1]), username, password)
       self.client.fsync(lock = True)
 
       # Add code to wait until the fsync operations is complete

   def revert(self, *args, **kwargs):
       # Resume DB
       self.client.unlock()


class ResumeDBInstance(task.Task):

   def execute(self, h, username, password):
       print "ResumeDBInstance"
       # Pause the DB
       host_info = h["secondaryReplica"].split(":")
       self.client = connect_server(host_info[0], int(host_info[1]), username, password)
       self.client.unlock()

class PauseBalancer(task.Task):

   def execute(self, host, port, username, password):
       print "PauseBalancer"
       self.client = connect_server(host, port, username, password)
       # Pause the DB
       db = self.client.config

       db.settings.update({"_id": "balancer"}, {"$set": {"stopped": True}}, true);
       balancer_info = db.locks.find_one({"_id": "balancer"})
       while int(str(balancer_info["state"])) > 0:
           print "\t\twaiting for migration"
           balancer_info = db.locks.find_one({"_id": "balancer"})

   def revert(self, *args, **kwargs):
       # Resume DB
       db = self.client.config
       db.settings.update({"_id": "balancer"}, {"$set": {"stopped": False}});

class ResumeBalancer(task.Task):

   def execute(self, host, port, username, password):
       print "ResumeBalancer"
       self.client = connect_server(host, port, username, password)
       # Resume DB

       db = self.client.config
       db.settings.update({"_id": "balancer"}, {"$set": {"stopped": False}});

class ShutdownConfigServer(task.Task):

    #
    #db.runCommand("getShardMap")
    #{
    #"map" : {
        #"node2:27021" : "node2:27021",
        #"node3:27021" : "node3:27021",
        #"node4:27021" : "node4:27021",
        #"config" : "node2:27019,node3:27019,node4:27019",
        #"shard0000" : "node2:27021",
        #"shard0001" : "node3:27021",
        #"shard0002" : "node4:27021"
    #},
    #"ok" : 1
   #}
   #"""
   def execute(self, host, port, username, password):
       # Get the list of config servers 
       # shutdown one of them
       self.client = connect_server(host, port, username, password)

       dbmap = self.client.admin.command("getShardMap")
       cfgsrvs = dbmap["map"]["config"].split(",")

       cfghost = cfgsrvs[0].split(":")[0]
       cfgport = cfgsrvs[0].split(":")[1]
       self.cfgclient = connect_server(cfghost, int(cfgport), username, password)

       #self.cfgclient.admin.command("shutdown")
       #self.cfgclient.admin.command("getCmdLineOpts")
       print "ShutdownConfigServer"

       # Also make sure the config server command line operations are saved
       return cfgsrvs[0]

   def revoke(self, *args, **kwargs):
       # Make sure all config servers are resumed
       cfghost = cfgsrvs[0].split(":")[0]
       cfgport = cfgsrvs[0].split(":")[1]
       #ssh into the cfg host and start the config server
       print "ShutdownConfigServer:revert"

class ResumeConfigServer(task.Task):

   def execute(self, cfgsrv, username, password):
       # Make sure all config servers are resumed
       cfghost = cfgsrv.split(":")[0]
       cfgport = cfgsrv.split(":")[1]
       #ssh into the cfg host and start the config server
       print "ResumeConfigServer"

# Assume there is no ordering dependency between instances
# pause each VM in parallel.
def PauseDBInstances(hosts_list):
    flow = uf.Flow("PauseDBInstances")
 
    for index, h in enumerate(hosts_list):
        host_info = h["secondaryReplica"].split(":")
        flow.add(PauseDBInstance("PauseDBInstance" + h["secondaryReplica"], rebind=["secondary_" + str(index), "username", "password"]))

    return flow

def ResumeDBInstances(hosts_list):
    flow = uf.Flow("ResumeDBInstances")
 
    for index, h in enumerate(hosts_list):
        host_info = h["secondaryReplica"].split(":")
        flow.add(ResumeDBInstance("ResumeDBInstance" + h["secondaryReplica"], rebind=["secondary_" + str(index), "username", "password"]))

    return flow

#
# MongoDB flow is an directed acyclic flow. 
# :param host - One of the mongo db node in the cluster that has mongos 
#               service running and will be used to discover the mongo db
#               shards, their replicas etc
# : port - port at which mongos service is running
# : usename/password - username and password to authenticate to the database
#
                 
def MongoDBflow(host, port, username, password):
    #
    # Creating connection to mongos server
    #
    print "Connecting to mongos server ", host
    connection = connect_server(host, port, username, password)
    print ""

    #
    # Getting sharding information
    #
    print "Getting sharding configuration"
    shards = getShards(connection)
    print ""

    #
    # Getting the secondaries list
    #
    hosts_to_backup = []
    for s in shards:
        hosts = str(s["host"])
        hosts = hosts.replace(str(s["_id"]), "").strip()
        hosts = hosts.replace("/", "").strip()
        print "Getting secondary from hosts in ", hosts
        # Get the replica set for each shard
        c = MongoClient(hosts,
                    read_preference=ReadPreference.SECONDARY)
        status = c.admin.command("replSetGetStatus")
        hosts_list = []
        for m in status["members"]:
           if m["stateStr"] == "SECONDARY":
              hosts_to_backup.append({"replicaSetName": status["set"], "secondaryReplica": m["name"]})
              break
    
    for index,item in enumerate(store["instanceids"]):
       store["instanceid_"+str(index)] = item

    for index, item in enumerate(hosts_to_backup):
       store["secondary_"+str(index)] = item

    #
    # Creating prefix to identify the backup to be build.
    #
    today = datetime.datetime.now()
    prefix_backup = str(today.strftime("%Y%m%d%H%M%S"))

    #
    # Backing up the servers.
    #
    print "Starting backup flow ..."
    print ""
    
    flow = lf.Flow("mongodbwf")

    # Add disable profile task. Stopping balancer fails if profile process
    # is running
    flow.add(DisableProfiling("DisableProfiling", provides="proflevel"))

    # This will be a flow that needs to be added to mongo db flow.
    # This is a flow that pauses all related VMs in unordered pattern
    flow.add(PauseDBInstances(hosts_to_backup))

    flow.add(ShutdownConfigServer("ShutdownConfigServer", provides="cfgsrv"))

    # This is an unordered pausing of VMs. This flow is created in
    # common tasks library. This routine takes instance ids from 
    # openstack. Workload manager should provide the list of 
    # instance ids
    flow.add(vmtasks.UnorderedPauseVMs(store["instanceids"]))

    # This is again unorder snapshot of VMs. This flow is implemented in
    # common tasks library
    flow.add(vmtasks.UnorderedSnapshotVMs(store["instanceids"]))

    flow.add(vmtasks.UnorderedResumeVMs(store["instanceids"]))

    # Restart the config servers so metadata changes can happen
    flow.add(ResumeConfigServer("ResumeConfigServer"))

    # unlock all locekd replicas so it starts receiving all updates from primary and
    # will eventually get into sync with primary
    flow.add(ResumeDBInstances(hosts_to_backup))

    # enable profiling to the level before the flow started
    flow.add(EnableProfiling("EnableProfiling"))

    # Now lazily copy the snapshots of VMs to tvault appliance
    flow.add(vmtasks.UnorderedUploadSnapshots(store["instanceids"]))

    # block commit any changes back to the snapshot
    flow.add(vmtasks.UnorderedBlockCommit(store["instanceids"]))

    return flow

# Provide the initial variable inputs using a storage dictionary.
#
store = {
    "instanceids": ["35d1b6ef-2841-46ce-9728-80c7e780afcc", 
                    "8393232c-a8a7-4a8b-9968-d65a9bd54d1c"],
    "host": "cloudvault4",
    "port": 27017,
    "username": "",
    "password": "",
}

flow = MongoDBflow(store["host"], store["port"], store["username"], store["password"])
result = engines.run(flow, engine_conf='parallel', store=store)
