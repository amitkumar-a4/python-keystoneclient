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
#from workloadmgr.compute import nova
from workloadmgr.tests import utils as tests_utils

from workloadmgr.workloads.api import API
from workloadmgr.workflows import vmtasks
from workloadmgr.vault import vault
from workloadmgr.tests.swift import fake_swift_client

CONF = cfg.CONF

class BaseWorkloadTypeVMTasksTestCase(test.TestCase):
    """Test Case for vmtasks."""
    def setUp(self):
        super(BaseWorkloadTypeVMTasksTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.workload = importutils.import_object(CONF.workloads_manager)
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

    def tearDown(self):
        super(BaseWorkloadTypeVMTasksTestCase, self).tearDown()

    def test_import_workloads(self):
        """Test import workloads from swift store."""
        def servicefunc(*args):
            return fake_swift_client.FakeSwiftClient()

        self.stubs.Set(vault, 'get_vault_service', servicefunc)
        vmtasks.import_workloads(self.context)
        workloads = self.db.workload_get_all_by_project(self.context, "9ad87da6ea0e4eacb2aaa85cbac31a21")
        self.assertEqual(len(workloads), 3)
        snapshots = self.db.snapshot_get_all_by_project(self.context, "9ad87da6ea0e4eacb2aaa85cbac31a21")
        self.assertEqual(len(snapshots), 4)
'''
