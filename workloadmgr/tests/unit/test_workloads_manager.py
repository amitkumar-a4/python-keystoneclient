# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.

import contextlib
import cPickle as pickle
import datetime
import os
import shutil
import socket
import tempfile

import eventlet
import mock
from mock import patch
import mox
from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.tests.unit import utils as tests_utils
from workloadmgr.openstack.common import importutils
#from workloadmgr.workloads.api import API

CONF = cfg.CONF

class BaseWorkloadTestCase(test.TestCase):
    """Test Case for workloads."""
    def setUp(self):
        super(BaseWorkloadTestCase, self).setUp()
        self.context = context.get_admin_context()


        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        patch('workloadmgr.workloads.api.create_trust', lambda x: x).start()
        self.is_online_patch = patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')
        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True

        self.workload = importutils.import_object(CONF.workloads_manager)
        from workloadmgr.workloads.api import *
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.context.tenant_id = 'fake'
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': -1,
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()
        super(BaseWorkloadTestCase, self).tearDown()

    def test_create_delete_workload(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
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
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '-1',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }
                    expected['status'] = 'available'
                    self.assertEqual(workload_id, self.db.workload_get(self.context, workload_id).id)

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)

    def test_create_delete_workload_fullbackup_always(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': 0,
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
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
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '0',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }
                    expected['status'] = 'available'
                    self.assertEqual(workload_id, self.db.workload_get(self.context, workload_id).id)

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)

    def test_create_delete_workload_fullbackup_interval(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
                    self.assertEqual(workload_id,
                                     self.db.workload_get(self.context,
                                                          workload_id).id)
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            self.assertEqual(meta.value, 'server1:nfsshare1')
                     
                    self.assertEqual(workload.status, 'available')
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '10',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)

    def test_create_delete_workload_with_one_nfs_full(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
                    self.assertEqual(workload_id,
                                     self.db.workload_get(self.context,
                                                          workload_id).id)
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            self.assertEqual(meta.value, 'server2:nfsshare2')
                     
                    self.assertEqual(workload.status, 'available')
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '10',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
    def test_create_delete_workload_with_two_nfs_full(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
                    self.assertEqual(workload_id,
                                     self.db.workload_get(self.context,
                                                          workload_id).id)
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            self.assertEqual(meta.value, 'server3:nfsshare3')
                     
                    self.assertEqual(workload.status, 'available')
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '10',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
    def test_create_workload_with_invalid_workload_type(self):
        """Test workload can be created and deleted."""
        pass
