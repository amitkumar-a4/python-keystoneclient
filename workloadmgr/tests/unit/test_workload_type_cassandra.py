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

from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common.rpc import amqp

from workloadmgr.compute import nova
from workloadmgr.tests import utils as tests_utils

from workloadmgr.workloads.api import API
from workloadmgr.workflows import cassandraworkflow
from workloadmgr.workflows import vmtasks_openstack

CONF = cfg.CONF

class BaseWorkloadTypeCassandraTestCase(test.TestCase):
    """Test Case for cassandra workload Type."""
    def setUp(self):
        super(BaseWorkloadTypeCassandraTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.workload = importutils.import_object(CONF.workloads_manager)
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

        self.workload_params = {
            'display_name': 'cassandra_workload_type',
            'display_description': 'this is a cassandra workload_type',
            'status': 'creating',
            'is_public': True,
            'metadata': {"CassandraNode": "CassandraNode1",
                         "SSHPort": '22',
                         "Username": "ubuntu",
                         "Password": "password",
                         "capabilities": "discover:topology",}}

        self.store = { 'connection': CONF.sql_connection,
                       'CassandraNode': 'localhost',   # cassandra node
                       'SSHPort': '22', # ssh port of namenode
                       'Username': 'fake_user', # namenode user
                       'Password': 'fake_password', # namenode password if ssh
                                                    # key is not set
                       'source_platform': "openstack",
                     }
        self.store["context"] = self.context.__dict__
        self.store["context"]["conf"] = None
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

        info1str = '\
                Token            : (invoke with -T/--tokens to see all 256 tokens)\n\
                ID               : 7d62d900-f99d-4b88-8012-f06cb639fc02\n\
                Gossip active    : true\n\
                Thrift active    : true\n\
                Native Transport active: true\n\
                Load             : 130.46 KB\n\
                Generation No    : 1410136571\n\
                Uptime (seconds) : 181\n\
                Heap Memory (MB) : 86.78 / 992.00\n\
                Data Center      : 17\n\
                Rack             : 17\n\
                Exceptions       : 0\n\
                Key Cache        : size 1328 (bytes), capacity 51380224 (bytes), 61 hits, 77 requests, 0.792 recent hit rate, 14400 save period in seconds\n\
                Row Cache        : size 0 (bytes), capacity 0 (bytes), 0 hits, 0 requests, NaN recent hit rate, 0 save period in seconds\n\
                                  '
        self.info1 = StringIO.StringIO(info1str)
        self.info11 = StringIO.StringIO(info1str)

        info2str = '\
                Token            : (invoke with -T/--tokens to see all 256 tokens)\n\
                ID               : 75917649-6caa-4c66-b003-71c0eb8c09e8\n\
                Gossip active    : true\n\
                Thrift active    : true\n\
                Native Transport active: true\n\
                Load             : 121.07 KB\n\
                Generation No    : 1410136525\n\
                Uptime (seconds) : 274\n\
                Heap Memory (MB) : 29.66 / 992.00\n\
                Data Center      : 17\n\
                Rack             : 17\n\
                Exceptions       : 0\n\
                Key Cache        : size 1200 (bytes), capacity 51380224 (bytes), 78 hits, 92 requests, 0.848 recent hit rate, 14400 save period in seconds\n\
                Row Cache        : size 0 (bytes), capacity 0 (bytes), 0 hits, 0 requests, NaN recent hit rate, 0 save period in seconds\n\
                                  '
        self.info2 = StringIO.StringIO(info2str)
        self.info21 = StringIO.StringIO(info2str)

        info3str = '\
                Token            : (invoke with -T/--tokens to see all 256 tokens)\n\
                ID               : a03a1287-7d32-42ed-9018-8206fc295dd9\n\
                Gossip active    : true\n\
                Thrift active    : true\n\
                Native Transport active: true\n\
                Load             : 111.62 KB\n\
                Generation No    : 1410136541\n\
                Uptime (seconds) : 327\n\
                Heap Memory (MB) : 35.32 / 992.00\n\
                Data Center      : 17\n\
                Rack             : 17\n\
                Exceptions       : 0\n\
                Key Cache        : size 1344 (bytes), capacity 51380224 (bytes), 69 hits, 84 requests, 0.821 recent hit rate, 14400 save period in seconds\n\
                Row Cache        : size 0 (bytes), capacity 0 (bytes), 0 hits, 0 requests, NaN recent hit rate, 0 save period in seconds\n\
                                  '

        self.info3 = StringIO.StringIO(info3str)
        self.info31 = StringIO.StringIO(info3str)

        info4str = '\
                Token            : (invoke with -T/--tokens to see all 256 tokens)\n\
                ID               : f64ced33-2c01-40a3-9979-cf0a0b60d7af\n\
                Gossip active    : true\n\
                Thrift active    : true\n\
                Native Transport active: true\n\
                Load             : 80.18 KB\n\
                Generation No    : 1410136556\n\
                Uptime (seconds) : 372\n\
                Heap Memory (MB) : 54.36 / 992.00\n\
                Data Center      : 17\n\
                Rack             : 17\n\
                Exceptions       : 0\n\
                Key Cache        : size 1952 (bytes), capacity 51380224 (bytes), 85 hits, 97 requests, 0.876 recent hit rate, 14400 save period in seconds\n\
                Row Cache        : size 0 (bytes), capacity 0 (bytes), 0 hits, 0 requests, NaN recent hit rate, 0 save period in seconds\n\
                                  '
        self.info4 = StringIO.StringIO(info4str)
        self.info41 = StringIO.StringIO(info4str)

        statusiostr = '\
                Datacenter: 17\n\
                ==============\n\
                Status=Up/Down\n\
                |/ State=Normal/Leaving/Joining/Moving\n\
                --  Address       Load       Owns (effective)  Host ID                               Token                                    Rack\n\
                UN  172.17.17.19  130.46 KB  0.2%              7d62d900-f99d-4b88-8012-f06cb639fc02  -4300314010327621                        17\n\
                UN  172.17.17.21  111.62 KB  65.4%             a03a1287-7d32-42ed-9018-8206fc295dd9  -9218601096928798970                     17\n\
                UN  172.17.17.20  121.07 KB  67.3%             75917649-6caa-4c66-b003-71c0eb8c09e8  -9210152678340971410                     17\n\
                UN  172.17.17.22  80.18 KB   67.1%             f64ced33-2c01-40a3-9979-cf0a0b60d7af  -9187087995446879807                     17\n'

        self.statusio = StringIO.StringIO(statusiostr)
        self.statusio1 = StringIO.StringIO(statusiostr)

        self.snapshotio = StringIO.StringIO('success')

    def tearDown(self):
        super(BaseWorkloadTypeCassandraTestCase, self).tearDown()

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

    def test_cassandra_getcassandranodes(self):
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')


        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio, sys.stderr))


        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info4, sys.stderr))

        self.mox.ReplayAll()
        cassnodes = cassandraworkflow.getcassandranodes(client)
        self.assertEqual(len(cassnodes), 4)
        self.assertEqual(cassnodes[0]['Address'], '172.17.17.19')
        self.assertEqual(cassnodes[1]['Address'], '172.17.17.21')
        self.assertEqual(cassnodes[2]['Address'], '172.17.17.20')
        self.assertEqual(cassnodes[3]['Address'], '172.17.17.22')

    def test_cassandra_get_cassandra_nodes(self):
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        self.mox.StubOutClassWithMocks(nova, 'API')
        compute_service = nova.API(production=True)

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         self.store['SSHPort'],
                                         self.store['Username'],
                                         self.store['Password']).\
            AndReturn(client)
        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio, sys.stderr))

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info4, sys.stderr))

        compute_service.get_servers(self.context, admin=True).AndReturn(tests_utils.build_instances())
        compute_service.get_hypervisors(self.context).AndReturn(tests_utils.build_hypervisors())

        self.mox.ReplayAll()

        cassnodes = cassandraworkflow.get_cassandra_nodes(self.context,
                                                          self.store['CassandraNode'],
                                                          self.store['SSHPort'],
                                                          self.store['Username'],
                                                          self.store['Password'])

        self.assertEqual(len(cassnodes), 4)
        self.assertEqual(cassnodes[0]['vm_name'], 'd8848b37-1f6a-4a60-9aa5-d7763f710f2a')
        self.assertEqual(cassnodes[1]['vm_name'], 'testVM')
        self.assertEqual(cassnodes[2]['vm_name'], 'vm1')
        self.assertEqual(cassnodes[3]['vm_name'], 'vmware1')

    def test_cassandra_discover(self):
        cflow = cassandraworkflow.CassandraWorkflow("Cassandra", self.store)
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        self.mox.StubOutClassWithMocks(nova, 'API')
        compute_service = nova.API(production=True)

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)
        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio, sys.stderr))

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info4, sys.stderr))

        compute_service.get_servers(IsA(amqp.RpcContext), admin=True).AndReturn(tests_utils.build_instances())
        compute_service.get_hypervisors(IsA(amqp.RpcContext)).AndReturn(tests_utils.build_hypervisors())

        self.mox.ReplayAll()

        instances = cflow.discover()
        self.assertEqual(len(instances['instances']), 4)
        self.assertEqual(instances['instances'][0]['vm_name'], 'd8848b37-1f6a-4a60-9aa5-d7763f710f2a')
        self.assertEqual(instances['instances'][1]['vm_name'], 'testVM')
        self.assertEqual(instances['instances'][2]['vm_name'], 'vm1')
        self.assertEqual(instances['instances'][3]['vm_name'], 'vmware1')

    def test_cassandra_initflow(self):
        cflow = cassandraworkflow.CassandraWorkflow("Cassandra", self.store)
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        self.mox.StubOutClassWithMocks(nova, 'API')
        compute_service = nova.API(production=True)

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)
        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio, sys.stderr))

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info4, sys.stderr))

        compute_service.get_servers(IsA(amqp.RpcContext), admin=True).AndReturn(tests_utils.build_instances())
        compute_service.get_hypervisors(IsA(amqp.RpcContext)).AndReturn(tests_utils.build_hypervisors())

        self.mox.ReplayAll()

        cflow.initflow()

        self.assertEqual(cflow._store['instance_b66be913-9f3e-4adf-9274-4a36e980ff25']['vm_name'], 'testVM')
        self.assertEqual(cflow._store['instance_f6792af5-ffaa-407b-8401-f8246323dedf']['vm_name'], 'vm1')
        self.assertEqual(cflow._store['instance_144775cc-764b-4af4-99b3-ac6df0cabf98']['vm_name'], 'vmware1')
        self.assertEqual(cflow._store['instance_e44e5170-255d-42fb-a603-89fa171104e1']['vm_name'], 'd8848b37-1f6a-4a60-9aa5-d7763f710f2a')

    def test_cassandra_details(self):
        cflow = cassandraworkflow.CassandraWorkflow("Cassandra", self.store)
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        self.mox.StubOutClassWithMocks(nova, 'API')
        compute_service = nova.API(production=True)
        compute_service1 = nova.API(production=True)

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)


        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio, sys.stderr))

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info4, sys.stderr))

        compute_service.get_servers(IsA(amqp.RpcContext), admin=True).AndReturn(tests_utils.build_instances())
        compute_service.get_hypervisors(IsA(amqp.RpcContext)).AndReturn(tests_utils.build_hypervisors())

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)

        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio1, sys.stderr))

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info11, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info31, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info21, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info41, sys.stderr))

        compute_service1.get_servers(IsA(amqp.RpcContext), admin=True).AndReturn(tests_utils.build_instances())
        compute_service1.get_hypervisors(IsA(amqp.RpcContext)).AndReturn(tests_utils.build_hypervisors())

        self.mox.ReplayAll()

        cflow.initflow()
        workflow = cflow.details()

        # TODO: Verify that workflow is valid

    def test_cassandra_topology(self):
        cflow = cassandraworkflow.CassandraWorkflow("Cassandra", self.store)
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)


        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio, sys.stderr))

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info4, sys.stderr))

        self.mox.ReplayAll()

        topology = cflow.topology()

        # Verify the topology

    def test_cassandra_execute(self):
        cflow = cassandraworkflow.CassandraWorkflow("Cassandra", self.store)
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        self.mox.StubOutWithMock(vmtasks_openstack, 'pre_snapshot_vm')
        self.mox.StubOutWithMock(vmtasks_openstack, 'snapshot_vm_networks')
        self.mox.StubOutWithMock(vmtasks_openstack, 'snapshot_vm_flavors')
        self.mox.StubOutWithMock(vmtasks_openstack, 'snapshot_vm_security_groups')
        self.mox.StubOutWithMock(vmtasks_openstack, 'pause_vm')
        self.mox.StubOutWithMock(vmtasks_openstack, 'snapshot_vm')
        self.mox.StubOutWithMock(vmtasks_openstack, 'unpause_vm')
        self.mox.StubOutWithMock(vmtasks_openstack, 'get_snapshot_data_size')
        self.mox.StubOutWithMock(vmtasks_openstack, 'upload_snapshot')
        self.mox.StubOutWithMock(vmtasks_openstack, 'post_snapshot')

        self.mox.StubOutClassWithMocks(nova, 'API')
        compute_service = nova.API(production=True)

        self.store['snapshot'] = tests_utils.create_snapshot(self.context,
                                      'd296c248-d206-4837-b719-0abed920281d').__dict__
        self.store['snapshot'].pop('_sa_instance_state')
        self.store['context']['read_deleted']=self.store['context']['_read_deleted']

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)
        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, self.statusio, sys.stderr))

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, self.info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, self.info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, self.info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, self.info4, sys.stderr))

        compute_service.get_servers(IsA(amqp.RpcContext), admin=True).AndReturn(tests_utils.build_instances())
        compute_service.get_hypervisors(IsA(amqp.RpcContext)).AndReturn(tests_utils.build_hypervisors())

        # These are presnapshot tasks
        instances = tests_utils.build_instances()
        for inst in instances:
            vmtasks_openstack.pre_snapshot_vm(IsA(amqp.RpcContext), self.db, IgnoreArg(), IgnoreArg())

        # mock snapshot networks, snapshot flavors, snapshot security groups
        vmtasks_openstack.snapshot_vm_networks(IsA(amqp.RpcContext), self.db, IsA(list), self.store['snapshot'])
        vmtasks_openstack.snapshot_vm_flavors(IsA(amqp.RpcContext), self.db, IsA(list), self.store['snapshot'])
        vmtasks_openstack.snapshot_vm_security_groups(IsA(amqp.RpcContext), self.db, IsA(list), self.store['snapshot'])

        # mock nodetool snapshot, part of Snapshot node
        for inst in instances:
            cassandraworkflow.connect_server(inst.name,
                                             int(self.store['SSHPort']),
                                             self.store['Username'],
                                             self.store['Password']).\
                                             InAnyOrder().\
                                             AndReturn(client)
            client.exec_command("nodetool snapshot").\
                InAnyOrder().\
                AndReturn((sys.stdin, StringIO.StringIO('success'), sys.stderr))

        # mode pausevm task
        for inst in instances:
            vmtasks_openstack.pause_vm(IsA(amqp.RpcContext), self.db, IsA(dict))

        # mode snapshotvm
        for inst in instances:
            vmtasks_openstack.snapshot_vm(IsA(amqp.RpcContext), self.db, IsA(dict), IgnoreArg())

        # mode unpausevm
        for inst in instances:
            vmtasks_openstack.unpause_vm(IsA(amqp.RpcContext), self.db, IsA(dict))

        # mock nodetool clearsnapshot, part of Clearsnapshot node task
        for inst in instances:
            cassandraworkflow.connect_server(inst.name,
                                             int(self.store['SSHPort']),
                                             self.store['Username'],
                                             self.store['Password']).\
                                             InAnyOrder().\
                                             AndReturn(client)
            client.exec_command("nodetool clearsnapshot").\
                InAnyOrder().\
                AndReturn((sys.stdin, StringIO.StringIO('success'), sys.stderr))

        # mock snapshot_data_size
        for inst in instances:
            vmtasks_openstack.get_snapshot_data_size(IsA(amqp.RpcContext),
                                                     self.db,
                                                     IsA(dict),
                                                     IsA(dict),
                                                     IgnoreArg()).\
                                                     InAnyOrder().\
                                                     AndReturn(1024*1024*1024)

        # mock upload snapshot
        for inst in instances:
            vmtasks_openstack.upload_snapshot(IsA(amqp.RpcContext), self.db,
                                              IsA(dict), IsA(dict),
                                              IgnoreArg()).\
                                              InAnyOrder()

        # mock post snapshot
        for inst in instances:
            vmtasks_openstack.post_snapshot(IsA(amqp.RpcContext), self.db,
                                              IsA(dict), IsA(dict),
                                              IgnoreArg()).\
                                              InAnyOrder()

        self.mox.ReplayAll()

        cflow.initflow()
        cflow.execute()

    def test_cassandra_snapshot_node_execute(self):
        snaptask = cassandraworkflow.SnapshotNode()
        client = paramiko.SSHClient()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)

        client.exec_command("nodetool snapshot").\
            AndReturn((sys.stdin, self.snapshotio, sys.stderr))

        self.mox.ReplayAll()
        cassnodes = snaptask.execute(self.store['CassandraNode'],
                                     self.store['SSHPort'],
                                     self.store['Username'],
                                     self.store['Password'])

    def test_cassandra_snapshot_node_revert(self):
        snaptask = cassandraworkflow.SnapshotNode()
        client = paramiko.SSHClient()
        snaptask.client = client
        self.mox.StubOutWithMock(client, 'exec_command')

        client.exec_command("nodetool clearsnapshot").\
            AndReturn((sys.stdin, self.snapshotio, sys.stderr))

        self.mox.ReplayAll()
        snaptask.revert([], result=-1)

    def test_cassandra_clear_snapshot_execute(self):
        client = paramiko.SSHClient()
        snaptask = cassandraworkflow.ClearSnapshot()
        self.mox.StubOutWithMock(client, 'exec_command')
        self.mox.StubOutWithMock(cassandraworkflow, 'connect_server')

        cassandraworkflow.connect_server(self.store['CassandraNode'],
                                         int(self.store['SSHPort']),
                                         self.store['Username'],
                                         self.store['Password']).AndReturn(client)

        client.exec_command("nodetool clearsnapshot").\
            AndReturn((sys.stdin, self.snapshotio, sys.stderr))

        self.mox.ReplayAll()
        cassnodes = snaptask.execute(self.store['CassandraNode'],
                                     self.store['SSHPort'],
                                     self.store['Username'],
                                     self.store['Password'])
'''
