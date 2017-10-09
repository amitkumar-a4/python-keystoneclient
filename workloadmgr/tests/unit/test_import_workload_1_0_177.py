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


class BaseVaultTestCase(test.TestCase):
    """Test Case for vmtasks."""

    def setUp(self):
        super(BaseVaultTestCase, self).setUp()

        CONF.set_default('vault_storage_nfs_export',
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
        #self.context.user = 'fake'
        #self.context.tenant = 'fake'
        self.context.project_id = str(uuid.uuid4())
        self.context.tenant_id = self.context.project_id

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()

        import workloadmgr.vault.vault
        for share in ['server1:nfsshare1',
                      'server2:nfsshare2', 'server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)

        super(BaseVaultTestCase, self).tearDown()

    @patch('subprocess.check_call')
    @patch('workloadmgr.db.imports.import_workload_1_0_177.get_context', lambda x: x)
    @patch('workloadmgr.db.imports.import_workload_1_0_177.project_id_exists')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
    def test_import_workloads_all(self, mock_method1,
                                  mock_method4,
                                  mock_method3):

        import workloadmgr.vault.vault
        from workloadmgr.db.imports.import_workload_1_0_177 import import_workload
        from workloadmgr.db.imports.import_workload_1_0_177 import import_settings

        values = [{'server1:nfsshare1': [1099511627776, 0], }.values()[0],
                  {'server2:nfsshare2': [1099511627776, 0], }.values()[0],
                  {'server3:nfsshare3': [1099511627776, 0], }.values()[0], ]

        mock_method1.return_value = True
        mock_method3.return_value = True
        mock_method4.return_value = True

        @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
        def create_workload(size, noofsnapshots, mock_method2):
            """ create a json file on the NFS share """
            mock_method2.return_value = None
            mock_method2.side_effect = values
            workload = {
                'id': str(uuid.uuid4()),
                'size': size,
                'error_msg': '',
                'user_id': self.context.user_id,
                'tenant_id': self.context.tenant_id,
                'status': 'creating',
                'instances': [],
                'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                             'end_date': '07/05/2015',
                                             'enabled': False,
                                             'interval': '1 hr',
                                             'start_time': '2:30 PM',
                                             'fullbackup_interval': '-1',
                                             'retention_policy_type': 'Number of Snapshots to Keep',
                                             'retention_policy_value': str(noofsnapshots)}),
                'metadata': {'workload_approx_backup_size': 1024}
            }

            workload_backup_media_size = size
            jobschedule = pickle.loads(workload['jobschedule'])
            if jobschedule['retention_policy_type'] == 'Number of Snapshots to Keep':
                incrs = int(jobschedule['retention_policy_value'])
            else:
                jobsperday = int(jobschedule['interval'].split("hr")[0])
                incrs = int(jobschedule['retention_policy_value']) * jobsperday

            if int(jobschedule['fullbackup_interval']) == -1:
                fulls = 1
            elif int(jobschedule['fullbackup_interval']) == 0:
                fulls = incrs
                incrs = 0
            else:
                fulls = incrs / int(jobschedule['fullbackup_interval'])
                incrs = incrs - fulls

            workload_approx_backup_size = \
                (fulls * workload_backup_media_size * CONF.workload_full_backup_factor +
                 incrs * workload_backup_media_size * CONF.workload_incr_backup_factor) / 100

            workload_metadata = [{'key': 'workload_approx_backup_size', 'value': workload_approx_backup_size,
                                  'deleted': False, 'created_at': None, 'updated_at': None,
                                  'version': '2.3.1', 'workload_id': workload['id'], 'deleted_at': None}]
            workload['metadata'] = workload_metadata
            backup_endpoint = workloadmgr.vault.vault.get_nfs_share_for_workload_by_free_overcommit(
                self.context, workload)
            workload_metadata = [{'key': 'workload_approx_backup_size', 'value': workload_approx_backup_size,
                                  'deleted': False, 'created_at': None, 'updated_at': None,
                                  'version': '2.3.1', 'workload_id': workload['id'], 'deleted_at': None,
                                  'id': str(uuid.uuid4())},
                                 {'key': 'backup_media_target', 'value': backup_endpoint,
                                  'deleted': False, 'created_at': None, 'updated_at': None,
                                  'version': '2.3.1', 'workload_id': workload['id'], 'deleted_at': None,
                                  'id': str(uuid.uuid4())}]

            workload['metadata'] = workload_metadata

            # write json here
            backup_target = workloadmgr.vault.vault.get_backup_target(
                backup_endpoint)
            workload_path = os.path.join(
                backup_target.mount_path,
                "workload_" + workload['id'])
            os.mkdir(workload_path)
            workload_json_file = os.path.join(workload_path, "workload_db")
            with open(workload_json_file, "w") as f:
                f.write(json.dumps(workload))

            return workload

        def create_setting(cntx):
            (backup_target, path) = vault.get_settings_backup_target()
            settings_db = [{"status": "available",
                            "category": "job_scheduler",
                            "user_id": cntx.user_id,
                            "description": "Controls job scheduler status",
                            "deleted": False,
                            "value": "1",
                            "name": "global-job-scheduler",
                            "version": "2.3.1",
                            "hidden": False,
                            "project_id": cntx.project_id,
                            "type": "job-scheduler-setting",
                            "public": False,
                            "metadata": []}]
            backup_target.put_object(path, json.dumps(settings_db))

        def delete_workload(workload):
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_endpoint = meta['value']
            backup_target = workloadmgr.vault.vault.get_backup_target(
                backup_endpoint)
            workload_path = os.path.join(backup_target.mount_path,
                                         "workload_" + workload['id'])
            shutil.rmtree(workload_path)

        def create_snapshot(workload, full=False):
            """ create a sparse file
                adjust number of snapshots based on retention policy
            """

            snap_id = str(uuid.uuid4())
            snapname = "snapshot_" + snap_id
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_endpoint = meta['value']
            backup_target = workloadmgr.vault.vault.get_backup_target(
                backup_endpoint)
            workload_path = os.path.join(
                backup_target.mount_path,
                "workload_" + workload['id'])
            snap_path = os.path.join(workload_path, snapname)
            fileutils.ensure_tree(snap_path)

            if full:
                snapsize = workload['size']
            else:
                snapsize = workload['size'] / (10 * random.randint(1, 10))

            snapshot_db = {"finished_at": None, "updated_at": None, "deleted_at": None, "id": snap_id,
                           "size": snapsize, "user_id": "fake", "restore_size": 0,
                           "display_description": "this is a test snapshot", "time_taken": 2,
                           "pinned": False, "version": "2.3.1", "project_id": "fake",
                           "metadata": [{"deleted": False, "created_at": None, "updated_at": None, "value": "0",
                                         "version": "2.3.1", "key": "object_store_transfer_time",
                                         "snapshot_id": snap_id, "deleted_at": None,
                                         "id": str(uuid.uuid4())},
                                        {"deleted": False, "created_at": None, "updated_at": None, "value": "0",
                                         "version": "2.3.1", "key": "data_transfer_time", "snapshot_id": snap_id,
                                         "deleted_at": None, "id": str(uuid.uuid4())},
                                        {"deleted": False, "created_at": None, "updated_at": None, "value": "1188",
                                         "version": "2.3.1", "key": "workload_approx_backup_size",
                                         "snapshot_id": snap_id, "deleted_at": None,
                                         "id": str(uuid.uuid4())},
                                        {"deleted": False, "created_at": None, "updated_at": None, "value": "server2:nfsshare2",
                                         "version": "2.3.1", "key": "backup_media_target", "snapshot_id": snap_id,
                                         "deleted_at": None, "id": str(uuid.uuid4())},
                                        {"deleted": False, "created_at": None, "updated_at": None,
                                         "value": "\"", "version": "2.3.1", "key": "topology",
                                         "snapshot_id": snap_id, "deleted_at": None, "id": str(uuid.uuid4())}],
                           "status": "available", "vault_storage_id": None, "deleted": False, "warning_msg": None,
                           "host": "openstack", "progress_msg": "Initializing Snapshot Workflow",
                           "display_name": "test_snapshot", "error_msg": None, "uploaded_size": 0,
                           "created_at": None, "snapshot_type": "full", "progress_percent": 0,
                           "data_deleted": False, "workload_id": workload['id']}

            with open(os.path.join(snap_path, 'snapshot_db'), "w") as f:
                f.write(json.dumps(snapshot_db))

            # apply retention policy
            snaps = []
            for snap in os.listdir(workload_path):
                if snapname in snap:
                    continue
                if not "snapshot_" in snap:
                    continue
                snaps.append(snap)

            if len(snaps) >= pickle.loads(workload['jobschedule'])[
                    'retention_policy_value']:
                os.remove(os.path.join(workload_path, snaps[0]))

            return snap_path

        workloads = []
        for i in range(20):
            workload = create_workload(random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)

        for w in workloads:
            create_snapshot(w, full=True)
            for s in range(5):
                create_snapshot(w)

        create_setting(self.context)

        for wdb in self.db.workload_get_all(self.context):
            self.db.workload_delete(self.context, wdb.id)

        import_settings(self.context, '2.3.1')
        setting = self.db.setting_get(self.context, 'global-job-scheduler')
        self.assertEqual(setting.name, 'global-job-scheduler')
        self.assertEqual(setting.value, '1')
        import_workload(self.context, [], '2.3.1')
        workloads_in_db = self.db.workload_get_all(self.context)
        self.assertEqual(len(workloads_in_db), 20)
        # delete latest workloads
        for w in workloads:
            delete_workload(w)
