# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.
import __builtin__
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


class BaseWorkloadUtilTestCase(test.TestCase):
    """Test Case for workload_utils."""

    def setUp(self):
        super(BaseWorkloadUtilTestCase, self).setUp()

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
        self.workloadAPI = API()
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

        super(BaseWorkloadUtilTestCase, self).tearDown()

    @patch('subprocess.check_call')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
    def test_upload_settings_db_entry(self, mock_method1, mock_method2,
                                      mock_method3):

        import workloadmgr.vault.vault
        from workloadmgr.workloads import workload_utils

        mock_method2.side_effect = self.nfsshares
        backup_target = workloadmgr.vault.vault.get_backup_target(
            'server3:nfsshare3')
        fileutils.ensure_tree(
            os.path.join(
                backup_target.mount_path,
                CONF.cloud_unique_id))
        with open(os.path.join(backup_target.mount_path,
                               CONF.cloud_unique_id, "settings_db"), "w") as f:
            f.write(json.dumps([]))

        for s in self.db.setting_get_all(self.context, read_deleted='no'):
            try:
                self.db.setting_delete(self.context, s.name)
            except BaseException:
                pass

        for s in range(10):
            setting = {u'category': "fake",
                       u'name': "fake-%d" % s,
                       u'description': "Controls fake scheduler status",
                       u'value': True,
                       u'user_id': self.context.user_id,
                       u'project_id': self.context.project_id,
                       u'tenant_id': self.context.tenant_id,
                       u'is_public': False,
                       u'is_hidden': True,
                       u'metadata': {},
                       u'type': "fake-scheduler-setting", }

            sdb = self.db.setting_create(self.context, setting)

        workload_utils.upload_settings_db_entry(self.context)

        settings_db = self.db.setting_get_all(self.context, read_deleted='no')
        self.assertEqual(len(settings_db), 10)

        settings_path = os.path.join(backup_target.mount_path,
                                     CONF.cloud_unique_id, "settings_db")
        settings_json = backup_target.get_object(settings_path)
        settings = json.loads(settings_json)
        self.assertEqual(len(settings), 10)

        for s in self.db.setting_get_all(None, read_deleted='no'):
            try:
                self.db.setting_delete(self.context, s.name)
            except BaseException:
                pass

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    def test_upload_workload_db_entry(self,
                                      set_meta_item_mock,
                                      delete_meta_mock,
                                      get_server_by_id_mock,
                                      get_flavor_by_id_mock,
                                      get_volume_mock):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
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
                    self.workload_params['instances'] = tests_utils.get_instances(
                    )
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

                    workload_utils.upload_workload_db_entry(
                        self.context, workload_id)

                    workload = self.db.workload_get(self.context, workload_id)

                    backup_target = None
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            backup_target = workloadmgr.vault.vault.get_backup_target(
                                meta.value)
                    self.assertNotEqual(backup_target, None)

                    workload_path = os.path.join(backup_target.mount_path,
                                                 "workload_" + workload_id)
                    workload_db = backup_target.get_object(
                        os.path.join(workload_path, "workload_db"))
                    wdb = json.loads(workload_db)
                    self.assertEqual(workload.id, wdb['id'])

                    self.workload.workload_delete(self.context, workload_id)
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_upload_snapshot_db_entry(self, mock_get_servers, m2,
                                      set_meta_item_mock,
                                      delete_meta_mock,
                                      get_server_by_id_mock,
                                      get_flavor_by_id_mock,
                                      get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                            self.workload_params['instances'] = tests_utils.get_instances(
                            )
                            workload = tests_utils.create_workload(
                                self.context,
                                availability_zone=CONF.storage_availability_zone,
                                workload_type_id=workload_type.id,
                                **self.workload_params)
                            workload_id = workload['id']
                            self.workload.workload_create(
                                self.context, workload_id)

                            snapshot = tests_utils.create_snapshot(
                                self.context,
                                workload_id,
                                display_name='test_snapshot',
                                display_description='this is a test snapshot',
                                snapshot_type='full',
                                status='creating')
                            self.workload.workload_snapshot(
                                self.context, snapshot['id'])
                            snapshot = self.db.snapshot_get(
                                self.context, snapshot['id'])
                            workload = self.db.workload_get(
                                self.context, workload['id'])
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            workload_utils.upload_snapshot_db_entry(
                                self.context, snapshot.id, snapshot_status=None)

                            backup_target = None
                            for meta in workload.metadata:
                                if meta.key == 'backup_media_target':
                                    backup_target = workloadmgr.vault.vault.get_backup_target(
                                        meta.value)
                            self.assertNotEqual(backup_target, None)

                            workload_path = os.path.join(
                                backup_target.mount_path, "workload_" + workload_id)
                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])

                            self.db.snapshot_delete(self.context, snapshot.id)
                            self.workload.workload_delete(
                                self.context, workload_id)
                            self.assertRaises(exception.NotFound,
                                              db.workload_get,
                                              self.context,
                                              workload_id)

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_snapshot_delete(self, mock_get_servers, m2,
                             set_meta_item_mock,
                             delete_meta_mock,
                             get_server_by_id_mock,
                             get_flavor_by_id_mock,
                             get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                        self.workload_params['instances'] = tests_utils.get_instances(
                        )
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(
                            self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(
                            self.context,
                            workload_id,
                            display_name='test_snapshot',
                            display_description='this is a test snapshot',
                            snapshot_type='full',
                            status='creating')
                        self.workload.workload_snapshot(
                            self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(
                            self.context, snapshot['id'])
                        workload = self.db.workload_get(
                            self.context, workload['id'])
                        self.assertEqual(
                            snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        backup_target = None
                        for meta in workload.metadata:
                            if meta.key == 'backup_media_target':
                                backup_target = workloadmgr.vault.vault.get_backup_target(
                                    meta.value)
                        self.assertNotEqual(backup_target, None)

                        workload_path = os.path.join(backup_target.mount_path,
                                                     "workload_" + workload_id)
                        workload_db = backup_target.get_object(
                            os.path.join(workload_path, "workload_db"))
                        snapshot_path = os.path.join(
                            workload_path, "snapshot_" + snapshot.id)
                        self.assertTrue(os.path.exists(snapshot_path))

                        wdb = json.loads(workload_db)
                        self.assertEqual(workload.id, wdb['id'])

                        workload_utils.snapshot_delete(
                            self.context, snapshot.id)
                        self.assertFalse(os.path.exists(snapshot_path))

                        self.db.snapshot_delete(self.context, snapshot.id)
                        self.workload.workload_delete(
                            self.context, workload_id)
                        self.assertRaises(exception.NotFound,
                                          db.workload_get,
                                          self.context,
                                          workload_id)

    def test_delete_if_chain(self):
        pass

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_common_apply_retention_policy_all_full(self, mock_get_servers, m2,
                                                    set_meta_item_mock,
                                                    delete_meta_mock,
                                                    get_server_by_id_mock,
                                                    get_flavor_by_id_mock,
                                                    get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                        self.workload_params['instances'] = tests_utils.get_instances(
                        )
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(
                            self.context, workload_id)

                        snapshots = []
                        for i in range(0, 5):
                            snapshot = tests_utils.create_snapshot(
                                self.context,
                                workload_id,
                                display_name='test_snapshot',
                                display_description='this is a test snapshot',
                                snapshot_type='full',
                                status='creating')
                            self.workload.workload_snapshot(
                                self.context, snapshot['id'])
                            snapshot = self.db.snapshot_get(
                                self.context, snapshot['id'])
                            workload = self.db.workload_get(
                                self.context, workload['id'])
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            backup_target = None
                            for meta in workload.metadata:
                                if meta.key == 'backup_media_target':
                                    backup_target = workloadmgr.vault.vault.get_backup_target(
                                        meta.value)
                            self.assertNotEqual(backup_target, None)

                            workload_path = os.path.join(
                                backup_target.mount_path, "workload_" + workload_id)
                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])
                            snapshots.append(snapshot)

                        snapshots.reverse()
                        # Call retension policy here
                        self.db.workload_update(self.context,
                                                workload_id,
                                                {'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                                                              'end_date': '07/05/2015',
                                                                              'interval': '1 hr',
                                                                              'start_time': '2:30 PM',
                                                                              'fullbackup_interval': '10',
                                                                              'retention_policy_type': 'Number of Snapshots to Keep',
                                                                              'retention_policy_value': '3'}),
                                                 })
                        snapshot_to_commit, snapshots_to_delete, affected_snapshots, \
                            workload_obj, snapshot_obj, dontcare = workload_utils.common_apply_retention_policy(
                                self.context,
                                tests_utils.get_instances(),
                                snapshots[0].__dict__)
                        self.assertEqual(len(snapshots_to_delete), 2)
                        self.assertEqual(set([s.id for s in snapshots_to_delete]),
                                         set([s.id for s in snapshots[3:5]]))
                        self.assertEqual(affected_snapshots, [])
                        self.assertEqual(
                            snapshot_to_commit['id'], snapshots[2]['id'])

                        for snapshot in snapshots:
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            workload_utils.snapshot_delete(
                                self.context, snapshot.id)
                            self.assertFalse(os.path.exists(snapshot_path))

                            self.db.snapshot_delete(self.context, snapshot.id)

                        self.workload.workload_delete(
                            self.context, workload_id)
                        self.assertRaises(exception.NotFound,
                                          db.workload_get,
                                          self.context,
                                          workload_id)

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_common_apply_retention_policy_with_incrementals(
            self,
            mock_get_servers,
            m2,
            set_meta_item_mock,
            delete_meta_mock,
            get_server_by_id_mock,
            get_flavor_by_id_mock,
            get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                        self.workload_params['instances'] = tests_utils.get_instances(
                        )
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(
                            self.context, workload_id)

                        snapshots = []
                        for i in range(0, 5):
                            snapshot = tests_utils.create_snapshot(
                                self.context,
                                workload_id,
                                display_name='test_snapshot',
                                display_description='this is a test snapshot',
                                snapshot_type='incremental',
                                status='creating')
                            self.workload.workload_snapshot(
                                self.context, snapshot['id'])
                            snapshot = self.db.snapshot_get(
                                self.context, snapshot['id'])
                            workload = self.db.workload_get(
                                self.context, workload['id'])
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            backup_target = None
                            for meta in workload.metadata:
                                if meta.key == 'backup_media_target':
                                    backup_target = workloadmgr.vault.vault.get_backup_target(
                                        meta.value)
                            self.assertNotEqual(backup_target, None)

                            workload_path = os.path.join(
                                backup_target.mount_path, "workload_" + workload_id)
                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])
                            snapshots.append(snapshot)

                        # Call retension policy here
                        snapshots.reverse()
                        self.db.workload_update(self.context,
                                                workload_id,
                                                {'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                                                              'end_date': '07/05/2015',
                                                                              'interval': '1 hr',
                                                                              'start_time': '2:30 PM',
                                                                              'fullbackup_interval': '10',
                                                                              'retention_policy_type': 'Number of Snapshots to Keep',
                                                                              'retention_policy_value': '3'}),
                                                 })
                        snapshot_to_commit, snapshots_to_delete, affected_snapshots, \
                            workload_obj, snapshot_obj, dontcare = workload_utils.common_apply_retention_policy(
                                self.context,
                                tests_utils.get_instances(),
                                snapshots[0].__dict__)
                        self.assertEqual(len(snapshots_to_delete), 2)
                        self.assertEqual(set([s.id for s in snapshots_to_delete]),
                                         set([s.id for s in snapshots[3:5]]))
                        self.assertEqual(affected_snapshots, [])
                        self.assertEqual(
                            snapshot_to_commit['id'], snapshots[2]['id'])

                        for snapshot in snapshots:
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            workload_utils.snapshot_delete(
                                self.context, snapshot.id)
                            self.assertFalse(os.path.exists(snapshot_path))

                            self.db.snapshot_delete(self.context, snapshot.id)

                        self.workload.workload_delete(
                            self.context, workload_id)
                        self.assertRaises(exception.NotFound,
                                          db.workload_get,
                                          self.context,
                                          workload_id)

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_common_apply_retention_policy_with_combination(
            self,
            mock_get_servers,
            m2,
            set_meta_item_mock,
            delete_meta_mock,
            get_server_by_id_mock,
            get_flavor_by_id_mock,
            get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                        self.workload_params['instances'] = tests_utils.get_instances(
                        )
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(
                            self.context, workload_id)

                        snapshots = []
                        for i in range(0, 15):
                            if i % 5 == 0:
                                snapshot_type = "full"
                            else:
                                snapshot_type = "incremental"
                            snapshot = tests_utils.create_snapshot(
                                self.context,
                                workload_id,
                                display_name='test_snapshot',
                                display_description='this is a test snapshot',
                                snapshot_type=snapshot_type,
                                status='creating')
                            self.workload.workload_snapshot(
                                self.context, snapshot['id'])
                            snapshot = self.db.snapshot_get(
                                self.context, snapshot['id'])
                            workload = self.db.workload_get(
                                self.context, workload['id'])
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            backup_target = None
                            for meta in workload.metadata:
                                if meta.key == 'backup_media_target':
                                    backup_target = workloadmgr.vault.vault.get_backup_target(
                                        meta.value)
                            self.assertNotEqual(backup_target, None)

                            workload_path = os.path.join(
                                backup_target.mount_path, "workload_" + workload_id)
                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])
                            snapshots.append(snapshot)

                        snap_to_delete = snapshots.pop(1)
                        snapshot_path = os.path.join(
                            workload_path, "snapshot_" + snap_to_delete.id)
                        workload_utils.snapshot_delete(
                            self.context, snap_to_delete.id)
                        self.assertFalse(os.path.exists(snapshot_path))

                        self.db.snapshot_delete(
                            self.context, snap_to_delete.id)

                        # Call retension policy here
                        snapshots.reverse()
                        self.db.workload_update(self.context,
                                                workload_id,
                                                {'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                                                              'end_date': '07/05/2015',
                                                                              'interval': '1 hr',
                                                                              'start_time': '2:30 PM',
                                                                              'fullbackup_interval': '10',
                                                                              'retention_policy_type': 'Number of Snapshots to Keep',
                                                                              'retention_policy_value': '7'}),
                                                 })
                        snapshot_to_commit, snapshots_to_delete, affected_snapshots, \
                            workload_obj, snapshot_obj, dontcare = workload_utils.common_apply_retention_policy(
                                self.context,
                                tests_utils.get_instances(),
                                snapshots[0].__dict__)
                        self.assertEqual(len(snapshots_to_delete), 7)
                        self.assertEqual(set([s.id for s in snapshots_to_delete]),
                                         set([s.id for s in snapshots[7:7 + 7]]))
                        self.assertEqual(affected_snapshots, [])
                        self.assertEqual(
                            snapshot_to_commit['id'], snapshots[6]['id'])

                        for snapshot in snapshots:
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            workload_utils.snapshot_delete(
                                self.context, snapshot.id)
                            self.assertFalse(os.path.exists(snapshot_path))

                            self.db.snapshot_delete(self.context, snapshot.id)

                        self.workload.workload_delete(
                            self.context, workload_id)
                        self.assertRaises(exception.NotFound,
                                          db.workload_get,
                                          self.context,
                                          workload_id)

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_common_apply_retention_policy_with_deleted_snaps(
            self,
            mock_get_servers,
            m2,
            set_meta_item_mock,
            delete_meta_mock,
            get_server_by_id_mock,
            get_flavor_by_id_mock,
            get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                        self.workload_params['instances'] = tests_utils.get_instances(
                        )
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(
                            self.context, workload_id)

                        snapshots = []
                        for i in range(0, 5):
                            snapshot = tests_utils.create_snapshot(
                                self.context,
                                workload_id,
                                display_name='test_snapshot',
                                display_description='this is a test snapshot',
                                snapshot_type='full',
                                status='creating')
                            self.workload.workload_snapshot(
                                self.context, snapshot['id'])
                            snapshot = self.db.snapshot_get(
                                self.context, snapshot['id'])
                            workload = self.db.workload_get(
                                self.context, workload['id'])
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            backup_target = None
                            for meta in workload.metadata:
                                if meta.key == 'backup_media_target':
                                    backup_target = workloadmgr.vault.vault.get_backup_target(
                                        meta.value)
                            self.assertNotEqual(backup_target, None)

                            workload_path = os.path.join(
                                backup_target.mount_path, "workload_" + workload_id)
                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])
                            snapshots.append(snapshot)

                        snap_to_delete = snapshots.pop(1)
                        snapshot_path = os.path.join(
                            workload_path, "snapshot_" + snap_to_delete.id)
                        workload_utils.snapshot_delete(
                            self.context, snap_to_delete.id)
                        self.assertFalse(os.path.exists(snapshot_path))

                        self.db.snapshot_delete(
                            self.context, snap_to_delete.id)

                        snapshots.reverse()
                        # Call retension policy here
                        self.db.workload_update(self.context,
                                                workload_id,
                                                {'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                                                              'end_date': '07/05/2015',
                                                                              'interval': '1 hr',
                                                                              'start_time': '2:30 PM',
                                                                              'fullbackup_interval': '10',
                                                                              'retention_policy_type': 'Number of Snapshots to Keep',
                                                                              'retention_policy_value': '3'}),
                                                 })
                        snapshot_to_commit, snapshots_to_delete, affected_snapshots, \
                            workload_obj, snapshot_obj, dontcare = workload_utils.common_apply_retention_policy(
                                self.context,
                                tests_utils.get_instances(),
                                snapshots[0].__dict__)
                        self.assertEqual(len(snapshots_to_delete), 1)
                        self.assertEqual(affected_snapshots, [])
                        self.assertEqual(
                            snapshot_to_commit['id'], snapshots[2]['id'])

                        for snapshot in snapshots:
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            workload_utils.snapshot_delete(
                                self.context, snapshot.id)
                            self.assertFalse(os.path.exists(snapshot_path))

                            self.db.snapshot_delete(self.context, snapshot.id)

                        self.workload.workload_delete(
                            self.context, workload_id)
                        self.assertRaises(exception.NotFound,
                                          db.workload_get,
                                          self.context,
                                          workload_id)

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_common_apply_retention_snap_delete(self, mock_get_servers, m2,
                                                set_meta_item_mock,
                                                delete_meta_mock,
                                                get_server_by_id_mock,
                                                get_flavor_by_id_mock,
                                                get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                        self.workload_params['instances'] = tests_utils.get_instances(
                        )
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(
                            self.context, workload_id)

                        snapshots = []
                        for i in range(0, 3):
                            snapshot = tests_utils.create_snapshot(
                                self.context,
                                workload_id,
                                display_name='test_snapshot',
                                display_description='this is a test snapshot',
                                snapshot_type='full',
                                status='creating')
                            self.workload.workload_snapshot(
                                self.context, snapshot['id'])
                            snapshot = self.db.snapshot_get(
                                self.context, snapshot['id'])
                            workload = self.db.workload_get(
                                self.context, workload['id'])
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            backup_target = None
                            for meta in workload.metadata:
                                if meta.key == 'backup_media_target':
                                    backup_target = workloadmgr.vault.vault.get_backup_target(
                                        meta.value)
                            self.assertNotEqual(backup_target, None)

                            workload_path = os.path.join(
                                backup_target.mount_path, "workload_" + workload_id)
                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])
                            snapshots.append(snapshot)

                        for snapshot in snapshots:
                            workload_utils.common_apply_retention_snap_delete(
                                self.context, snapshot, workload)

                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertFalse(os.path.exists(snapshot_path))

                            self.assertRaises(exception.NotFound,
                                              self.db.snapshot_get,
                                              self.context, snapshot.id)

                        self.workload.workload_delete(
                            self.context, workload_id)
                        self.assertRaises(exception.NotFound,
                                          db.workload_get,
                                          self.context,
                                          workload_id)

    def test_common_apply_retention_disk_check(self):
        # def test_common_apply_retention_disk_check(cntx, snapshot_to_commit,
        # snap, workload_obj):
        pass

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_common_apply_retention_disk_check(self, mock_get_servers, m2,
                                               set_meta_item_mock,
                                               delete_meta_mock,
                                               get_server_by_id_mock,
                                               get_flavor_by_id_mock,
                                               get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils

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
            'host': CONF.host, }

        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [
                            {
                                'server1:nfsshare1': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server2:nfsshare2': [
                                    1099511627776, 1099511627776], }.values()[0], {
                                'server3:nfsshare3': [
                                    1099511627776, 7 * 10737418240], }.values()[0], ]

                        mock_method2.side_effect = values

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

                        self.workload_params['instances'] = tests_utils.get_instances(
                        )
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(
                            self.context, workload_id)

                        snapshots = []
                        for i in range(0, 5):
                            snapshot = tests_utils.create_snapshot(
                                self.context,
                                workload_id,
                                display_name='test_snapshot',
                                display_description='this is a test snapshot',
                                snapshot_type='full',
                                status='creating')
                            self.workload.workload_snapshot(
                                self.context, snapshot['id'])
                            snapshot = self.db.snapshot_get(
                                self.context, snapshot['id'])
                            workload = self.db.workload_get(
                                self.context, workload['id'])
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            backup_target = None
                            for meta in workload.metadata:
                                if meta.key == 'backup_media_target':
                                    backup_target = workloadmgr.vault.vault.get_backup_target(
                                        meta.value)
                            self.assertNotEqual(backup_target, None)

                            workload_path = os.path.join(
                                backup_target.mount_path, "workload_" + workload_id)
                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])
                            snapshots.append(snapshot)

                        snapshots.reverse()
                        # Call retension policy here
                        self.db.workload_update(self.context,
                                                workload_id,
                                                {'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                                                              'end_date': '07/05/2015',
                                                                              'interval': '1 hr',
                                                                              'start_time': '2:30 PM',
                                                                              'fullbackup_interval': '10',
                                                                              'retention_policy_type': 'Number of Snapshots to Keep',
                                                                              'retention_policy_value': '3'}),
                                                 })

                        snapshot_to_commit, snapshots_to_delete, affected_snapshots, \
                            workload_obj, snapshot_obj, dontcare = workload_utils.common_apply_retention_policy(
                                self.context,
                                tests_utils.get_instances(),
                                snapshots[0].__dict__)

                        self.assertEqual(len(snapshots_to_delete), 2)
                        self.assertEqual(affected_snapshots, [])
                        self.assertEqual(
                            snapshot_to_commit['id'], snapshots[2]['id'])

                        workload_utils. common_apply_retention_disk_check(
                            self.context, snapshot_to_commit, snapshot_obj, workload_obj)

                        for snapshot in snapshots:
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            workload_utils.snapshot_delete(
                                self.context, snapshot.id)
                            self.assertFalse(os.path.exists(snapshot_path))

                            self.db.snapshot_delete(self.context, snapshot.id)

                        self.workload.workload_delete(
                            self.context, workload_id)
                        self.assertRaises(exception.NotFound,
                                          db.workload_get,
                                          self.context,
                                          workload_id)

    def test_common_apply_retention_db_backing_update(self):

        # def common_apply_retention_db_backing_update(cntx, snapshot_vm_resource,
        #                                     vm_disk_resource_snap,
        #                                     vm_disk_resource_snap_backing,
        #                                     affected_snapshots):
        pass
