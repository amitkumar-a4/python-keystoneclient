# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.

import contextlib
from bunch import bunchify
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
from workloadmgr.openstack.common import fileutils
#from workloadmgr.workloads.api import API

CONF = cfg.CONF

class BaseWorkloadTestCase(test.TestCase):
    """Test Case for workloads."""
    def setUp(self):
        super(BaseWorkloadTestCase, self).setUp()
        self.context = context.get_admin_context()


        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        self.is_online_patch = patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.MockMethod = self.is_online_patch.start()
        self.MockMethod.return_value = True

        self.subprocess_patch = patch('subprocess.check_call')
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.SubProcessMockMethod.return_value = True

        patch('workloadmgr.workloads.api.create_trust', lambda x: x).start()
        patch('sys.stderr').start()
        patch('workloadmgr.autolog.log_method').start()

        self.workload = importutils.import_object(CONF.workloads_manager)
        from workloadmgr.workloads.api import *
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.context.tenant_id = 'fake'
        self.context.is_admin = False
        self.workload_params = {
            'status': 'creating',
            'error_msg': '',
            'instances': [],
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

        import workloadmgr.vault.vault
        for share in ['server1:nfsshare1','server2:nfsshare2','server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                             display_name='Serial',
                                                             display_description='this is a test workload_type',
                                                             status='available',
                                                             is_public=True,
                                                             metadata=None)

                    workload = tests_utils.create_workload(
                        self.context,
                        workload_type_id=workload_type.id,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
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

                    backup_target = None
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            backup_target = workloadmgr.vault.vault.get_backup_target(meta.value)
                    self.assertNotEqual(backup_target, None)
                    workload_path = os.path.join(backup_target.mount_path, "workload_" + workload.id)

                    self.assertTrue(os.path.exists(workload_path))

                    self.workload.workload_delete(self.context, workload_id)
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
                    self.assertFalse(os.path.exists(workload_path))

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    def test_create_delete_multivm_workload(self,
                                            set_meta_item_mock,
                                            delete_meta_mock,
                                            get_server_by_id_mock,
                                            get_flavor_by_id_mock,
                                            get_volume_mock):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager

        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
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

                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                             display_name='Serial',
                                                             display_description='this is a test workload_type',
                                                             status='available',
                                                             is_public=True,
                                                             metadata=None)

                    self.workload_params['instances'] = tests_utils.get_instances()
                    workload = tests_utils.create_workload(
                        self.context,
                        workload_type_id=workload_type['id'],
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
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

                    backup_target = None
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            backup_target = workloadmgr.vault.vault.get_backup_target(meta.value)
                    self.assertNotEqual(backup_target, None)
                    workload_path = os.path.join(backup_target.mount_path, "workload_" + workload.id)
                    workload_vms_path = os.path.join(workload_path, "workload_vms_db")

                    self.assertTrue(os.path.exists(workload_path))
                    self.assertTrue(os.path.exists(workload_vms_path))

                    self.workload.workload_delete(self.context, workload_id)
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
                    self.assertFalse(os.path.exists(workload_path))

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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                             display_name='Serial',
                                                             display_description='this is a test workload_type',
                                                             status='available',
                                                             is_public=True,
                                                             metadata=None)

                    workload = tests_utils.create_workload(
                        self.context,
                        workload_type_id=workload_type['id'],
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                             display_name='Serial',
                                                             display_description='this is a test workload_type',
                                                             status='available',
                                                             is_public=True,
                                                             metadata=None)

                    workload = tests_utils.create_workload(
                        self.context,
                        workload_type_id=workload_type['id'],
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
                            break
                     
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                             display_name='Serial',
                                                             display_description='this is a test workload_type',
                                                             status='available',
                                                             is_public=True,
                                                             metadata=None)

                    workload = tests_utils.create_workload(
                        self.context,
                        workload_type_id=workload_type['id'],
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                             display_name='Serial',
                                                             display_description='this is a test workload_type',
                                                             status='available',
                                                             is_public=True,
                                                             metadata=None)

                    workload = tests_utils.create_workload(
                        self.context,
                        workload_type_id=workload_type['id'],
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

    @patch('sys.stderr')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.initflow')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_snapshot(self, mock_get_servers, m1, m2, m3):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.return_value = []
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)
                        workload = self.db.workload_get(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])
                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        backup_target = None
                        for meta in workload.metadata:
                            if meta.key == 'backup_media_target':
                                backup_target = workloadmgr.vault.vault.get_backup_target(meta.value)

                        self.assertNotEqual(backup_target, None)
                        workload_path = os.path.join(backup_target.mount_path, "workload_" + workload.id)
                        workload_vms_path = os.path.join(workload_path, "workload_vms_db")
                        snapshot_path = os.path.join(workload_path, "snapshot_" + snapshot.id)

                        self.assertTrue(os.path.exists(workload_path))
                        self.assertTrue(os.path.exists(workload_vms_path))
                        self.assertTrue(os.path.exists(snapshot_path))

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_snapshot(self, mock_get_servers, m2,
                                                 set_meta_item_mock,
                                                 delete_meta_mock,
                                                 get_server_by_id_mock,
                                                 get_flavor_by_id_mock,
                                                 get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = tests_utils.get_vms
        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = tests_utils.get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])
                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_snapshot_workflow_execute(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = tests_utils.get_vms
        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = tests_utils.get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)
  
                        # check all database records before deleting snapshots and workloads

    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_snapshot_workflow_execute_incr(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = tests_utils.get_vms
        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = tests_utils.get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='incr',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')
  
                        # check all database records before deleting snapshots and workloads

    @patch('workloadmgr.workflows.vmtasks_openstack.post_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_keypairs')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavors')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_restore_workflow_execute(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_flavors_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy,
        pre_restore_vm_mock,
        restore_keypairs_mock,
        restore_vm_mock,
        post_restore_vm_mock):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = tests_utils.get_vms
        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
        get_flavors_mock.side_effect = tests_utils.get_flavors_for_test
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = tests_utils.get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        set_meta_item_mock.reset_mock()
                        delete_meta_mock.reset_mock()
                        pre_snapshot_vm_mock.reset_mock()
                        snapshot_vm_networks_mock.reset_mock()
                        snapshot_vm_security_groups.reset_mock()
                        snapshot_flavors_mock.reset_mock()
                        freeze_vm_mock.reset_mock()
                        thaw_vm_mock.reset_mock()
                        snapshot_vm_mock.reset_mock()
                        get_snapshot_data_size_mock.reset_mock()
                        upload_snapshot_mock.reset_mock()
                        post_snapshot_mock.reset_mock()
                        apply_retention_policy.reset_mock()

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])

                        self.assertEqual(set_meta_item_mock.call_count, 10)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')
  
                        options = tests_utils.get_restore_options()
                        restore = tests_utils.create_restore(self.context,
                                                              snapshot['id'],
                                                              display_name='test_restore',
                                                              display_description='this is a test restore',
                                                              options=options)
                        restore_id = restore['id']
                        self.workload.snapshot_restore(self.context, restore_id)
                        restore = self.db.restore_get(self.context, restore['id'])
                        self.assertEqual(restore.status, 'available')

                        self.assertEqual(pre_restore_vm_mock.call_count, 5)
                        self.assertEqual(restore_keypairs_mock.call_count, 1)
                        self.assertEqual(restore_vm_mock.call_count, 5)
                        self.assertEqual(post_restore_vm_mock.call_count, 5)

    @patch('workloadmgr.workflows.vmtasks_openstack.post_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_keypairs')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavors')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_restore_workflow_execute_restore_vm_flow(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_flavors_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy,
        pre_restore_vm_mock,
        restore_keypairs_mock,
        restore_vm_networks_mock,
        post_restore_vm_mock):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = tests_utils.get_vms
        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
        get_flavors_mock.side_effect = tests_utils.get_flavors_for_test
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
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = tests_utils.get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        set_meta_item_mock.reset_mock()
                        delete_meta_mock.reset_mock()
                        pre_snapshot_vm_mock.reset_mock()
                        snapshot_vm_networks_mock.reset_mock()
                        snapshot_vm_security_groups.reset_mock()
                        snapshot_flavors_mock.reset_mock()
                        freeze_vm_mock.reset_mock()
                        thaw_vm_mock.reset_mock()
                        snapshot_vm_mock.reset_mock()
                        get_snapshot_data_size_mock.reset_mock()
                        upload_snapshot_mock.reset_mock()
                        post_snapshot_mock.reset_mock()
                        apply_retention_policy.reset_mock()

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])

                        self.assertEqual(set_meta_item_mock.call_count, 10)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')
  
                        options = tests_utils.get_restore_options()
                        restore = tests_utils.create_restore(self.context,
                                                              snapshot['id'],
                                                              display_name='test_snapshot',
                                                              display_description='this is a test snapshot',
                                                              options=options)
                        restore_id = restore['id']
                        self.workload.snapshot_restore(self.context, restore_id)
                        restore = self.db.restore_get(self.context, restore['id'])
                        self.assertEqual(restore.status, 'available')

                        self.assertEqual(pre_restore_vm_mock.call_count, 5)
                        self.assertEqual(restore_keypairs_mock.call_count, 1)
