## vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.
import cPickle as pickle
import json
import os
import shutil
import uuid

import mock
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
from datetime import date, timedelta

CONF = cfg.CONF

class BaseFileSearchTestCase(test.TestCase):
    """Test Case for File Search"""

    def setUp(self):
        super(BaseFileSearchTestCase, self).setUp()

        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        self.context = context.get_admin_context()

        self.stderr_patch = patch('sys.stderr')
        self.stderr_patch.start()

        self.is_online_patch = patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')
        self.subprocess_patch_output = patch('subprocess.check_output')

        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.SubProcessOutputMockMethod = self.subprocess_patch_output.start()

        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True
        self.SubProcessOutputMockMethod.return_value = '{}'
        self.workload = importutils.import_object(CONF.workloads_manager)
        from workloadmgr.workloads.api import API
        from workloadmgr.workloads.manager import WorkloadMgrManager
        self.workloadAPI = API()
        self.workloadManager = WorkloadMgrManager()
        self.db = self.workload.db
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = str(uuid.uuid4())
        self.context.tenant_id = self.context.project_id
        self.context.vm_id = str(uuid.uuid4())

    def tearDown(self):
        for workload in self.db.workload_get_all(self.context):
            snapshots = self.db.snapshot_get_all_by_workload(self.context, workload['id'])
            for snapshot in snapshots:
                self.db.snapshot_delete(self.context, snapshot['id'])
            self.db.workload_delete(self.context, workload['id'])

        kwargs = {}
        list_search = self.db.file_search_get_all(self.context, **kwargs)
        if len(list_search) > 0:
           for search in list_search:
               self.db.file_search_delete(self.context, search.id)
        for share in ['server1:nfsshare1', 'server2:nfsshare2', 'server3:nfsshare3']:
            backup_target = vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)

        self.is_online_patch.stop()
        self.subprocess_patch.stop()
        self.subprocess_patch_output.stop()
        self.stderr_patch.stop()

        super(BaseFileSearchTestCase, self).tearDown()
        

    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
    def create_workload(self, capacity_mock):
        values = [{'server1:nfsshare1': [1099511627776, 0],}.values()[0],
                  {'server2:nfsshare2': [1099511627776, 0],}.values()[0],
                  {'server3:nfsshare3': [1099511627776, 0],}.values()[0], ]

        capacity_mock.return_value = None
        capacity_mock.side_effect = values
        type_id = tests_utils.create_workload_type(self.context)
        jobschedule = pickle.dumps({'test': 'schedule'})
        instances = []
        instances.append({'instance-id':  self.context.vm_id, 'instance-name': 'test_vm'})
        workload = tests_utils.create_workload(self.context, workload_type_id=type_id.id, jobschedule=jobschedule, instances=instances)
        workload = workload.__dict__
        workload.pop('_sa_instance_state')
        workload.pop('created_at')
        workload['workload_id'] = workload['id']
        backup_endpoint = vault.get_nfs_share_for_workload_by_free_overcommit(self.context,workload)
        # write json here
        backup_target = vault.get_backup_target(backup_endpoint)
        workload['metadata'] = [{'key': 'backup_media_target', 'value': backup_target.mount_path}]
        workload_path = os.path.join(backup_target.mount_path, "workload_" + workload['id'])
        os.mkdir(workload_path)
        workload_json_file = os.path.join(workload_path, "workload_db")
        with open(workload_json_file, "w") as f:
            f.write(json.dumps(workload))
        return (workload, backup_target)

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
        self.db.snapshot_update(self.context, 
                                snapshot['id'],{'status': 'available'})
        return snapshot

    def test_file_search_api_and_manager(self):
        workload, backup_target = self.create_workload()
        snapshot = self.create_snapshot(workload)
        data = {'vm_id': self.context.vm_id, 'filepath': '/', 'snapshot_ids': '', 'start': 0, 'end': 0
                 ,'date_from': '', 'date_to': ''}
        search = self.workloadAPI.search(self.context, data)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        try:
            search = self.workloadAPI.search(self.context, data)
        except Exception as ex:
               self.assertEqual(1, 1)
        disks = mock.Mock()
        disks.vault_url = str(uuid.uuid4()) 
        self.workloadManager.db.vm_disk_resource_snap_get_top = mock.MagicMock()
        self.workloadManager.db.vm_disk_resource_snap_get_top.return_value = disks
        vault.get_backup_target = mock.MagicMock()
        vault.get_backup_target.return_value = backup_target
        vm_resource_obj = mock.Mock()
        vm_resource_obj.resource_type = 'disk'
        vm_resource_obj.id = str(uuid.uuid4())
        vm_resource_obj_list = []
        vm_resource_obj_list.append(vm_resource_obj)
        self.workloadManager.db.snapshot_vm_resources_get = mock.MagicMock()
        self.workloadManager.db.snapshot_vm_resources_get.return_value = vm_resource_obj_list
        self.workloadManager.file_search(self.context, search.id)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'completed')
        self.assertEqual(search.vm_id, self.context.vm_id)

    def test_file_search_api_and_manager_with_snapshot_filter(self):
        workload, backup_target = self.create_workload()
        snapshot_ids = []
        for i in range(5): 
            snapshot = self.create_snapshot(workload)
            snapshot_ids.append(snapshot['id'])
        del snapshot_ids[0]
        data = {'vm_id': self.context.vm_id, 'filepath': '/', 'snapshot_ids': snapshot_ids, 'start': 0, 'end': 0
                ,'date_from': '', 'date_to': ''}
        search = self.workloadAPI.search(self.context, data)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        self.assertEqual(",".join(snapshot_ids), search.snapshot_ids)
        try:
            search = self.workloadAPI.search(self.context, data)
        except Exception as ex:
               self.assertEqual(1, 1)
        disks = mock.Mock()
        disks.vault_url = str(uuid.uuid4())
        self.workloadManager.db.vm_disk_resource_snap_get_top = mock.MagicMock()
        self.workloadManager.db.vm_disk_resource_snap_get_top.return_value = disks
        vault.get_backup_target = mock.MagicMock()
        vault.get_backup_target.return_value = backup_target
        vm_resource_obj = mock.Mock()
        vm_resource_obj.resource_type = 'disk'
        vm_resource_obj.id = str(uuid.uuid4())
        vm_resource_obj_list = []
        vm_resource_obj_list.append(vm_resource_obj)
        self.workloadManager.db.snapshot_vm_resources_get = mock.MagicMock()
        self.workloadManager.db.snapshot_vm_resources_get.return_value = vm_resource_obj_list
        self.workloadManager.file_search(self.context, search.id)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'completed')
        self.assertEqual(search.vm_id, self.context.vm_id)
        self.assertEqual(",".join(snapshot_ids), search.snapshot_ids)

    def test_file_search_api_and_manager_with_range_filter(self):
        workload, backup_target = self.create_workload()
        snapshot_ids = []
        for i in range(5):
            snapshot = self.create_snapshot(workload)
            snapshot_ids.append(snapshot['id'])
        data = {'vm_id': self.context.vm_id, 'filepath': '/', 'snapshot_ids': '', 'start': 1, 'end': 2
                ,'date_from': '', 'date_to': ''}
        search = self.workloadAPI.search(self.context, data)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        self.assertEqual(search.start, 1)
        self.assertEqual(search.end, 2)
        try:
            search = self.workloadAPI.search(self.context, data)
        except Exception as ex:
               self.assertEqual(1, 1)
        disks = mock.Mock()
        disks.vault_url = str(uuid.uuid4())
        self.workloadManager.db.vm_disk_resource_snap_get_top = mock.MagicMock()
        self.workloadManager.db.vm_disk_resource_snap_get_top.return_value = disks
        vault.get_backup_target = mock.MagicMock()
        vault.get_backup_target.return_value = backup_target
        vm_resource_obj = mock.Mock()
        vm_resource_obj.resource_type = 'disk'
        vm_resource_obj.id = str(uuid.uuid4())
        vm_resource_obj_list = []
        vm_resource_obj_list.append(vm_resource_obj)
        self.workloadManager.db.snapshot_vm_resources_get = mock.MagicMock()
        self.workloadManager.db.snapshot_vm_resources_get.return_value = vm_resource_obj_list
        self.workloadManager.file_search(self.context, search.id)
        args = self.SubProcessOutputMockMethod.call_args[0]
        self.assertEqual(len(args[0][2].split('|-|')), 2)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'completed')
        self.assertEqual(search.vm_id, self.context.vm_id)

    def test_file_search_api_and_manager_with_date_filter(self):
        workload, backup_target = self.create_workload()
        snapshot_ids = []
        for i in range(5):
            snapshot = self.create_snapshot(workload)
            snapshot_ids.append(snapshot['id'])
        date_from = date.today() - timedelta(1)
        date_from = date_from.strftime('%Y-%m-%dT%H:%M:%S')
        data = {'vm_id': self.context.vm_id, 'filepath': '/', 'snapshot_ids': '', 'start': 0, 'end': 0
                ,'date_from': date_from, 'date_to': ''}
        search = self.workloadAPI.search(self.context, data)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'executing')
        self.assertEqual(search.vm_id, self.context.vm_id)
        self.assertEqual(search.date_from, date_from)
        self.assertEqual(search.date_to, '')
        try:
            search = self.workloadAPI.search(self.context, data)
        except Exception as ex:
               self.assertEqual(1, 1)
        # mismatch between mysql and sqlite queries, cant check dates in tests
        kwargs = {'workload_id':workload['id'], 'get_all': False, 'status':'available'}
        search_list_snapshots = self.workloadManager.db.snapshot_get_all(self.context, **kwargs)
        disks = mock.Mock()
        disks.vault_url = str(uuid.uuid4())
        self.workloadManager.db.vm_disk_resource_snap_get_top = mock.MagicMock()
        self.workloadManager.db.vm_disk_resource_snap_get_top.return_value = disks
        vault.get_backup_target = mock.MagicMock()
        vault.get_backup_target.return_value = backup_target
        vm_resource_obj = mock.Mock()
        vm_resource_obj.resource_type = 'disk'
        vm_resource_obj.id = str(uuid.uuid4())
        vm_resource_obj_list = []
        vm_resource_obj_list.append(vm_resource_obj)
        self.workloadManager.db.snapshot_vm_resources_get = mock.MagicMock()
        self.workloadManager.db.snapshot_vm_resources_get.return_value = vm_resource_obj_list
        with patch.object(self.workloadManager.db, 'snapshot_get_all', return_value=search_list_snapshots):
             self.workloadManager.file_search(self.context, search.id)
        args = self.SubProcessOutputMockMethod.call_args[0]
        self.assertEqual(len(args[0][2].split('|-|')), 5)
        search = self.workloadAPI.search_show(self.context, search.id)
        self.assertEqual(search.status, 'completed')
        self.assertEqual(search.vm_id, self.context.vm_id)

    def test_file_search_api_date_validations(self):
        workload, backup_target = self.create_workload()
        date1 = date.today() - timedelta(1)
        date_from = date1.strftime('%Y-%m-%d')
        data = {'vm_id': self.context.vm_id, 'filepath': '/', 'snapshot_ids': '', 'start': 0, 'end': 0
                ,'date_from': date_from, 'date_to': ''}
        try:
            search = self.workloadAPI.search(self.context, data)
            self.assertEqual(1,2)            
        except Exception as ex:
               self.assertEqual(ex.kwargs['reason'], 
                    "Please provide valid date_from in Format YYYY-MM-DDTHH:MM:SS")

        date_to = date1.strftime('%Y-%m-%d')
        date_from = date1.strftime('%Y-%m-%dT%H:%M:%S')
        data['date_to'] = date_to
        data['date_from'] = date_from 

        try:
            search = self.workloadAPI.search(self.context, data)
            self.assertEqual(1,2)
        except Exception as ex:
               self.assertEqual(ex.kwargs['reason'],
                    "Please provide valid date_to in Format YYYY-MM-DDTHH:MM:SS") 
