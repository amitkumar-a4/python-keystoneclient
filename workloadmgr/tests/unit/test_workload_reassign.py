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
import pdb
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
from bunch import bunchify

from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import test
from workloadmgr.openstack.common import fileutils
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common.rpc import amqp
from workloadmgr.tests.unit import utils as tests_utils
from workloadmgr import exception as wlm_exceptions
import workloadmgr

from workloadmgr.vault import vault

CONF = cfg.CONF

class BaseReassignAPITestCase(test.TestCase):
    """Test Case for Reassign API ."""
    def setUp(self):
        super(BaseReassignAPITestCase, self).setUp()

        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        self.context = context.get_admin_context()
        patch('sys.stderr').start()

        self.is_online_patch = patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
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

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()

        import workloadmgr.vault.vault
        for share in ['server1:nfsshare1', 'server2:nfsshare2', 'server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)

        super(BaseReassignAPITestCase, self).tearDown()

    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
    def create_workload(self, capacity_mock):
        values = [{'server1:nfsshare1': [1099511627776, 0],}.values()[0],
                  {'server2:nfsshare2': [1099511627776, 0],}.values()[0],
                  {'server3:nfsshare3': [1099511627776, 0],}.values()[0], ]

        capacity_mock.return_value = None
        capacity_mock.side_effect = values
        type_id = tests_utils.create_workload_type(self.context)
        jobschedule = pickle.dumps({'test': 'schedule'})
        workload = tests_utils.create_workload(self.context, workload_type_id=type_id.id, jobschedule=jobschedule)
        workload = workload.__dict__
        workload.pop('_sa_instance_state')
        workload.pop('created_at')
        workload['workload_id'] = workload['id']
        backup_endpoint = workloadmgr.vault.vault.get_nfs_share_for_workload_by_free_overcommit(self.context,
                                                                                                workload)
        # write json here
        backup_target = workloadmgr.vault.vault.get_backup_target(backup_endpoint)
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

    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_single_old_tenant(self, check_user_mock, user_exist_mock, get_project_mock):

        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id':new_tenant_id}), bunchify({'id':old_tenant_id})]
        get_project_mock.return_value = tenant_list

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)
        workloads = []
        for i in range(5):
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            for i in range(5):
                self.create_snapshot(workload)

        old_tenant_id = self.context.project_id
        user_id = self.context.user_id
        tenant_map = [
                     {'old_tenant_ids': [old_tenant_id],
                      'new_tenant_id' : new_tenant_id ,
                      'user_id': user_id,
                      'workload_ids' : None,
                      'migrate_cloud' : False
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
                        self.assertEqual( db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual( db_values.get('user_id', None), user_id)
    
    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_multiple_old_tenant(self, check_user_mock, user_exist_mock, get_project_mock):

        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        project_ids = [str(uuid.uuid4()) for x in range(5)]
        tenant_list = [bunchify({'id':new_tenant_id})]
        for id in project_ids:
            tenant_list.append(bunchify({'id':id}))
        get_project_mock.return_value = tenant_list

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)
        
        workloads = []
        for project_id in project_ids:
            self.context.project_id = project_id
            workload = self.create_workload()
            workloads.append(workload)

        for w in workloads:
            self.context.project_id = w['project_id']
            for i in range(5):
                self.create_snapshot(workload)

        #old_tenant_id = self.context.project_id
        user_id = self.context.user_id
        tenant_map = [
                     {'old_tenant_ids': project_ids,
                      'new_tenant_id' : new_tenant_id ,
                      'user_id': user_id,
                      'workload_ids' : None,
                      'migrate_cloud' : False
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
                        self.assertEqual( db_values.get('project_id', None), new_tenant_id)
                        self.assertEqual( db_values.get('user_id', None), user_id)
     
    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_non_existing_old_tenant(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        tenant_list = [bunchify({'id': new_tenant_id})]
        get_project_mock.return_value = tenant_list

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
   
    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_existing_new_tenant_and_user_id(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': new_tenant_id}), bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list

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

    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_non_existing_new_tenant(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list

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
        self.assertRaises(wlm_exceptions.ProjectNotFound, self.workloadAPI.workloads_reassign, self.context, tenant_map)

    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_non_existing_user_id(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = False

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': new_tenant_id}), bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list

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
        self.assertRaises(wlm_exceptions.UserNotFound, self.workloadAPI.workloads_reassign, self.context, tenant_map)
        
    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_single_workload(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': new_tenant_id}), bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list

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
    
    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_multiple_workload(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True
    
        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': new_tenant_id}), bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list
    
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

    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_existing_project_id_and_migrate_cloud(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True
    
        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': new_tenant_id}), bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list
    
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

    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_non_existing_project_id_and_migrate_cloud(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [ bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list

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
        self.assertRaises(wlm_exceptions.ProjectNotFound, self.workloadAPI.workloads_reassign, self.context, tenant_map) 

    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_existing_user_id_and_migrate_cloud(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = True

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': new_tenant_id}), bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list

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

    @patch('workloadmgr.vault.vault.get_project_list_for_import')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.user_exist_in_tenant')
    @patch('workloadmgr.common.workloadmgr_keystoneclient.check_user_role')
    def test_reassign_with_non_existing_user_id_and_migrate_cloud(self, check_user_mock, user_exist_mock, get_project_mock):
        check_user_mock.return_value = True
        user_exist_mock.return_value = False

        new_tenant_id = str(uuid.uuid4())
        old_tenant_id = self.context.project_id
        tenant_list = [bunchify({'id': new_tenant_id}), bunchify({'id': old_tenant_id})]
        get_project_mock.return_value = tenant_list

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
        self.assertRaises(wlm_exceptions.UserNotFound, self.workloadAPI.workloads_reassign, self.context, tenant_map)
    
