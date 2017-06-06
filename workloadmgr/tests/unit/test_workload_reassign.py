# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.
import cPickle as pickle
import json
import os
import shutil
import uuid

from bunch import bunchify
from mock import patch
from oslo.config import cfg

from workloadmgr import context
from workloadmgr import test
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import importutils
from workloadmgr.tests.unit import utils as tests_utils
from workloadmgr import exception as wlm_exceptions
from workloadmgr.vault import vault
from workloadmgr.db.sqlalchemy.session import get_session

CONF = cfg.CONF

global_old_tenant_id = [str(uuid.uuid4())]
global_new_tenant_id = [str(uuid.uuid4())]

def _return_tenant_list(*argv, **kwargs):
    tenant_list = []
    for tid in global_old_tenant_id + global_new_tenant_id:
        tenant_list.append(bunchify({'id': tid}))

    return tenant_list

def _user_in_tenant(*argv, **kwargs):
    return not 'fake' in argv

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
        self.keystone_client = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClient')
        self.project_list_for_import = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV2.get_project_list_for_import')
        self.user_exist_in_tenant = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV2.user_exist_in_tenant')
        self.user_role = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV2.check_user_role')
        self.project_list_for_importV3 = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV3.get_project_list_for_import')
        self.user_exist_in_tenantV3 = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV3.user_exist_in_tenant')
        self.user_roleV3 = patch('workloadmgr.common.workloadmgr_keystoneclient.KeystoneClientV3.check_user_role')

        self.KeystoneClient = self.keystone_client.start()
        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        #self.ProjectListMockMethod = self.project_list_for_import.start()
        #self.UserExistMockMethod = self.user_exist_in_tenant.start()
        self.ProjectListMockMethod = self.KeystoneClient().client.get_project_list_for_import
        self.UserExistMockMethod = self.KeystoneClient().client.user_exist_in_tenant
        self.UserRoleMockMethod = self.user_role.start()
        self.ProjectListMockMethodV3 = self.project_list_for_importV3.start()
        self.UserExistMockMethodV3 = self.user_exist_in_tenantV3.start()
        self.UserRoleMockMethodV3 = self.user_roleV3.start()

        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True
        self.UserExistMockMethod.return_value = True
        self.UserRoleMockMethod.return_value = True
        self.ProjectListMockMethodV3.return_value = True
        self.UserExistMockMethodV3.return_value = True
        self.UserRoleMockMethodV3.return_value = True

        self.workload = importutils.import_object(CONF.workloads_manager)
        from workloadmgr.workloads.api import API
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = str(uuid.uuid4())

        global global_old_tenant_id
        self.context.tenant_id = self.context.project_id
        global_old_tenant_id = [self.context.tenant_id]

        self.ProjectListMockMethod.side_effect = _return_tenant_list
        self.UserExistMockMethod.side_effect = _user_in_tenant

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
        #self.project_list_for_import.stop()
        #self.user_exist_in_tenant.stop()
        self.user_role.stop()
        self.project_list_for_importV3.stop()
        self.user_exist_in_tenantV3.stop()
        self.user_roleV3.stop()
        self.stderr_patch.stop()
        self.KeystoneClient.stop()

        super(BaseReassignAPITestCase, self).tearDown()

    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
    def create_workload(self, capacity_mock):
        values = [{'server1:nfsshare1': [1099511627776, 0],}.values()[0],
                  {'server2:nfsshare2': [1099511627776, 0],}.values()[0],
                  {'server3:nfsshare3': [1099511627776, 0],}.values()[0], ]

        capacity_mock.return_value = None
        capacity_mock.side_effect = values
        type_id = tests_utils.create_workload_type(self.context)
        jobschedule =  pickle.dumps({
                            'enabled': True,
                            'start_date': '06/05/2014',
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

    def test_reassign_for_idempotent(self):
        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]

        new_tenant_id = global_new_tenant_id[0]
        old_tenant_id = self.context.project_id

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': [workload['id'] for workload in workloads],
             'migrate_cloud': False
             }
        ]
        with patch('sqlalchemy.orm.session.Session.bulk_update_mappings') as bulk_update:
            def side_effect(*args, **kwargs):
                if args[0].__tablename__ != 'workloads':
                    raise wlm_exceptions.DBError('DB crashed.')

            bulk_update.side_effect = side_effect
            self.assertRaises(wlm_exceptions.DBError, self.workloadAPI.workloads_reassign, self.context, tenant_map)

        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_for_idempotent_with_migrate(self):
        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        old_tenant_id = self.context.project_id

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

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': True
             }

        ]

        with patch('workloadmgr.workloads.api.API.import_workloads') as import_workload_mock:
            import_workload_mock.side_effect = wlm_exceptions.DBError('DB crashed.')
            self.assertRaises(wlm_exceptions.DBError, self.workloadAPI.workloads_reassign, self.context, tenant_map)

        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_single_old_tenant(self):
        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        old_tenant_id = self.context.project_id

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)
        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': False
             }
        ]
        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_multiple_old_tenant(self):
        global global_new_tenant_id

        global_new_tenant_id = [str(uuid.uuid4()) for x in range(5)]
        new_tenant_id = global_new_tenant_id[0]

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for project_id in global_new_tenant_id[1:]:
            self.context.project_id = project_id
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            self.context.project_id = w['project_id']
            for i in range(5):
                self.create_snapshot(w)

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': global_new_tenant_id[1:],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': False
             }
        ]
        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_non_existing_old_tenant(self):

        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [str(uuid.uuid4())],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': False
             }
        ]
        self.assertRaises(wlm_exceptions.ProjectNotFound, self.workloadAPI.workloads_reassign, self.context, tenant_map)

    def test_reassign_with_existing_new_tenant_and_user_id(self):

        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        user_id = self.context.user_id
        old_tenant_id = self.context.project_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': False
             }
        ]
        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_non_existing_new_tenant(self):

        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        user_id = self.context.user_id
        old_tenant_id = self.context.project_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': str(uuid.uuid4()),
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': False
             }
        ]
        self.assertEqual(self.workloadAPI.workloads_reassign(self.context, tenant_map), [])

    def test_reassign_with_non_existing_user_id(self):
        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        old_tenant_id = self.context.project_id

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': 'fake',
             'workload_ids': None,
             'migrate_cloud': False
             }
        ]
        self.assertRaises(wlm_exceptions.UserNotFound, self.workloadAPI.workloads_reassign, self.context, tenant_map)

    def test_reassign_with_single_workload(self):
        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        workload = self.create_workload()

        for i in range(5):
            self.create_snapshot(workload)
        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': [workload['id']],
             'migrate_cloud': False
             }
        ]
        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_multiple_workload(self):
        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        old_tenant_id = self.context.project_id

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': [workload['id'] for workload in workloads],
             'migrate_cloud': False
             }
        ]
        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_existing_project_id_and_migrate_cloud(self):

        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

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

        user_id = self.context.user_id
        old_tenant_id = self.context.project_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': True
             }
        ]
        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_non_existing_project_id_and_migrate_cloud(self):

        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]
        global_new_tenant_id = [str(uuid.uuid4())]

        old_tenant_id = self.context.project_id

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

        user_id = self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': True
             }
        ]
        self.assertEqual(self.workloadAPI.workloads_reassign(self.context, tenant_map), [])

    def test_reassign_with_existing_user_id_and_migrate_cloud(self):

        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

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

        user_id = self.context.user_id
        old_tenant_id = self.context.project_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': True
             }
        ]
        self.workloadAPI.workloads_reassign(self.context, tenant_map)
        workloads_in_db = self.db.workload_get_all(self.context)
        for w in workloads_in_db:
            self.assertEqual(w.project_id, new_tenant_id)
            self.assertEqual(w.user_id, user_id)
        for workload in workloads:
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_target = meta['value']
            workload_path = os.path.join(backup_target, "workload_" + workload['id'])

            for path, subdirs, files in os.walk(workload_path):
                for name in files:
                    if name.endswith("snapshot_db") or name.endswith("workload_db"):
                        db_values = json.loads(open(os.path.join(path, name), 'r').read())
                        self.assertEqual(db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual(db_values.get('user_id', None), user_id)

    def test_reassign_with_non_existing_user_id_and_migrate_cloud(self):
        global global_new_tenant_id
        global_new_tenant_id = [str(uuid.uuid4())]
        new_tenant_id = global_new_tenant_id[0]

        old_tenant_id = self.context.project_id

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

        user_id = 'fake' #self.context.user_id
        tenant_map = [
            {'old_tenant_ids': [old_tenant_id],
             'new_tenant_id': new_tenant_id,
             'user_id': user_id,
             'workload_ids': None,
             'migrate_cloud': True
             }
        ]
        self.assertRaises(wlm_exceptions.UserNotFound, self.workloadAPI.workloads_reassign, self.context, tenant_map)
