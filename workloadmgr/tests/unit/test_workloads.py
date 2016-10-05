'''
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.

import contextlib
import datetime
import os
import shutil
import socket
import tempfile

import eventlet
import mock
import mox
from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.tests import utils as tests_utils
from workloadmgr.openstack.common import importutils
#from workloadmgr.workloads.api import API
from workloadmgr.workloads.api import *

CONF = cfg.CONF

class BaseWorkloadTestCase(test.TestCase):
    """Test Case for workloads."""
    def setUp(self):
        super(BaseWorkloadTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.workload = importutils.import_object(CONF.workloads_manager)
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.workload_params = {
            'status': 'creating',
            'host': CONF.host,}

    def tearDown(self):
        super(BaseWorkloadTestCase, self).tearDown()

    def test_create_delete_workload(self):
        """Test workload can be created and deleted."""

        workload = tests_utils.create_workload(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.workload_params)
        workload_id = workload['id']
        self.workload.workload_create(self.context, workload_id)
        expected = {
            'status': 'creating',
            'display_name': 'test_workload',
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'workload_id': workload_id,
            'workload_type': None,
            'user_id': 'fake',
            'launched_at': 'DONTCARE',
        }
        expected['status'] = 'available'
        self.assertEqual(workload_id, self.db.workload_get(self.context, workload_id).id)

        self.workload.workload_delete(self.context, workload_id)
        workload = db.workload_get(self.context, workload_id)
        self.assertEqual(workload['status'], 'deleted')
        self.assertRaises(exception.NotFound,
                          db.workload_get,
                          self.context,
                          workload_id)

    def test_create_workload_with_invalid_workload_type(self):
        """Test workload can be created and deleted."""

        self.assertRaises(exception.InvalidState,
                          self.workloadAPI.workload_create,
                          self.context, 'test_workload',
                          'this is a test_workload', "invalid_type",
                          'openstack', [], {}, {})
'''

