# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.
import cPickle as pickle
import json
import os
import shutil
import uuid

from mock import patch
from bunch import bunchify
from oslo.config import cfg

from workloadmgr import context
from workloadmgr import test
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import importutils
from workloadmgr.tests.unit import utils as tests_utils
from workloadmgr.vault import vault

CONF = cfg.CONF

class BaseReassignAPITestCase(test.TestCase):
    """Test Case for Reassign API ."""

    def setUp(self):
        super(BaseReassignAPITestCase, self).setUp()

        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        self.context = context.get_admin_context()
        self.stderr_patch = patch('sys.stderr')
        self.stderr_patch.start()

        self.is_online_patch = patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')
        self.project_list_for_import =  patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV2.get_project_list_for_import')
        self.user_exist_in_tenant = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV2.user_exist_in_tenant')
        self.project_list_for_importV3 = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV3.get_project_list_for_import')
        self.user_exist_in_tenantV3 = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV3.user_exist_in_tenant')
        self.user_list_patch = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClient.get_user_list')
        self.keystone_client_patch = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClient')

        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.ProjectListMockMethod = self.project_list_for_import.start()
        self.UserExistMockMethod = self.user_exist_in_tenant.start()
        self.ProjectListMockMethodV3 = self.project_list_for_importV3.start()
        self.UserExistMockMethodV3 = self.user_exist_in_tenantV3.start()
        self.UserListMockMethod = self.user_list_patch.start()
        self.KeystoneClientMock = self.keystone_client_patch.start()

        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True
        self.UserExistMockMethod.return_value = True
        self.UserExistMockMethodV3.return_value = True

        self.workload = importutils.import_object(CONF.workloads_manager)
        from workloadmgr.workloads.api import API
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = str(uuid.uuid4())
        self.context.tenant_id = self.context.project_id
        self.UserListMockMethod.return_value = [bunchify({'id': str(self.context.user_id)})]

    def tearDown(self):
        #Delete all workloads and snapshots from database
        for workload in self.db.workload_get_all(self.context):
            snapshots = self.db.snapshot_get_all_by_workload(self.context, workload['id'])
            for snapshot in snapshots:
                self.db.snapshot_delete(self.context, snapshot['id'])
            self.db.workload_delete(self.context, workload['id'])

        for share in ['server1:nfsshare1', 'server2:nfsshare2', 'server3:nfsshare3']:
            backup_target = vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)

        self.is_online_patch.stop()
        self.subprocess_patch.stop()
        self.stderr_patch.stop()
        self.project_list_for_importV3.stop()
        self.user_exist_in_tenantV3.stop()
        self.keystone_client_patch.stop()

        super(BaseReassignAPITestCase, self).tearDown()

    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
    def create_workload(self, capacity_mock):
        values = [{'server1:nfsshare1': [1099511627776, 0],}.values()[0],
                  {'server2:nfsshare2': [1099511627776, 0],}.values()[0],
                  {'server3:nfsshare3': [1099511627776, 0],}.values()[0], ]

        capacity_mock.return_value = None
        capacity_mock.side_effect = values
        type_id = tests_utils.create_workload_type(self.context)
        jobschedule = pickle.dumps({'start_date': '06/05/2014',
                                    'end_date': '07/05/2015',
                                    'interval': '1 hr',
                                    'start_time': '2:30 PM',
                                    'fullbackup_interval': -1,
                                    'retention_policy_type': 'Number of Snapshots to Keep',
                                    'retention_policy_value': '30'})
        workload = tests_utils.create_workload(self.context, workload_type_id=type_id.id, jobschedule=jobschedule)
        workload = workload.__dict__
        workload.pop('_sa_instance_state')
        workload.pop('created_at')
        workload['workload_id'] = workload['id']
        backup_endpoint = vault.get_nfs_share_for_workload_by_free_overcommit(self.context,
                                                                                                workload)
        # write json here
        backup_target = vault.get_backup_target(backup_endpoint)
        workload['metadata'] = [{'key': 'backup_media_target', 'value': backup_target.mount_path}]
        workload_path = os.path.join(backup_target.mount_path, "workload_" + workload['id'])
        os.mkdir(workload_path)
        workload_json_file = os.path.join(workload_path, "workload_db")
        with open(workload_json_file, "w") as f:
            f.write(json.dumps(workload))
        return workload

    def create_snapshot(self, workload):

        snapshot = tests_utils.create_snapshot(self.context, workload['id'])
        snapshot = snapshot.__dict__
        snapshot.pop('_sa_instance_state')
        snapshot.pop('created_at')
        for meta in workload['metadata']:
            if meta['key'] == 'backup_media_target':
                backup_target = meta['value']
        workload_path = os.path.join(backup_target, "workload_" + workload['id'])
        snap_path = os.path.join(workload_path, "snapshot_" + snapshot['id'])
        fileutils.ensure_tree(snap_path)
        with open(os.path.join(snap_path, 'snapshot_db'), "w") as f:
            f.write(json.dumps(snapshot))
        return snapshot

    @patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClient')
    def test_orphan_workload_list_with_existing_tenant_and_user(self, keysstoneclient):

        tenant_list = [bunchify({'id': self.context.project_id })]
        self.ProjectListMockMethod.return_value = tenant_list
        self.ProjectListMockMethodV3.return_value = tenant_list

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)
        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        workloads = self.workloadAPI.get_orphaned_workloads_list(self.context)
        self.assertEqual(len(workloads), 5)

    def test_orphan_workload_list_with_non_existing_tenant(self):

        tenant_list = [bunchify({'id': str(uuid.uuid4()) })]
        self.ProjectListMockMethod.return_value = [bunchify({'id': str(uuid.uuid4()) })]
        self.ProjectListMockMethodV3.return_value = [bunchify({'id': str(uuid.uuid4()) })]

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)
        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        workloads = self.workloadAPI.get_orphaned_workloads_list(self.context)
        self.assertEqual(len(workloads), 5)

    def test_orphan_workload_list_with_non_existing_user(self):

        self.UserExistMockMethod.return_value = False
        self.UserExistMockMethodV3.return_value = False
        self.UserListMockMethod.return_value = [bunchify({'id':  str(uuid.uuid4()) })]
        tenant_list = [bunchify({'id': self.context.project_id })]
        self.ProjectListMockMethod.return_value = tenant_list
        self.ProjectListMockMethodV3.return_value = tenant_list

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)
        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)
        workloads = self.workloadAPI.get_orphaned_workloads_list(self.context)
        self.assertEqual(len(workloads), 5)

    def test_orphan_workload_list_with_existing_tenant_and_user_with_migrate_cloud(self):

        tenant_list = [bunchify({'id': self.context.project_id})]
        self.ProjectListMockMethod.return_value = tenant_list
        self.ProjectListMockMethodV3.return_value = tenant_list

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for workload in workloads:
            for i in range(5):
                snapshot = self.create_snapshot(workload)
                self.db.snapshot_delete(self.context, snapshot['id'])
            self.db.workload_delete(self.context, workload['id'])
        workloads = self.workloadAPI.get_orphaned_workloads_list(self.context, migrate_cloud=True)
        self.assertEqual(len(workloads), 5)

    def test_orphan_workload_list_with_non_exist_tenant_with_migrate_cloud(self):

        tenant_list = [bunchify({'id': str(uuid.uuid4())})]
        self.ProjectListMockMethod.return_value = tenant_list
        self.ProjectListMockMethodV3.return_value = tenant_list

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for workload in workloads:
            for i in range(5):
                snapshot = self.create_snapshot(workload)
                self.db.snapshot_delete(self.context, snapshot['id'])
            self.db.workload_delete(self.context, workload['id'])

        workloads = self.workloadAPI.get_orphaned_workloads_list(self.context, migrate_cloud=True)
        self.assertEqual(len(workloads), 5)

    def test_orphan_workload_list_with_non_exist_user_with_migrate_cloud(self):

        self.UserExistMockMethod.return_value = False
        self.UserExistMockMethodV3.return_value = False
        tenant_list = [bunchify({'id': str(uuid.uuid4())})]
        self.ProjectListMockMethod .return_value = tenant_list
        self.ProjectListMockMethodV3.return_value = tenant_list

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for workload in workloads:
            for i in range(5):
                snapshot = self.create_snapshot(workload)
                self.db.snapshot_delete(self.context, snapshot['id'])
            self.db.workload_delete(self.context, workload['id'])

        workloads = self.workloadAPI.get_orphaned_workloads_list(self.context, migrate_cloud=True)
        self.assertEqual(len(workloads), 5)
    
