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
import StringIO

from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.compute import nova
from workloadmgr.tests import utils as tests_utils
from workloadmgr.openstack.common import importutils

from workloadmgr.workloads.api import API
from workloadmgr.workflows import cassandraworkflow

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
                         "SSHPort": 22,
                         "Username": "ubuntu",
                         "Password": "password",
                         "capabilities": "discover:topology",}}

    def tearDown(self):
        super(BaseWorkloadTypeCassandraTestCase, self).tearDown()

    def test_create_delete_workload_type(self):
        """Test workload can be created and deleted."""

        workload_type = self.workloadAPI.workload_type_create(self.context, 
			    self.workload_params['display_name'],
                            self.workload_params['display_description'],
                            self.workload_params['is_public'],
                            self.workload_params['metadata'],)

        workload_type_id = workload_type['id']
        self.assertEqual(workload_type_id, 
                         self.db.workload_type_get(self.context,
                                                   workload_type_id).id)

        self.assertEqual(workload_type['status'], 'available')
        self.assertEqual(workload_type['display_name'], self.workload_params['display_name'])
        self.assertEqual(workload_type['display_description'], self.workload_params['display_description'])
        self.assertEqual(workload_type['is_public'], self.workload_params['is_public'])
        self.assertEqual(workload_type['metadata'], self.workload_params['metadata'])


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
                            False, None)
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

        self.assertEqual(workload_type['metadata'], {})
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
   
        statusio = StringIO.StringIO('\
                Datacenter: 17\n\
                ==============\n\
                Status=Up/Down\n\
                |/ State=Normal/Leaving/Joining/Moving\n\
                --  Address       Load       Owns (effective)  Host ID                               Token                                    Rack\n\
                UN  172.17.17.19  130.46 KB  0.2%              7d62d900-f99d-4b88-8012-f06cb639fc02  -4300314010327621                        17\n\
                UN  172.17.17.21  111.62 KB  65.4%             a03a1287-7d32-42ed-9018-8206fc295dd9  -9218601096928798970                     17\n\
                UN  172.17.17.20  121.07 KB  67.3%             75917649-6caa-4c66-b003-71c0eb8c09e8  -9210152678340971410                     17\n\
                UN  172.17.17.22  80.18 KB   67.1%             f64ced33-2c01-40a3-9979-cf0a0b60d7af  -9187087995446879807                     17\n')

        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, statusio, sys.stderr))

        info1 = StringIO.StringIO('\
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
                                  ')
        info2 = StringIO.StringIO('\
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
                                  ')
        info3 = StringIO.StringIO('\
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
                                  ')
        info4 = StringIO.StringIO('\
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
                                  ')

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, info4, sys.stderr))

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
        #self.mox.StubOutWithMock(compute_service, "get_servers")
        #self.mox.StubOutWithMock(compute_service, "get_hypervisors")

   
        statusio = StringIO.StringIO('\
                Datacenter: 17\n\
                ==============\n\
                Status=Up/Down\n\
                |/ State=Normal/Leaving/Joining/Moving\n\
                --  Address       Load       Owns (effective)  Host ID                               Token                                    Rack\n\
                UN  172.17.17.19  130.46 KB  0.2%              7d62d900-f99d-4b88-8012-f06cb639fc02  -4300314010327621                        17\n\
                UN  172.17.17.21  111.62 KB  65.4%             a03a1287-7d32-42ed-9018-8206fc295dd9  -9218601096928798970                     17\n\
                UN  172.17.17.20  121.07 KB  67.3%             75917649-6caa-4c66-b003-71c0eb8c09e8  -9210152678340971410                     17\n\
                UN  172.17.17.22  80.18 KB   67.1%             f64ced33-2c01-40a3-9979-cf0a0b60d7af  -9187087995446879807                     17\n')

        cassandraworkflow.connect_server("localhost", "22", "fake_user", "fake_password").\
            AndReturn(client)
        client.exec_command("nodetool status").\
            AndReturn((sys.stdin, statusio, sys.stderr))

        info1 = StringIO.StringIO('\
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
                                  ')
        info2 = StringIO.StringIO('\
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
                                  ')
        info3 = StringIO.StringIO('\
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
                                  ')
        info4 = StringIO.StringIO('\
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
                                  ')

        client.exec_command("nodetool -h 172.17.17.19 info").AndReturn((sys.stdin, info1, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.21 info").AndReturn((sys.stdin, info3, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.20 info").AndReturn((sys.stdin, info2, sys.stderr))
        client.exec_command("nodetool -h 172.17.17.22 info").AndReturn((sys.stdin, info4, sys.stderr))

        compute_service.get_servers(self.context, admin=True).AndReturn(tests_utils.build_instances())
        compute_service.get_hypervisors(self.context).AndReturn(tests_utils.build_hypervisors())

        self.mox.ReplayAll()

        cassnodes = cassandraworkflow.get_cassandra_nodes(self.context, "localhost", "22", "fake_user", "fake_password")

        self.assertEqual(len(cassnodes), 4)

    def test_cassandra_details(self):
        pass

    def test_cassandra_initflow(self):
        pass

    def test_cassandra_topology(self):
        pass
