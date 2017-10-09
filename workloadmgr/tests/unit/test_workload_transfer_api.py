# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.
import __builtin__
from bunch import bunchify
import contextlib
import cPickle as pickle
import datetime
import json
import os
import random
import sys
import shutil
import socket
import subprocess
import tempfile
import paramiko
import eventlet
import mock
from mock import patch
import mox
from mox import IsA
from mox import IgnoreArg
from mox import In
import StringIO
import uuid

from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common.rpc import amqp
#from workloadmgr.compute import nova
from workloadmgr.tests.unit import utils as tests_utils

from workloadmgr.vault import vault

CONF = cfg.CONF


class BaseWorkloadTransferTestCase(test.TestCase):
    """Test Case for workload_utils."""

    def setUp(self):
        super(BaseWorkloadTransferTestCase, self).setUp()

        CONF.set_default(
            'vault_storage_nfs_export',
            'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        self.context = context.get_admin_context()
        patch('sys.stderr').start()

        self.is_online_patch = patch(
            'workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')

        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True

        self.workload = importutils.import_object(CONF.workloads_manager)
        from workloadmgr.workloads.api import API
        from workloadmgr.transfer.api import API as transfer_api
        self.workloadAPI = API()
        self.workload_transfer_api = transfer_api()
        self.db = self.workload.db
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = str(uuid.uuid4())
        self.context.tenant_id = self.context.project_id
        self.context.is_admin = False

        self.nfsshares = [{'server1:nfsshare1': [1099511627776,
                                                 10737418240],
                           }.values()[0],
                          {'server2:nfsshare2': [1099511627776,
                                                 5 * 10737418240],
                           }.values()[0],
                          {'server3:nfsshare3': [1099511627776,
                                                 7 * 10737418240],
                           }.values()[0],
                          ]

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()

        import workloadmgr.vault.vault
        for share in ['server1:nfsshare1',
                      'server2:nfsshare2', 'server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)

        super(BaseWorkloadTransferTestCase, self).tearDown()

    def test_workload_transfer_get(self):
        pass

    def test_workload_transfer_delete(self):
        """Test workload transfer created and deleted."""
        pass

    def test_workload_transfer_get_all(self):
        pass

    def test_workload_transfer_create(self):
        """Test workload transfer created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776,
                                                     10737418240],
                               }.values()[0],
                              {'server2:nfsshare2': [1099511627776,
                                                     5 * 10737418240],
                               }.values()[0],
                              {'server3:nfsshare3': [1099511627776,
                                                     7 * 10737418240],
                               }.values()[0],
                              ]

                    mock_method2.side_effect = values
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
                        'host': CONF.host, }
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(
                            self.context,
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
                        'jobschedule': {
                            'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '-1',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}}
                    expected['status'] = 'available'
                    self.assertEqual(
                        workload_id, self.db.workload_get(
                            self.context, workload_id).id)

                    backup_target = None
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            backup_target = workloadmgr.vault.vault.get_backup_target(
                                meta.value)
                    self.assertNotEqual(backup_target, None)
                    workload_path = os.path.join(
                        backup_target.mount_path, "workload_" + workload.id)

                    self.assertTrue(os.path.exists(workload_path))

                    current_project_id = self.context.project_id
                    self.context.project_id = str(uuid.uuid4())
                    self.assertRaises(exception.InvalidWorkload,
                                      self.workload_transfer_api.create,
                                      self.context,
                                      workload_id,
                                      "test_transfer")
                    self.context.project_id = current_project_id

                    self.db.workload_update(self.context, workload['id'],
                                            {'status': 'notavailable'})
                    self.assertRaises(exception.InvalidState,
                                      self.workload_transfer_api.create,
                                      self.context,
                                      workload_id,
                                      "test_transfer")
                    self.db.workload_update(self.context, workload['id'],
                                            {'status': 'available'})

                    transfer_rec = self.workload_transfer_api.create(
                        self.context, workload_id, "test-transfer")

                    self.assertEqual(set(['id',
                                          'workload_id',
                                          'display_name',
                                          'auth_key',
                                          'created_at']),
                                     set(transfer_rec.keys()))

                    self.assertEqual(
                        transfer_rec['workload_id'], workload['id'])

                    rec = self.workload_transfer_api.get(
                        self.context, transfer_rec['id'])
                    self.assertEqual(transfer_rec['id'], rec['id'])

                    self.workload_transfer_api.delete(
                        self.context, transfer_rec['id'])
                    self.workload.workload_delete(self.context, workload_id)
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
                    self.assertFalse(os.path.exists(workload_path))

                    self.assertRaises(exception.TransferNotFound,
                                      self.workload_transfer_api.get,
                                      self.context,
                                      rec['id'])

    @patch('workloadmgr.workloads.api.API.import_workloads')
    def test_workload_transfer_accept_same_cloud(self, import_wl_mock):
        """Test workload transfer created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        import workloadmgr.db.api
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776,
                                                     10737418240],
                               }.values()[0],
                              {'server2:nfsshare2': [1099511627776,
                                                     5 * 10737418240],
                               }.values()[0],
                              {'server3:nfsshare3': [1099511627776,
                                                     7 * 10737418240],
                               }.values()[0],
                              ]

                    mock_method2.side_effect = values
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
                        'host': CONF.host, }

                    self.stash = self.workload_params

                    def import_wl_mock_se(context, workloads, upgrade=False):
                        self.stash['id'] = workloads[0]
                        self.stash['status'] = 'available'
                        self.stash['import_done'] = True

                    import_wl_mock.side_effect = import_wl_mock_se
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(
                            self.context,
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
                        'jobschedule': {
                            'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '-1',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}}
                    expected['status'] = 'available'
                    self.assertEqual(
                        workload_id, self.db.workload_get(
                            self.context, workload_id).id)

                    backup_target = None
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            backup_target = workloadmgr.vault.vault.get_backup_target(
                                meta.value)
                    self.assertNotEqual(backup_target, None)
                    workload_path = os.path.join(
                        backup_target.mount_path, "workload_" + workload.id)

                    self.assertTrue(os.path.exists(workload_path))

                    current_project_id = self.context.project_id
                    self.context.project_id = str(uuid.uuid4())
                    self.assertRaises(exception.InvalidWorkload,
                                      self.workload_transfer_api.create,
                                      self.context,
                                      workload_id,
                                      "test_transfer")
                    self.context.project_id = current_project_id

                    self.db.workload_update(self.context, workload['id'],
                                            {'status': 'notavailable'})
                    self.assertRaises(exception.InvalidState,
                                      self.workload_transfer_api.create,
                                      self.context,
                                      workload_id,
                                      "test_transfer")
                    self.db.workload_update(self.context, workload['id'],
                                            {'status': 'available'})

                    transfer_rec = self.workload_transfer_api.create(
                        self.context, workload_id, "test-transfer")

                    self.assertEqual(set(['id',
                                          'workload_id',
                                          'display_name',
                                          'auth_key',
                                          'created_at']),
                                     set(transfer_rec.keys()))

                    self.assertEqual(
                        transfer_rec['workload_id'], workload['id'])

                    rec = self.workload_transfer_api.get(
                        self.context, transfer_rec['id'])
                    self.assertEqual(transfer_rec['id'], rec['id'])

                    self.assertRaises(exception.TransferNotAllowed,
                                      self.workload_transfer_api.accept,
                                      self.context,
                                      rec['id'], transfer_rec['auth_key'])

                    self.db.workload_delete(self.context, workload_id)

                    with patch.object(workloadmgr.db, 'workload_get') as workload_get_mock:
                        def workload_get_stub(context, wid):
                            if 'import_done' not in self.stash:
                                raise exception.WorkloadNotFound(
                                    workload_id=wid)
                            else:
                                return bunchify(self.stash)
                        workload_get_mock.side_effect = workload_get_stub
                        trans_rec = self.workload_transfer_api.accept(
                            self.context, rec['id'], transfer_rec['auth_key'])

    @patch('workloadmgr.workloads.api.API.import_workloads')
    def test_workload_transfer_complete(self, import_wl_mock):
        """Test workload transfer created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        import workloadmgr.db.api
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776,
                                                     10737418240],
                               }.values()[0],
                              {'server2:nfsshare2': [1099511627776,
                                                     5 * 10737418240],
                               }.values()[0],
                              {'server3:nfsshare3': [1099511627776,
                                                     7 * 10737418240],
                               }.values()[0],
                              ]

                    mock_method2.side_effect = values
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
                        'host': CONF.host, }

                    self.stash = self.workload_params

                    def import_wl_mock_se(context, workloads, upgrade=False):
                        self.stash['id'] = workloads[0]
                        self.stash['status'] = 'available'
                        self.stash['import_done'] = True

                    import_wl_mock.side_effect = import_wl_mock_se
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(
                            self.context,
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
                        'jobschedule': {
                            'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '-1',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}}
                    expected['status'] = 'available'
                    self.assertEqual(
                        workload_id, self.db.workload_get(
                            self.context, workload_id).id)

                    backup_target = None
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            backup_target = workloadmgr.vault.vault.get_backup_target(
                                meta.value)
                    self.assertNotEqual(backup_target, None)
                    workload_path = os.path.join(
                        backup_target.mount_path, "workload_" + workload.id)

                    self.assertTrue(os.path.exists(workload_path))

                    current_project_id = self.context.project_id
                    self.context.project_id = str(uuid.uuid4())
                    self.assertRaises(exception.InvalidWorkload,
                                      self.workload_transfer_api.create,
                                      self.context,
                                      workload_id,
                                      "test_transfer")
                    self.context.project_id = current_project_id

                    self.db.workload_update(self.context, workload['id'],
                                            {'status': 'notavailable'})
                    self.assertRaises(exception.InvalidState,
                                      self.workload_transfer_api.create,
                                      self.context,
                                      workload_id,
                                      "test_transfer")
                    self.db.workload_update(self.context, workload['id'],
                                            {'status': 'available'})

                    transfer_rec = self.workload_transfer_api.create(
                        self.context, workload_id, "test-transfer")

                    self.assertEqual(set(['id',
                                          'workload_id',
                                          'display_name',
                                          'auth_key',
                                          'created_at']),
                                     set(transfer_rec.keys()))

                    self.assertEqual(
                        transfer_rec['workload_id'], workload['id'])

                    rec = self.workload_transfer_api.get(
                        self.context, transfer_rec['id'])
                    self.assertEqual(transfer_rec['id'], rec['id'])

                    self.assertRaises(exception.TransferNotAllowed,
                                      self.workload_transfer_api.accept,
                                      self.context,
                                      rec['id'], transfer_rec['auth_key'])

                    with patch.object(workloadmgr.db, 'workload_get') as workload_get_mock:
                        def workload_get_stub(context, wid):
                            if 'import_done' not in self.stash:
                                raise exception.WorkloadNotFound(
                                    workload_id=wid)
                            else:
                                return bunchify(self.stash)
                        workload_get_mock.side_effect = workload_get_stub
                        saved_project_id = self.context.project_id
                        new_id = self.context.project_id = str(uuid.uuid4())
                        self.context.tenant_id = self.context.project_id
                        trans_rec = self.workload_transfer_api.accept(
                            self.context, rec['id'], transfer_rec['auth_key'])
                        self.context.project_id = saved_project_id
                        self.context.tenant_id = self.context.project_id

                    with patch.object(workloadmgr.workloads.api.API,
                                      'workload_reset', return_value=None) as mock_method3:
                        # invalid transfer id should throw exception
                        self.assertRaises(exception.TransferNotFound,
                                          self.workload_transfer_api.complete,
                                          self.context,
                                          'fakeid')

                        # workload in available state should raise exception
                        self.db.workload_update(self.context, workload_id,
                                                {'status': 'available'})
                        self.assertRaises(exception.InvalidState,
                                          self.workload_transfer_api.complete,
                                          self.context,
                                          rec['id'])
                        self.db.workload_update(
                            self.context, workload_id, {
                                'status': 'transfer-in-progress'})

                        # same project id should throws an exception
                        saved_project_id = self.context.project_id
                        self.context.project_id = new_id
                        self.context.tenant_id = self.context.project_id
                        self.assertRaises(exception.InvalidState,
                                          self.workload_transfer_api.complete,
                                          self.context,
                                          rec['id'])
                        self.context.project_id = saved_project_id
                        self.context.tenant_id = self.context.project_id

                        # good path
                        self.workload_transfer_api.complete(
                            self.context, rec['id'])

                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
                    self.assertRaises(exception.TransferNotFound,
                                      self.workload_transfer_api.get,
                                      self.context,
                                      rec['id'])
