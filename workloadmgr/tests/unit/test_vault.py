# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.
import __builtin__
import contextlib
import datetime
import os
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

from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
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
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()
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

                 values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                           {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                           {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                 mock_method1.side_effect = values
                 workloadmgr.vault.vault.get_capacities_utilizations(self.context)

    def test_get_settings_backup_target(self):
        import workloadmgr.vault.vault
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_online', return_value=True) as mock_method1, \
             patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'get_total_capacity', return_value=None) as mock_method2,\
             patch.object(subprocess, 'check_call', return_value=True) as mock_method3:

                 values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                           {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                           {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                 mock_method1.side_effect = values

                 settings_backup = workloadmgr.vault.vault.get_settings_backup_target()
                 self.assertEqual(settings_backup.backup_endpoint, 'server3:nfsshare3')

    @patch('subprocess.check_call')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
    def test_get_nfs_share_for_workload_by_free_overcommit(context, mock_method1,
                                                           mock_method2, mock_method3):

        values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                   {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                   {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

        mock_method2.side_effect = values
        mock_method1.return_value = True
        mock_method3.return_value = True

        def create_workload(size, noofsnapshots):
            """ create a json file on the NFS share """
            workload = {
                        'id': str(uuid.uuid4()),
                        'size': size,
                        'status': 'creating',
                        'instances': [],
                        'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': -1,
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': str(noofsnapshots)}),
                        'metadata': {'workload_approx_backup_size': 1024}
                       }

            workload_backup_media_size = size
            jobschedule = workload['jobschedule']
            if jobschedule['retention_policy_type'] == 'Number of Snapshots to Keep':
                incrs = int(jobschedule['retention_policy_value'])
            else:
                jobsperday = int(jobschedule['interval'].split("hr")[0])
                incrs = int(jobschedule['retention_policy_value']) * jobsperday

            if int(jobschedule['fullbackup_interval']) == -1:
                fulls = 1
            if int(jobschedule['fullbackup_interval']) == 0:
                fulls = incrs
                incrs = 0
            else:
                fulls = incrs/int(jobschedule['fullbackup_interval'])
                incrs = incrs - fulls

            workload_approx_backup_size = \
                (fulls * workload_backup_media_size * CONF.workload_full_backup_factor +
                 incrs * workload_backup_media_size * CONF.workload_incr_backup_factor) / 100

            backup_endpoint = workloadmgr.vault.vault.get_nfs_share_for_workload_by_free_overcommit(self.context, workload)
            workload_metadata = {'workload_approx_backup_size': workload_approx_backup_size,
                                 'backup_media_target': backup_endpoint}
            workload['metadata'] = workload_metadata

            # write json here
            workload_path = os.path.join(backup_endpoint.mount_path, "workload_" + workload['id'])
            os.mkdir(workload_path)
            workload_json_file = os.path.join(workload_path, "workload_db")
            with open(workload_json_file, "w") as f:
                 f.write(json.dumps(workload))

            return workload

        def delete_workload(workload):
            workload_path = os.path.join(workload['nfsshare'],
                                         'workload_' + workload['id'])
            shutil.rmtree(workload_path) 

        def create_snapshot(workload, full=False):
            """ create a sparse file
                adjust number of snapshots based on retention policy
            """
            snapname = "snapshot_" + str(uuid.uuid4())
            backup_target = workloadmgr.vault.vault.get_backup_target(workworkload['metadata']['backup_media_target'])
            workload_path = os.path.join(backup_target.mount_path, "workload_" + workload['id'])
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

            if len(snaps) >= workload['noofsnapshots']:
                os.remove(os.path.join(workload_path, snaps[0]))

            return snap_path

        import pdb;pdb.set_trace()
        workloads = []
        for i in range(200):
            workload = create_workload(1024 * 1024 * 1024 * random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)

        totalworkloads += workloads
        for w in workloads:
            create_snapshot(w, full=True)

        workloads = []
        for i in range(200):
            workload = create_workload(1024 * 1024 * 1024 * random.randint(1, 100),
                                       random.randint(10, 50))
            workloads.append(workload)

        for w in workloads:
            create_snapshot(w, shares, full=True)

        workloads = []
        print_usage("After creating 200 workloads and full snapshots", shares)
        for i in range(200):
            workload = create_workload(shares,
                                       1024 * 1024 * 1024 * random.randint(1, 100),
                                       random.randint(10, 50),
                                       placementalgo)
            workloads.append(workload)

        totalworkloads += workloads


        for w in workloads:
            create_snapshot(w, shares, full=True)

        print_usage("After creating addtional 100 workloads and full snapshots", shares)

        for i in range(100):
            for w in totalworkloads:
                create_snapshot(w, shares)

        print_usage("After create 100 incrementals on each workload", shares)

        workloads = []
        for i in range(500):
            workload = create_workload(shares,
                                       1024 * 1024 * 1024 * random.randint(1, 100),
                                       random.randint(10, 50),
                                       placementalgo)
            workloads.append(workload)
        for w in workloads:
            create_snapshot(w, shares, full=True)

        print_usage("Creating additional 500 workloads and a full snapshot", shares)

        # delete latest workloads
        for w in workloads:
            delete_workload(w)

        print_usage("After deleting latest 500 workloads and a full snapshot", shares)

        workloads = []
        for i in range(500):
            workload = create_workload(shares,
                                       1024 * 1024 * 1024 * random.randint(1, 100),
                                       random.randint(10, 50),
                                       placementalgo)
            workloads.append(workload)
        totalworkloads += workloads
        for w in workloads:
            create_snapshot(w, shares, full=True)

        print_usage("After recreating additional 500 workloads and a full snapshot", shares)

        # add few more NFS shares
        shares += create_multiple_shares()
        print_usage("After adding few more shares", shares)

        workloads = []
        for i in range(1000):
            workload = create_workload(shares,
                                       1024 * 1024 * 1024 * random.randint(1, 100),
                                       random.randint(10, 50),
                                       placementalgo)
            workloads.append(workload)

        for w in workloads:
            create_snapshot(w, shares, full=True)
        totalworkloads += workloads

        print_usage("After adding workloads and a full snapshot", shares)

        for i in range(100):
            for w in totalworkloads:
                create_snapshot(w, shares)

        print_usage("After create 100 incrementals on each workload", shares)
        #print_workloads(totalworkloads, shares, workloads_by_share=True)

        for s in shares:
            shutil.rmtree(s['share'])
