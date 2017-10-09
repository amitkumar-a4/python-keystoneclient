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
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

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

    def test_mount_backup_media(self):
        """Test mount backup medua"""
        pass

    def test_get_capacities_utilizations(self):
        import workloadmgr.vault.vault
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_online', return_value=True) as mock_method1, \
                patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                             'get_total_capacity', return_value=None) as mock_method2,\
                patch.object(subprocess, 'check_call', return_value=True) as mock_method3:

            values = [{'server1:nfsshare1': [1099511627776, 10737418240], }.values()[0],
                      {'server2:nfsshare2': [
                          1099511627776, 5 * 10737418240], }.values()[0],
                      {'server3:nfsshare3': [1099511627776, 7 * 10737418240], }.values()[0], ]

            mock_method2.side_effect = values
            workloadmgr.vault.vault.get_capacities_utilizations(self.context)

    def test_get_settings_backup_target(self):
        import workloadmgr.vault.vault
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_online', return_value=True) as mock_method1, \
                patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                             'get_total_capacity', return_value=None) as mock_method2,\
                patch.object(subprocess, 'check_call', return_value=True) as mock_method3:

            values = [{'server1:nfsshare1': [1099511627776, 10737418240], }.values()[0],
                      {'server2:nfsshare2': [
                          1099511627776, 5 * 10737418240], }.values()[0],
                      {'server3:nfsshare3': [1099511627776, 7 * 10737418240], }.values()[0], ]

            mock_method2.side_effect = values

            backup_target = workloadmgr.vault.vault.get_backup_target(
                'server3:nfsshare3')
            fileutils.ensure_tree(
                os.path.join(
                    backup_target.mount_path,
                    CONF.cloud_unique_id))
            with open(os.path.join(backup_target.mount_path,
                                   CONF.cloud_unique_id, "settings_db"), "w") as f:
                f.write(json.dumps([]))
            (settings_backup, path) = workloadmgr.vault.vault.get_settings_backup_target()
            self.assertEqual(
                settings_backup.backup_endpoint,
                'server3:nfsshare3')

    @patch('subprocess.check_call')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
    def test_get_nfs_share_for_workload_by_free_overcommit(self, mock_method1,
                                                           mock_method3):

        import workloadmgr.vault.vault

        values = [{'server1:nfsshare1': [1099511627776, 0], }.values()[0],
                  {'server2:nfsshare2': [1099511627776, 0], }.values()[0],
                  {'server3:nfsshare3': [1099511627776, 0], }.values()[0], ]

        mock_method1.return_value = True
        mock_method3.return_value = True

        @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
        def create_workload(size, noofsnapshots, mock_method2):
            """ create a json file on the NFS share """
            mock_method2.return_value = None
            mock_method2.side_effect = values
            workload = {
                'id': str(uuid.uuid4()),
                'size': size,
                'error_msg': '',
                'status': 'creating',
                'instances': [],
                'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                             'end_date': '07/05/2015',
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

            workload_metadata = [
                {'key': 'workload_approx_backup_size', 'value': workload_approx_backup_size}]
            workload['metadata'] = workload_metadata
            backup_endpoint = workloadmgr.vault.vault.get_nfs_share_for_workload_by_free_overcommit(
                self.context, workload)
            workload_metadata = [{'key': 'workload_approx_backup_size', 'value': workload_approx_backup_size},
                                 {'key': 'backup_media_target', 'value': backup_endpoint}]
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

            snapname = "snapshot_" + str(uuid.uuid4())
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_endpoint = meta['value']
            backup_target = workloadmgr.vault.vault.get_backup_target(
                backup_endpoint)
            workload_path = os.path.join(
                backup_target.mount_path,
                "workload_" + workload['id'])
            snap_path = os.path.join(workload_path, snapname)

            if full:
                snapsize = workload['size']
            else:
                snapsize = workload['size'] / (10 * random.randint(1, 10))
            with open(snap_path, "w") as f:
                f.truncate(snapsize)

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
        totalworkloads = []
        for i in range(2):
            workload = create_workload(random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)

        totalworkloads += workloads
        for w in workloads:
            create_snapshot(w, full=True)

        workloads = []
        for i in range(2):
            workload = create_workload(random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)

        for w in workloads:
            create_snapshot(w, full=True)

        workloads = []
        for i in range(2):
            workload = create_workload(random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)

        totalworkloads += workloads

        for w in workloads:
            create_snapshot(w, full=True)

        for i in range(1):
            for w in totalworkloads:
                create_snapshot(w)

        workloads = []
        for i in range(5):
            workload = create_workload(random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)
        for w in workloads:
            create_snapshot(w, full=True)

        # delete latest workloads
        for w in workloads:
            delete_workload(w)

        workloads = []
        for i in range(5):
            workload = create_workload(random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)
        totalworkloads += workloads
        for w in workloads:
            create_snapshot(w, full=True)

        for w in workloads:
            delete_workload(w)

        for share in ['server1:nfsshare1',
                      'server2:nfsshare2', 'server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)

    @patch('subprocess.check_call')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
    def test_get_nfs_share_for_workload_by_free_overcommit_distro(self, mock_method1,
                                                                  mock_method3):

        import workloadmgr.vault.vault

        values = [{'server1:nfsshare1': [1099511627776, 0], }.values()[0],
                  {'server2:nfsshare2': [1099511627776, 0], }.values()[0],
                  {'server3:nfsshare3': [1099511627776, 0], }.values()[0], ]

        mock_method1.return_value = True
        mock_method3.return_value = True

        @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
        def create_workload(size, noofsnapshots, mock_method2):
            """ create a json file on the NFS share """
            mock_method2.return_value = None
            mock_method2.side_effect = values
            workload = {
                'id': str(uuid.uuid4()),
                'size': size,
                'status': 'creating',
                'instances': [],
                'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                             'end_date': '07/05/2015',
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

            workload_metadata = [
                {'key': 'workload_approx_backup_size', 'value': workload_approx_backup_size}]
            workload['metadata'] = workload_metadata
            backup_endpoint = workloadmgr.vault.vault.get_nfs_share_for_workload_by_free_overcommit(
                self.context, workload)
            workload_metadata = [{'key': 'workload_approx_backup_size', 'value': workload_approx_backup_size},
                                 {'key': 'backup_media_target', 'value': backup_endpoint}]
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

        def delete_workload(workload):
            for meta in workload['metadata']:
                if meta['key'] == 'backup_media_target':
                    backup_endpoint = meta['value']
            backup_target = workloadmgr.vault.vault.get_backup_target(
                backup_endpoint)
            workload_path = os.path.join(backup_target.mount_path,
                                         "workload_" + workload['id'])
            shutil.rmtree(workload_path)

        workloads = []
        totalworkloads = []
        for i in range(3):
            workload = create_workload(random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)

        totalworkloads += workloads
        tgts = []
        for w in workloads:
            for meta in w['metadata']:
                if meta['key'] == 'backup_media_target':
                    tgts.append(meta['value'])
                    break

        self.assertEqual(set(tgts), set(['server1:nfsshare1',
                                         'server2:nfsshare2',
                                         'server3:nfsshare3']))

        delete_workload(workloads.pop())

        workload = create_workload(random.randint(1, 100),
                                   random.randint(10, 50))
        workloads.append(workload)

        tgts = []
        for w in workloads:
            for meta in w['metadata']:
                if meta['key'] == 'backup_media_target':
                    tgts.append(meta['value'])

        self.assertEqual(set(tgts), set(['server1:nfsshare1',
                                         'server2:nfsshare2',
                                         'server3:nfsshare3']))

        for share in ['server1:nfsshare1',
                      'server2:nfsshare2', 'server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)
