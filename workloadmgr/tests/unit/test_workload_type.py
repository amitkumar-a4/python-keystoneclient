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

from workloadmgr.workloads.api import API

CONF = cfg.CONF

class BaseWorkloadTypeTestCase(test.TestCase):
    """Test Case for workload Type."""
    def setUp(self):
        super(BaseWorkloadTypeTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.workload = importutils.import_object(CONF.workloads_manager)
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.workload_params = {
            'display_name': 'test_workload_type',
            'display_description': 'this is a test workload_type',
            'status': 'creating',
            'is_public': True,
            'metadata': {}, }

    def tearDown(self):
        super(BaseWorkloadTypeTestCase, self).tearDown()

    def test_create_delete_workload_type(self):
        """Test workload can be created and deleted."""

        workload_type = self.workloadAPI.workload_type_create(self.context,
                            'test_workload',
                            'this is a test workload_type',
                            False, {})
        workload_type_id = workload_type['id']
        self.assertEqual(workload_type_id,
                         self.db.workload_type_get(self.context,
                                                   workload_type_id).id)

        self.assertEqual(workload_type['status'], 'available')
        self.assertEqual(workload_type['display_name'], 'test_workload')
        self.assertEqual(workload_type['display_description'], 'this is a test workload_type')
        self.assertEqual(workload_type['is_public'], False)
        self.assertEqual(workload_type['metadata'], {})

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

        self.assertEqual(workload_type['metadata'], {})
        self.workloadAPI.workload_type_delete(self.context, workload_type_id)
        workload_type = db.workload_type_get(self.context, workload_type_id)
        self.assertEqual(workload_type['status'], 'deleted')
        self.assertRaises(exception.NotFound,
                          db.workload_type_get,
                          self.context,
                          workload_type_id)

    def test_create_workload_type_with_metadata(self):
        """Test workloadtype with invalid metadata"""

        metadata  = {"key1": "value1",
                     "key2": "value2"}
        workload_type = self.workloadAPI.workload_type_create(self.context,
                            'test_workload',
                            'this is a test workload_type',
                            False, metadata)
        workload_type_id = workload_type['id']
        self.assertEqual(workload_type_id,
                         self.db.workload_type_get(self.context,
                                                   workload_type_id).id)
        workload_type = self.db.workload_type_get(self.context, workload_type_id)
        actual_metadata = {}
        for meta in workload_type.metadata:
            actual_metadata[meta.key] = meta.value

        self.assertDictMatch(actual_metadata, metadata)
        self.workloadAPI.workload_type_delete(self.context, workload_type_id)
        workload_type = db.workload_type_get(self.context, workload_type_id)
        self.assertEqual(workload_type['status'], 'deleted')
'''
