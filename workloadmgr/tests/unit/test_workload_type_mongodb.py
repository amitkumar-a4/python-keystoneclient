'''
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.

import __builtin__
import contextlib
import datetime
import os
import sys
import shutil
import socket
import tempfile
import paramiko
import eventlet
import mock
import mox
from mox import IsA
from mox import IgnoreArg
from mox import In
import StringIO
import datetime
import time

from oslo.config import cfg
import bson
from bson.timestamp import Timestamp

import pymongo
from pymongo import MongoClient
from pymongo import MongoReplicaSetClient
from pymongo import MongoClient, ReadPreference

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common.rpc import amqp

from workloadmgr.compute import nova
from workloadmgr.tests import utils as tests_utils

from workloadmgr.workloads.api import API
from workloadmgr.workflows import mongodbflow
from workloadmgr.workflows import vmtasks_openstack
from workloadmgr.workflows import vmtasks
from workloadmgr.vault import vault
from workloadmgr.tests.swift import fake_swift_client

CONF = cfg.CONF

mongodb_shards = [{u'host': u'replica1/mongodb1:27021,mongodb2:27021,mongodb3:27021', u'_id': u'replica1'},
                  {u'host': u'replica2/mongodb1:27022,mongodb2:27022,mongodb3:27022', u'_id': u'replica2'},
                  {u'host': u'replica3/mongodb1:27023,mongodb2:27023,mongodb3:27023', u'_id': u'replica3'},
                  {u'host': u'replica4/mongodb4:27024', u'_id': u'replica4'},]

shardmap = {u'map': {u'replica4': u'replica4/mongodb4:27024', u'replica3/mongodb1:27023,mongodb2:27023,mongodb3:27023': u'replica3/mongodb1:27023,mongodb2:27023,mongodb3:27023', u'replica1': u'replica1/mongodb1:27021,mongodb2:27021,mongodb3:27021', u'replica2': u'replica2/mongodb1:27022,mongodb2:27022,mongodb3:27022', u'replica3': u'replica3/mongodb1:27023,mongodb2:27023,mongodb3:27023', u'mongodb1:27022': u'replica2/mongodb1:27022,mongodb2:27022,mongodb3:27022', u'mongodb1:27023': u'replica3/mongodb1:27023,mongodb2:27023,mongodb3:27023', u'mongodb1:27021': u'replica1/mongodb1:27021,mongodb2:27021,mongodb3:27021', u'mongodb2:27021': u'replica1/mongodb1:27021,mongodb2:27021,mongodb3:27021', u'replica2/mongodb1:27022,mongodb2:27022,mongodb3:27022': u'replica2/mongodb1:27022,mongodb2:27022,mongodb3:27022', u'mongodb2:27023': u'replica3/mongodb1:27023,mongodb2:27023,mongodb3:27023', u'mongodb2:27022': u'replica2/mongodb1:27022,mongodb2:27022,mongodb3:27022', u'replica4/mongodb4:27024': u'replica4/mongodb4:27024', u'replica1/mongodb1:27021,mongodb2:27021,mongodb3:27021': u'replica1/mongodb1:27021,mongodb2:27021,mongodb3:27021', u'mongodb4:27024': u'replica4/mongodb4:27024', u'config': u'mongodb1:27019,mongodb2:27019,mongodb3:27019', u'mongodb3:27021': u'replica1/mongodb1:27021,mongodb2:27021,mongodb3:27021', u'mongodb3:27022': u'replica2/mongodb1:27022,mongodb2:27022,mongodb3:27022', u'mongodb3:27023': u'replica3/mongodb1:27023,mongodb2:27023,mongodb3:27023'}, u'ok': 1.0}

cfgcmdlineopts = {u'ok': 1.0, u'parsed': {u'sharding': {u'configDB': u'mongodb1:27019,mongodb2:27019,mongodb3:27019'}, u'processManagement': {u'fork': True}, u'systemLog': {u'path': u'/dev/null', u'destination': u'file'}}, u'argv': [u'mongos', u'--fork', u'--logpath', u'/dev/null', u'--configdb', u'mongodb1:27019,mongodb2:27019,mongodb3:27019']}

repl1Status = {u'date': datetime.datetime(2014, 9, 12, 2, 36, 23), u'myState': 1, u'set': u'replica1', u'ok': 1.0, u'members': [{u'uptime': 2667, u'optime': Timestamp(1399319851, 1), u'name': u'mongodb1:27021', u'self': True, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 57, 31), u'electionTime': Timestamp(1410487024, 1), u'state': 1, u'health': 1.0, u'stateStr': u'PRIMARY', u'_id': 0, u'electionDate': datetime.datetime(2014, 9, 12, 1, 57, 4)}, {u'uptime': 2375, u'optime': Timestamp(1399319851, 1), u'name': u'mongodb2:27021', u'pingMs': 0, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 57, 31), u'syncingTo': u'mongodb1:27021', u'state': 2, u'health': 1.0, u'stateStr': u'SECONDARY', u'lastHeartbeatRecv': datetime.datetime(2014, 9, 12, 2, 36, 21), u'_id': 1, u'lastHeartbeat': datetime.datetime(2014, 9, 12, 2, 36, 22)}, {u'uptime': 2198, u'optime': Timestamp(1399319851, 1), u'name': u'mongodb3:27021', u'pingMs': 0, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 57, 31), u'syncingTo': u'mongodb1:27021', u'state': 2, u'health': 1.0, u'stateStr': u'SECONDARY', u'lastHeartbeatRecv': datetime.datetime(2014, 9, 12, 2, 36, 22), u'_id': 2, u'lastHeartbeat': datetime.datetime(2014, 9, 12, 2, 36, 22)}]}

repl2Status = {u'date': datetime.datetime(2014, 9, 12, 2, 37, 46), u'myState': 1, u'set': u'replica2', u'ok': 1.0, u'members': [{u'uptime': 2465, u'optime': Timestamp(1399319872, 1), u'name': u'mongodb2:27022', u'pingMs': 0, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 57, 52), u'syncingTo': u'mongodb1:27022', u'state': 2, u'health': 1.0, u'stateStr': u'SECONDARY', u'lastHeartbeatRecv': datetime.datetime(2014, 9, 12, 2, 37, 45), u'_id': 0, u'lastHeartbeat': datetime.datetime(2014, 9, 12, 2, 37, 46)}, {u'uptime': 2290, u'optime': Timestamp(1399319872, 1), u'name': u'mongodb3:27022', u'pingMs': 0, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 57, 52), u'syncingTo': u'mongodb1:27022', u'state': 2, u'health': 1.0, u'stateStr': u'SECONDARY', u'lastHeartbeatRecv': datetime.datetime(2014, 9, 12, 2, 37, 45), u'_id': 1, u'lastHeartbeat': datetime.datetime(2014, 9, 12, 2, 37, 46)}, {u'uptime': 2749, u'optime': Timestamp(1399319872, 1), u'name': u'mongodb1:27022', u'self': True, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 57, 52), u'electionTime': Timestamp(1410487014, 1), u'state': 1, u'health': 1.0, u'stateStr': u'PRIMARY', u'_id': 2, u'electionDate': datetime.datetime(2014, 9, 12, 1, 56, 54)}]}

repl3Status = {u'date': datetime.datetime(2014, 9, 12, 2, 38, 19), u'myState': 1, u'set': u'replica3', u'ok': 1.0, u'members': [{u'uptime': 2324, u'optime': Timestamp(1399319894, 1), u'name': u'mongodb3:27023', u'pingMs': 0, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 58, 14), u'syncingTo': u'mongodb1:27023', u'state': 2, u'health': 1.0, u'stateStr': u'SECONDARY', u'lastHeartbeatRecv': datetime.datetime(2014, 9, 12, 2, 38, 17), u'_id': 0, u'lastHeartbeat': datetime.datetime(2014, 9, 12, 2, 38, 18)}, {u'uptime': 2778, u'optime': Timestamp(1399319894, 1), u'name': u'mongodb1:27023', u'self': True, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 58, 14), u'electionTime': Timestamp(1410487030, 1), u'state': 1, u'health': 1.0, u'stateStr': u'PRIMARY', u'_id': 1, u'electionDate': datetime.datetime(2014, 9, 12, 1, 57, 10)}, {u'uptime': 2485, u'optime': Timestamp(1399319894, 1), u'name': u'mongodb2:27023', u'pingMs': 0, u'optimeDate': datetime.datetime(2014, 5, 5, 19, 58, 14), u'syncingTo': u'mongodb1:27023', u'state': 2, u'health': 1.0, u'stateStr': u'SECONDARY', u'lastHeartbeatRecv': datetime.datetime(2014, 9, 12, 2, 38, 18), u'_id': 2, u'lastHeartbeat': datetime.datetime(2014, 9, 12, 2, 38, 18)}]}

repl4Status = {u'date': datetime.datetime(2014, 9, 12, 2, 38, 49), u'myState': 1, u'set': u'replica4', u'ok': 1.0, u'members': [{u'uptime': 3063, u'optime': Timestamp(1399407548, 1), u'name': u'mongodb4:27024', u'self': True, u'optimeDate': datetime.datetime(2014, 5, 6, 20, 19, 8), u'electionTime': Timestamp(1410486509, 1), u'state': 1, u'health': 1.0, u'stateStr': u'PRIMARY', u'_id': 0, u'electionDate': datetime.datetime(2014, 9, 12, 1, 48, 29)}]}

class BaseWorkloadTypeMongoDBTestCase(test.TestCase):
    """Test Case for mongodb workload Type."""
    def setUp(self):
        super(BaseWorkloadTypeMongoDBTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.workload = importutils.import_object(CONF.workloads_manager)
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

        self.workload_params = {
            'display_name': 'mongodb_workload_type',
            'display_description': 'this is a mongodb workload_type',
            'status': 'creating',
            'is_public': True,
            'metadata': {
                         "HostUsername": "string",
                         "HostPassword": "string",
                         "HostSSHPort": "string",
                         "DBHost": "string",
                         "DBPort": "string",
                         "DBUser": "string",
                         "DBPassword": "password",
                         "RunAsRoot": "bool",
                         "capabilities": "string",
                        }}

        self.store = { 'connection': CONF.sql_connection,
                       'source_platform': "openstack",
                       "HostUsername": "ubuntu",
                       "HostPassword": "project1",
                       "HostSSHPort": "22",
                       "DBHost": "mongodb1",
                       "DBPort": "27019",
                       "DBUser": "",
                       "DBPassword": "",
                       "RunAsRoot": True,
                       "capabilities": "discover:topology",
                     }
        self.store["context"] = self.context.__dict__
        self.store["context"]["conf"] = None
        self.store['context']['read_deleted']=self.store['context']['_read_deleted']
        self.store["snapshot"] = {'status': u'starting',
                                  'project_id': u'fake_project',
                                  'user_id': u'fake_user',
                                  'deleted': False, 'uploaded_size': 0L,
                                  'created_at': datetime.datetime(2014, 9, 9, 13, 2, 38),
                                  'progress_percent': 0L,
                                  'updated_at': datetime.datetime(2014, 9, 9, 13, 2, 38),
                                  'display_description': u'User Initiated Snapshot operation',
                                  'error_msg': None,
                                  'progress_msg': u'Snapshot of workload is starting',
                                  'snapshot_type': 'incremental',
                                  'workload_id': u'd296c248-d206-4837-b719-0abed920281d',
                                  'display_name': u'User-Initiated',
                                  'deleted_at': None,
                                  'id': u'9ed247f2-c117-4353-88b2-44b61548116b',
                                  'size': 0L}


    def tearDown(self):
        super(BaseWorkloadTypeMongoDBTestCase, self).tearDown()

    def test_create_delete_workload_type(self):
        """Test workload can be created and deleted."""

        workload_type = self.workloadAPI.workload_type_create(self.context,
                        self.workload_params['display_name'],
                        self.workload_params['display_description'],
                        self.workload_params['is_public'],
                        self.workload_params['metadata'],)

        workload_type = self.db.workload_type_get(self.context,
                                                  workload_type['id'])
        workload_type_id = workload_type['id']
        self.assertEqual(workload_type_id,
                         self.db.workload_type_get(self.context,
                                                   workload_type_id).id)

        self.assertEqual(workload_type['status'], 'available')
        self.assertEqual(workload_type['display_name'], self.workload_params['display_name'])
        self.assertEqual(workload_type['display_description'], self.workload_params['display_description'])
        self.assertEqual(workload_type['is_public'], self.workload_params['is_public'])
        for m in workload_type['metadata']:
            self.assertEqual(self.workload_params['metadata'][m.key], m.value)


        self.workloadAPI.workload_type_delete(self.context, workload_type_id)
        workload_type = db.workload_type_get(self.context, workload_type_id)
        self.assertEqual(workload_type['status'], 'deleted')
        self.assertRaises(exception.NotFound,
                          db.workload_type_get,
                          self.context,
                          workload_type_id)

    def test_create_workload_type_invalid_metadata(self):
        """Test workloadtype with invalid metadata"""

        workload_type = self.workloadAPI.workload_type_create(self.context,
                            'test_workload',
                            'this is a test workload_type',
                            False, {})
        workload_type_id = workload_type['id']
        expected = {
            'status': 'available',
            'display_name': 'test_workload',
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'workload_type': None,
            'user_id': 'fake',
            'is_public': True,
            'metadata': {},
        }
        self.assertEqual(workload_type_id,
                         self.db.workload_type_get(self.context,
                                                   workload_type_id).id)

        self.assertEqual(len(workload_type['metadata']), 0)
        self.workloadAPI.workload_type_delete(self.context, workload_type_id)
        workload_type = db.workload_type_get(self.context, workload_type_id)
        self.assertEqual(workload_type['status'], 'deleted')
        self.assertRaises(exception.NotFound,
                          db.workload_type_get,
                          self.context,
                          workload_type_id)

    @mock.patch.object(mongodbflow, 'connect_server')
    def test_mongodb_pausedb_instance_execute(self,
                                              _mock_connect_server):
        h = {'replicaSetName': u'replica1', 'secondaryReplica': u'mongodb2:27021'}
        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            instance = mclient.return_value
            mclient.is_locked = True
            mclient.fsync.return_value = True
            admin = mdb.return_value

            instance.admin = admin
            _mock_connect_server.return_value = instance

            mdbflow = mongodbflow.PauseDBInstance()
            mdbflow.execute(h, self.store['DBUser'], self.store['DBPassword'])

            self.assertEqual(mclient.is_locked, True)
            mdbflow.client.fsync.assert_called_with(lock=True)

    @mock.patch.object(mongodbflow, 'connect_server')
    def test_mongodb_pausedb_instance_revert(self,
                                             _mock_connect_server):
        h = {'replicaSetName': u'replica1', 'secondaryReplica': u'mongodb2:27021'}
        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            instance = mclient.return_value
            mclient.is_locked = True
            mclient.fsync.return_value = True
            admin = mdb.return_value

            instance.admin = admin
            _mock_connect_server.return_value = instance

            mdbflow = mongodbflow.PauseDBInstance()
            mdbflow.execute(h, self.store['DBUser'], self.store['DBPassword'])
            mdbflow.revert()

            self.assertEqual(mclient.is_locked, True)
            mdbflow.client.unlock.assert_called_with()

    @mock.patch.object(mongodbflow, 'connect_server')
    def test_mongodb_resumedb_instance_execute(self,
                                               _mock_connect_server):
        h = {'replicaSetName': u'replica1', 'secondaryReplica': u'mongodb2:27021'}
        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            instance = mclient.return_value
            admin = mdb.return_value

            instance.admin = admin
            _mock_connect_server.return_value = instance

            mdbflow = mongodbflow.ResumeDBInstance()
            mdbflow.execute(h, self.store['DBUser'], self.store['DBPassword'])

            mdbflow.client.unlock.assert_called_with()

    @mock.patch.object(mongodbflow, 'connect_server')
    @mock.patch.object(paramiko, 'SSHClient')
    def test_mongodb_shutdown_configsvr_execute(self,
                                                _mock_sshclient,
                                                _mock_connect_server):
        class sshclient(object):

              def load_system_host_keys(self):
                  return
              def set_missing_host_key_policy(self, policy):
                  return

              def connect(self, hostname, port, username, password):
                  self.hostname = hostname
                  self.port = port
                  self.username = username
                  self.password = password

              def exec_command(self, cmd):
                  eth = ""
                  if cmd == 'ifconfig eth0 | grep HWaddr':
                      if self.hostname == "mongodb1":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:5b:9b:bb'
                      elif self.hostname == "mongodb2":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:e3:97:ec'
                      elif self.hostname == "mongodb3":
                          eth =  'eth0      Link encap:Ethernet  HWaddr fa:16:3e:23:0f:ff'
                      elif self.hostname == "mongodb4":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:7c:0f:ae'
                      else:
                           raise "Invalid argument"
                  elif cmd == 'mongod --shutdown --port 27019 --configsvr':
                      eth = 'Success'
                  elif cmd == 'mongos --fork --logpath /dev/null --configdb '\
                              'mongodb1:27019,mongodb2:27019,mongodb3:27019 ':
                      eth = 'Success'
                  else:
                      raise "Invalid argument"

                  info1 = StringIO.StringIO(eth)
                  return (sys.stdin, info1, sys.stderr)

              def close(self):
                  return

        def create_sshclient():
            return sshclient()

        h = {'replicaSetName': u'replica1', 'secondaryReplica': u'mongodb2:27021'}
        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            def multicall(*args, **kwargs):
               if args[0] == 'replSetGetStatus':
                   x = statuses.pop()
                   statuses.insert(0, x)
                   return x
               elif args[0] == 'getShardMap':
                   return shardmap
               elif args[0] == 'getCmdLineOpts':
                   return cfgcmdlineopts
               else:
                   raise "Invalid command"
            instance = mclient.return_value
            admin = mdb.return_value
            instance.admin = admin
            admin.command.side_effect = multicall
            _mock_sshclient.side_effect = create_sshclient

            _mock_connect_server.return_value = instance

            mdbflow = mongodbflow.ShutdownConfigServer()

            x, y = mdbflow.execute(self.store['DBHost'], self.store['DBPort'],
                            self.store['DBUser'], self.store['DBPassword'],
                            self.store['HostUsername'], self.store['HostPassword'])


    def test_mongodb_shutdown_configsvr_revert(self):
        pass

    def test_mongodb_resume_configsvr_execute(self):
        pass

    def test_mongodb_disable_profiling_execute(self):
        pass

    def test_mongodb_disable_profiling_revert(self):
        pass

    def test_mongodb_enable_profiling_execute(self):
        pass

    def test_mongodb_pausedb_instances(self):
        pass

    def test_mongodb_resumedb_instances(self):
        pass

    def test_mongodb_get_shards(self):
        pass

    @mock.patch.object(mongodbflow, 'getShards')
    @mock.patch.object(mongodbflow, 'connect_server')
    @mock.patch.object(paramiko, 'SSHClient')
    def test_mongodb_get_vms(self,
                             _mock_sshclient,
                             _mock_connect_server,
                             _mock_getShards):

        class sshclient(object):

              def load_system_host_keys(self):
                  return
              def set_missing_host_key_policy(self, policy):
                  return

              def connect(self, hostname, port, username, password):
                  self.hostname = hostname
                  self.port = port
                  self.username = username
                  self.password = password

              def exec_command(self, cmd):
                  assert cmd == 'ifconfig eth0 | grep HWaddr'

                  eth = ""
                  if self.hostname == "mongodb1":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:5b:9b:bb'
                  elif self.hostname == "mongodb2":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:e3:97:ec'
                  elif self.hostname == "mongodb3":
                      eth =  'eth0      Link encap:Ethernet  HWaddr fa:16:3e:23:0f:ff'
                  elif self.hostname == "mongodb4":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:7c:0f:ae'
                  else:
                       raise "Invalid argument"

                  info1 = StringIO.StringIO(eth)
                  return (sys.stdin, info1, sys.stderr)
              def close(self):
                  return

        def create_sshclient():
            return sshclient()

        def fake_get_servers(self, cntx, **kwargs):
            return tests_utils.build_mongodb_instances()

        def fake_get_hypervisors(self, cntx):
            return tests_utils.build_mongodb_hypervisors()

        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            instance = mclient.return_value
            admin = mdb.return_value

            instance.admin = admin

            _mock_connect_server.return_value = instance
            _mock_getShards.return_value = mongodb_shards
            _mock_sshclient.side_effect = create_sshclient

            self.stubs.Set(nova.API, 'get_servers', fake_get_servers)
            self.stubs.Set(nova.API, 'get_hypervisors', fake_get_hypervisors)

            vms = mongodbflow.get_vms(self.context, self.store['DBHost'],
                                self.store['DBPort'], self.store['DBUser'],
                                self.store['DBPassword'], self.store['HostSSHPort'],
                                self.store['HostUsername'], self.store['HostPassword'])

            self.assertEqual(4, len(vms))

    @mock.patch.object(mongodbflow, 'getShards')
    @mock.patch.object(mongodbflow, 'connect_server')
    def test_mongodb_secondary_hosts_to_backup(self,
                                            _mock_connect_server,
                                            _mock_getShards):

        statuses = [repl1Status, repl2Status, repl3Status, repl4Status]
        replnum = len(statuses)

        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            def multicall(*args, **kwargs):
               x = statuses.pop()
               statuses.insert(0, x)
               return x

            instance = mclient.return_value
            admin = mdb.return_value

            admin.command.side_effect = multicall
            instance.admin = admin

            _mock_connect_server.return_value = instance
            _mock_getShards.return_value = mongodb_shards

            hosts = mongodbflow.secondaryhosts_to_backup(self.context,
                                             self.store['DBHost'],
                                             self.store['DBPort'],
                                             self.store['HostUsername'],
                                             self.store['HostPassword'])
            self.assertDictMatch(hosts[0], {'replicaSetName': u'replica3',
                                            'secondaryReplica': u'mongodb3:27023'})
            self.assertDictMatch(hosts[1], {'replicaSetName': u'replica2',
                                            'secondaryReplica': u'mongodb2:27022'})
            self.assertDictMatch(hosts[2], {'replicaSetName': u'replica1',
                                            'secondaryReplica': u'mongodb2:27021'})
            self.assertEqual(len(hosts), replnum)


    @mock.patch.object(mongodbflow, 'getShards')
    @mock.patch.object(mongodbflow, 'connect_server')
    @mock.patch.object(paramiko, 'SSHClient')
    def test_mongodb_initflow(self,
                              _mock_sshclient,
                              _mock_connect_server,
                              _mock_getShards):

        statuses = [repl1Status, repl2Status, repl3Status, repl4Status]
        replnum = len(statuses)
        class sshclient(object):

              def load_system_host_keys(self):
                  return
              def set_missing_host_key_policy(self, policy):
                  return

              def connect(self, hostname, port, username, password):
                  self.hostname = hostname
                  self.port = port
                  self.username = username
                  self.password = password

              def exec_command(self, cmd):
                  assert cmd == 'ifconfig eth0 | grep HWaddr'

                  eth = ""
                  if self.hostname == "mongodb1":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:5b:9b:bb'
                  elif self.hostname == "mongodb2":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:e3:97:ec'
                  elif self.hostname == "mongodb3":
                      eth =  'eth0      Link encap:Ethernet  HWaddr fa:16:3e:23:0f:ff'
                  elif self.hostname == "mongodb4":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:7c:0f:ae'
                  else:
                       raise "Invalid argument"

                  info1 = StringIO.StringIO(eth)
                  return (sys.stdin, info1, sys.stderr)
              def close(self):
                  return

        def create_sshclient():
            return sshclient()

        def fake_get_servers(self, cntx, **kwargs):
            return tests_utils.build_mongodb_instances()

        def fake_get_hypervisors(self, cntx):
            return tests_utils.build_mongodb_hypervisors()

        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            def multicall(*args, **kwargs):
               return statuses.pop()

            instance = mclient.return_value
            admin = mdb.return_value
            admin.command.side_effect = multicall

            instance.admin = admin

            _mock_connect_server.return_value = instance
            _mock_getShards.return_value = mongodb_shards
            _mock_sshclient.side_effect = create_sshclient

            self.stubs.Set(nova.API, 'get_servers', fake_get_servers)
            self.stubs.Set(nova.API, 'get_hypervisors', fake_get_hypervisors)

            mdbflow = mongodbflow.MongoDBWorkflow("test_mongodb", self.store)
            flow = mdbflow.initflow()

    @mock.patch.object(mongodbflow, 'getShards')
    @mock.patch.object(mongodbflow, 'connect_server')
    @mock.patch.object(paramiko, 'SSHClient')
    def test_mongodb_details(self,
                              _mock_sshclient,
                              _mock_connect_server,
                              _mock_getShards):

        statuses = [repl1Status, repl2Status, repl3Status, repl4Status]
        replnum = len(statuses)
        class sshclient(object):

              def load_system_host_keys(self):
                  return
              def set_missing_host_key_policy(self, policy):
                  return

              def connect(self, hostname, port, username, password):
                  self.hostname = hostname
                  self.port = port
                  self.username = username
                  self.password = password

              def exec_command(self, cmd):
                  assert cmd == 'ifconfig eth0 | grep HWaddr'

                  eth = ""
                  if self.hostname == "mongodb1":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:5b:9b:bb'
                  elif self.hostname == "mongodb2":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:e3:97:ec'
                  elif self.hostname == "mongodb3":
                      eth =  'eth0      Link encap:Ethernet  HWaddr fa:16:3e:23:0f:ff'
                  elif self.hostname == "mongodb4":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:7c:0f:ae'
                  else:
                       raise "Invalid argument"

                  info1 = StringIO.StringIO(eth)
                  return (sys.stdin, info1, sys.stderr)
              def close(self):
                  return

        def create_sshclient():
            return sshclient()

        def fake_get_servers(self, cntx, **kwargs):
            return tests_utils.build_mongodb_instances()

        def fake_get_hypervisors(self, cntx):
            return tests_utils.build_mongodb_hypervisors()

        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            def multicall(*args, **kwargs):
               return statuses.pop()

            instance = mclient.return_value
            admin = mdb.return_value
            admin.command.side_effect = multicall

            instance.admin = admin

            _mock_connect_server.return_value = instance
            _mock_getShards.return_value = mongodb_shards
            _mock_sshclient.side_effect = create_sshclient

            self.stubs.Set(nova.API, 'get_servers', fake_get_servers)
            self.stubs.Set(nova.API, 'get_hypervisors', fake_get_hypervisors)

            mdbflow = mongodbflow.MongoDBWorkflow("test_mongodb", self.store)
            mdbflow.initflow()
            workflow = mdbflow.details()
            self.assertEqual(4, len(workflow['workflow']['children']))
            self.assertEqual(4, len(workflow['workflow']['children'][0]['children'][0]['children']))
            self.assertEqual(3, len(workflow['workflow']['children'][1]['children']))
            self.assertEqual(9, len(workflow['workflow']['children'][2]['children']))
            self.assertEqual(3, len(workflow['workflow']['children'][3]['children']))
            # Beefup the validatation even further

    @mock.patch.object(mongodbflow, 'getShards')
    @mock.patch.object(mongodbflow, 'connect_server')
    @mock.patch.object(paramiko, 'SSHClient')
    def test_mongodb_discover(self,
                             _mock_sshclient,
                             _mock_connect_server,
                             _mock_getShards):

        class sshclient(object):

              def load_system_host_keys(self):
                  return
              def set_missing_host_key_policy(self, policy):
                  return

              def connect(self, hostname, port, username, password):
                  self.hostname = hostname
                  self.port = port
                  self.username = username
                  self.password = password

              def exec_command(self, cmd):
                  assert cmd == 'ifconfig eth0 | grep HWaddr'

                  eth = ""
                  if self.hostname == "mongodb1":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:5b:9b:bb'
                  elif self.hostname == "mongodb2":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:e3:97:ec'
                  elif self.hostname == "mongodb3":
                      eth =  'eth0      Link encap:Ethernet  HWaddr fa:16:3e:23:0f:ff'
                  elif self.hostname == "mongodb4":
                      eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:7c:0f:ae'
                  else:
                       raise "Invalid argument"

                  info1 = StringIO.StringIO(eth)
                  return (sys.stdin, info1, sys.stderr)
              def close(self):
                  return

        def create_sshclient():
            return sshclient()

        def fake_get_servers(self, cntx, **kwargs):
            return tests_utils.build_mongodb_instances()

        def fake_get_hypervisors(self, cntx):
            return tests_utils.build_mongodb_hypervisors()

        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            instance = mclient.return_value
            admin = mdb.return_value

            instance.admin = admin

            _mock_connect_server.return_value = instance
            _mock_getShards.return_value = mongodb_shards
            _mock_sshclient.side_effect = create_sshclient

            self.stubs.Set(nova.API, 'get_servers', fake_get_servers)
            self.stubs.Set(nova.API, 'get_hypervisors', fake_get_hypervisors)

            mdbflow = mongodbflow.MongoDBWorkflow("test_mongodb", self.store)
            vms = mdbflow.discover()['instances']
            self.assertEqual(4, len(vms))

    @mock.patch.object(mongodbflow, 'getShards')
    @mock.patch.object(mongodbflow, 'connect_server')
    @mock.patch.object(paramiko, 'SSHClient')
    def test_mongodb_execute(self,
                             _mock_sshclient,
                             _mock_connect_server,
                             _mock_getShards):

        statuses = [repl1Status, repl2Status, repl3Status, repl4Status]
        replnum = len(statuses)
        class sshclient(object):

              def load_system_host_keys(self):
                  return
              def set_missing_host_key_policy(self, policy):
                  return

              def connect(self, hostname, port, username, password):
                  self.hostname = hostname
                  self.port = port
                  self.username = username
                  self.password = password

              def exec_command(self, cmd):

                  eth = ""
                  if cmd == 'ifconfig eth0 | grep HWaddr':
                      if self.hostname == "mongodb1":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:5b:9b:bb'
                      elif self.hostname == "mongodb2":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:e3:97:ec'
                      elif self.hostname == "mongodb3":
                          eth =  'eth0      Link encap:Ethernet  HWaddr fa:16:3e:23:0f:ff'
                      elif self.hostname == "mongodb4":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:7c:0f:ae'
                      else:
                           raise "Invalid argument"
                  elif cmd == 'mongod --shutdown --port 27019 --configsvr':
                      eth = 'Success'
                  elif cmd == 'mongos --fork --logpath /dev/null --configdb '\
                              'mongodb1:27019,mongodb2:27019,mongodb3:27019 ':
                      eth = 'Success'
                  else:
                      raise "Invalid argument"

                  info1 = StringIO.StringIO(eth)
                  return (sys.stdin, info1, sys.stderr)
              def close(self):
                  return

        def create_sshclient():
            return sshclient()

        def fake_get_servers(self, cntx, **kwargs):
            return tests_utils.build_mongodb_instances()

        def fake_get_hypervisors(self, cntx):
            return tests_utils.build_mongodb_hypervisors()

        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            def multicall(*args, **kwargs):
               if args[0] == 'replSetGetStatus':
                   x = statuses.pop()
                   statuses.insert(0, x)
                   return x
               elif args[0] == 'getShardMap':
                   return shardmap
               elif args[0] == 'getCmdLineOpts':
                   return cfgcmdlineopts
               else:
                   raise "Invalid command"

            def taskfunc(*args):
               return

            def fake_data_size(*args):
               return 1024 * 1024 * 1024

            instance = mclient.return_value
            admin = mdb.return_value
            admin.command.side_effect = multicall

            instance.admin = admin

            self.store['snapshot'] = tests_utils.create_snapshot(self.context,
                                      'd296c248-d206-4837-b719-0abed920281d').__dict__
            self.store['snapshot'].pop('_sa_instance_state')

            _mock_connect_server.return_value = instance
            _mock_getShards.return_value = mongodb_shards
            _mock_sshclient.side_effect = create_sshclient

            self.stubs.Set(nova.API, 'get_servers', fake_get_servers)
            self.stubs.Set(nova.API, 'get_hypervisors', fake_get_hypervisors)

            self.stubs.Set(vmtasks_openstack, 'pre_snapshot_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm_networks', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm_flavors', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm_security_groups', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'pause_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'unpause_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'get_snapshot_data_size', fake_data_size)
            self.stubs.Set(vmtasks_openstack, 'upload_snapshot', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'post_snapshot', taskfunc)

            mdbflow = mongodbflow.MongoDBWorkflow("test_mongodb", self.store)
            mdbflow.initflow()
            workflow = mdbflow.execute()

    @mock.patch.object(mongodbflow, 'getShards')
    @mock.patch.object(mongodbflow, 'connect_server')
    @mock.patch.object(paramiko, 'SSHClient')
    def test_mongodb_execute_and_upload(self,
                                        _mock_sshclient,
                                        _mock_connect_server,
                                        _mock_getShards):

        statuses = [repl1Status, repl2Status, repl3Status, repl4Status]
        replnum = len(statuses)
        class sshclient(object):

              def load_system_host_keys(self):
                  return
              def set_missing_host_key_policy(self, policy):
                  return

              def connect(self, hostname, port, username, password):
                  self.hostname = hostname
                  self.port = port
                  self.username = username
                  self.password = password

              def exec_command(self, cmd):

                  eth = ""
                  if cmd == 'ifconfig eth0 | grep HWaddr':
                      if self.hostname == "mongodb1":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:5b:9b:bb'
                      elif self.hostname == "mongodb2":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:e3:97:ec'
                      elif self.hostname == "mongodb3":
                          eth =  'eth0      Link encap:Ethernet  HWaddr fa:16:3e:23:0f:ff'
                      elif self.hostname == "mongodb4":
                          eth = 'eth0      Link encap:Ethernet  HWaddr fa:16:3e:7c:0f:ae'
                      else:
                           raise "Invalid argument"
                  elif cmd == 'mongod --shutdown --port 27019 --configsvr':
                      eth = 'Success'
                  elif cmd == 'mongos --fork --logpath /dev/null --configdb '\
                              'mongodb1:27019,mongodb2:27019,mongodb3:27019 ':
                      eth = 'Success'
                  else:
                      raise "Invalid argument"

                  info1 = StringIO.StringIO(eth)
                  return (sys.stdin, info1, sys.stderr)
              def close(self):
                  return

        def create_sshclient():
            return sshclient()

        def fake_get_servers(self, cntx, **kwargs):
            return tests_utils.build_mongodb_instances()

        def fake_get_hypervisors(self, cntx):
            return tests_utils.build_mongodb_hypervisors()

        with contextlib.nested (
            mock.patch('pymongo.MongoClient'),
            mock.patch('pymongo.database.Database')
        ) as (mclient, mdb):
            def multicall(*args, **kwargs):
               if args[0] == 'replSetGetStatus':
                   x = statuses.pop()
                   statuses.insert(0, x)
                   return x
               elif args[0] == 'getShardMap':
                   return shardmap
               elif args[0] == 'getCmdLineOpts':
                   return cfgcmdlineopts
               else:
                   raise "Invalid command"

            def taskfunc(*args):
               return

            def fake_data_size(*args):
                return 1024 * 1024 * 1024
            def servicefunc(*args):
                return fake_swift_client.FakeSwiftClient()


            instance = mclient.return_value
            admin = mdb.return_value
            admin.command.side_effect = multicall

            instance.admin = admin

            self.store['snapshot'] = tests_utils.create_snapshot(self.context,
                                      'd296c248-d206-4837-b719-0abed920281d').__dict__
            self.store['snapshot'].pop('_sa_instance_state')

            _mock_connect_server.return_value = instance
            _mock_getShards.return_value = mongodb_shards
            _mock_sshclient.side_effect = create_sshclient

            self.stubs.Set(nova.API, 'get_servers', fake_get_servers)
            self.stubs.Set(nova.API, 'get_hypervisors', fake_get_hypervisors)
            self.stubs.Set(vault, 'get_vault_service', servicefunc)

            self.stubs.Set(vmtasks_openstack, 'pre_snapshot_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm_networks', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm_flavors', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm_security_groups', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'pause_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'snapshot_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'unpause_vm', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'get_snapshot_data_size', fake_data_size)
            self.stubs.Set(vmtasks_openstack, 'upload_snapshot', taskfunc)
            self.stubs.Set(vmtasks_openstack, 'post_snapshot', taskfunc)

            mdbflow = mongodbflow.MongoDBWorkflow("test_mongodb", self.store)
            mdbflow.initflow()
            workflow = mdbflow.execute()

            vmtasks.UploadSnapshotDBEntry(self.context,
                     db.snapshot_get(self.context, self.store['snapshot']['id']))
'''
