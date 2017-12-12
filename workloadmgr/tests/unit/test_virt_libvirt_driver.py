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


class BaseLibvirtDriverTestCase(test.TestCase):
    """Test Case for workload_utils."""

    def setUp(self):
        super(BaseLibvirtDriverTestCase, self).setUp()

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

        super(BaseLibvirtDriverTestCase, self).tearDown()

    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_apply_retention_policy_with_incrementals(
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
        from workloadmgr.virt import driver

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
                        for snapshot in snapshots[1:]:
                            self.db.snapshot_update(
                                self.context, snapshot['id'], {
                                    'snapshot_type': 'incremental'})
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

                        workload_driver = driver.load_compute_driver(
                            None,
                            compute_driver='libvirt.LibvirtDriver')
                        workload_driver.apply_retention_policy(
                            self.context, self.db,
                            tests_utils.get_instances(),
                            snapshots[0].__dict__)  # Latest snapshot

                        retained_snapshots = self.db.snapshot_get_all_by_project_workload(
                            self.context, self.context.project_id, workload.id)
                        self.assertEqual(len(retained_snapshots), 3)
                        self.assertEqual(set([s.id for s in retained_snapshots]),
                                         set([s.id for s in snapshots[0:3]]))
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
    def test_apply_retention_policy_with_combination(
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
        from workloadmgr.virt import driver

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

                        workload_driver = driver.load_compute_driver(
                            None,
                            compute_driver='libvirt.LibvirtDriver')

                        workload_driver.apply_retention_policy(
                            self.context, self.db,
                            tests_utils.get_instances(),
                            snapshots[0].__dict__)  # Latest snapshot

                        retained_snapshots = self.db.snapshot_get_all_by_project_workload(
                            self.context, self.context.project_id, workload.id)

                        self.assertEqual(len(retained_snapshots), 7)
                        self.assertEqual(set([s.id for s in retained_snapshots]),
                                         set([s.id for s in snapshots[0:7]]))

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
    def test_apply_retention_policy_with_deleted_snaps(
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
        from workloadmgr.virt import driver

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
                        workload_driver = driver.load_compute_driver(
                            None,
                            compute_driver='libvirt.LibvirtDriver')

                        workload_driver.apply_retention_policy(
                            self.context, self.db,
                            tests_utils.get_instances(),
                            snapshots[0].__dict__)  # Latest snapshot

                        retained_snapshots = self.db.snapshot_get_all_by_project_workload(
                            self.context, self.context.project_id, workload.id)

                        self.assertEqual(len(retained_snapshots), 3)
                        self.assertEqual(set([s.id for s in retained_snapshots]),
                                         set([s.id for s in snapshots[0:3]]))

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

    @patch('workloadmgr.image.glance.GlanceImageService.show')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.network.neutron.API.get_routers')
    @patch('workloadmgr.network.neutron.API.get_ports')
    @patch('workloadmgr.network.neutron.API.get_port')
    @patch('workloadmgr.network.neutron.API.server_security_groups')
    @patch('workloadmgr.network.neutron.API.get_network')
    @patch('workloadmgr.network.neutron.API.get_networks')
    @patch('workloadmgr.network.neutron.API.get_subnets_from_port')
    @patch('workloadmgr.compute.nova.API.vast_finalize')
    @patch('workloadmgr.compute.nova.API.vast_data_transfer')
    @patch('workloadmgr.compute.nova.API.vast_get_info')
    @patch('workloadmgr.compute.nova.API.vast_thaw')
    @patch('workloadmgr.compute.nova.API.vast_async_task_status')
    @patch('workloadmgr.compute.nova.API.vast_instance')
    @patch('workloadmgr.compute.nova.API.vast_freeze')
    @patch('workloadmgr.compute.nova.API.get_interfaces')
    @patch('workloadmgr.compute.nova.API.vast_prepare')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_apply_retention_policy_with_incrementals_with_data(
            self,
            mock_get_servers,
            set_meta_item_mock,
            delete_meta_mock,
            get_server_by_id_mock,
            get_flavor_by_id_mock,
            vast_prepare_mock,
            get_interfaces_mock,
            vast_freeze_mock,
            vast_instance_mock,
            vast_async_task_status_mock,
            vast_thaw_mock,
            vast_get_info_mock,
            vast_data_transfer_mock,
            vast_finalize,
            get_subnets_from_port_mock,
            get_networks_mock,
            get_network_mock,
            server_security_groups_mock,
            get_port_mock,
            get_ports_mock,
            get_routers_mock,
            get_volume_mock,
            image_show_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager
        from workloadmgr.workloads import workload_utils
        from workloadmgr.virt import driver

        vast_async_task_status_mock.return_value = {'status': ['Completed']}
        get_routers_mock.side_effect = tests_utils._routers_data
        get_interfaces_mock.side_effect = tests_utils._get_interfaces
        get_port_mock.side_effect = tests_utils._port_data
        get_ports_mock.side_effect = tests_utils._router_ports
        get_subnets_from_port_mock.side_effect = tests_utils._subnets_data
        get_network_mock.side_effect = tests_utils._network
        mock_get_servers.side_effect = tests_utils.get_vms
        get_server_by_id_mock.side_effect = tests_utils.get_server_by_id
        get_flavor_by_id_mock.side_effect = tests_utils.get_flavor_by_id
        get_volume_mock.side_effect = tests_utils.get_volume_id
        vast_get_info_mock.side_effect = tests_utils._snapshot_data_ex
        image_show_mock.side_effect = tests_utils.get_glance_image

        def vast_data_transfer_mock_side(*args, **kwargs):
            #'/tmp/triliovault-mounts/c2VydmVyMzpuZnNzaGFyZTM=/workload_8e9bb422-6520-433e-945e-e89bc25c3448/snapshot_1effe039-3b68-47da-8924-2fd709a828a5/vm_id_4f92587b-cf3a-462a-89d4-0f5634293477/vm_res_id_9959a33a-9d77-41f9-adef-cf47ebdd89d3_vda/2456b34a-e981-4828-b386-6d122781a72f'
            path = os.path.join(
                "/tmp/triliovault-mounts/c2VydmVyMzpuZnNzaGFyZTM=",
                "workload_" +
                args[2]['metadata']['workload_id'],
                "snapshot_" +
                args[2]['metadata']['snapshot_id'],
                "vm_id_" +
                args[2]['metadata']['snapshot_vm_id'],
                "vm_res_id_" +
                args[2]['metadata']['snapshot_vm_resource_id'] +
                "_" +
                args[2]['metadata']['snapshot_vm_resource_name'],
                args[2]['metadata']['vm_disk_resource_snap_id'])
            tests_utils.create_qcow2_image(path)
            return {'result': ['Completed']}

        vast_data_transfer_mock.side_effect = vast_data_transfer_mock_side
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

                        workload = self.db.workload_get(
                            self.context, workload['id'])
                        backup_target = None
                        for meta in workload.metadata:
                            if meta.key == 'backup_media_target':
                                backup_target = workloadmgr.vault.vault.get_backup_target(
                                    meta.value)
                        self.assertNotEqual(backup_target, None)

                        workload_path = os.path.join(backup_target.mount_path,
                                                     "workload_" + workload_id)
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
                            self.assertEqual(
                                snapshot.display_name, 'test_snapshot')
                            self.assertEqual(snapshot.status, 'available')

                            workload_db = backup_target.get_object(
                                os.path.join(workload_path, "workload_db"))
                            snapshot_path = os.path.join(
                                workload_path, "snapshot_" + snapshot.id)
                            self.assertTrue(os.path.exists(snapshot_path))

                            wdb = json.loads(workload_db)
                            self.assertEqual(workload.id, wdb['id'])
                            snapshots.append(snapshot)

                        snapshots.reverse()
                        for snapshot in snapshots[1:]:
                            self.db.snapshot_update(
                                self.context, snapshot['id'], {
                                    'snapshot_type': 'incremental'})
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

                        workload_driver = driver.load_compute_driver(
                            None,
                            compute_driver='libvirt.LibvirtDriver')
                        workload_driver.apply_retention_policy(
                            self.context, self.db,
                            tests_utils.get_instances(),
                            snapshots[0].__dict__)  # Latest snapshot
                        workload_driver.apply_retention_policy(
                            self.context, self.db,
                            tests_utils.get_instances(),
                            snapshots[0].__dict__)  # Latest snapshot

                        retained_snapshots = self.db.snapshot_get_all_by_project_workload(
                            self.context, self.context.project_id, workload.id)
                        self.assertEqual(len(retained_snapshots), 3)
                        self.assertEqual(set([s.id for s in retained_snapshots]),
                                         set([s.id for s in snapshots[0:3]]))
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
