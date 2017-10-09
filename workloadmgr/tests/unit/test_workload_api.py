# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
# All Rights Reserved.

import contextlib
from bunch import bunchify
import cPickle as pickle
import datetime
import os
import shutil
import socket
import tempfile

import eventlet
import mock
from mock import patch
import mox
from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception as wlm_exceptions
from workloadmgr import test
from workloadmgr.tests.unit import utils as tests_utils
from workloadmgr.openstack.common import importutils

CONF = cfg.CONF


class BaseWorkloadTestCase(test.TestCase):
    """Test Case for workloads."""

    def setUp(self):
        super(BaseWorkloadTestCase, self).setUp()
        self.context = context.get_admin_context()

        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        patch('sys.stderr').start()
        self.is_online_patch = patch(
            'workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')
        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True

        patch('workloadmgr.workloads.api.create_trust', lambda x: x).start()

        self.workload = importutils.import_object(CONF.workloads_manager)
        from workloadmgr.workloads.api import *
        self.workloadAPI = API()
        self.db = self.workload.db
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.context.tenant_id = 'fake'
        self.context.is_admin = False
        self.workload_params = {
            'status': 'creating',
            'instances': [],
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                                         'end_date': '07/05/2015',
                                         'interval': '1 hr',
                                         'start_time': '2:30 PM',
                                         'fullbackup_interval': -1,
                                         'retention_policy_type': 'Number of Snapshots to Keep',
                                         'retention_policy_value': '30'}),
            'host': CONF.host, }

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()
        super(BaseWorkloadTestCase, self).tearDown()

    def test_get_storage_usage_admin_required(self):
        self.assertRaises(wlm_exceptions.AdminRequired,
                          self.workloadAPI.get_storage_usage,
                          self.context)

    def test_get_storage_usage(self):
        self.context.is_admin = True
        storage_usage = self.workloadAPI.get_storage_usage(self.context)

        self.assertEqual(len(storage_usage['storage_usage']), 3)
        self.assertTrue('count_dict' in storage_usage)
        shares = set(
            ['server1:nfsshare1', 'server2:nfsshare2', 'server3:nfsshare3'])
        sharesinusage = []
        storage_usage['storage_usage'][0]['nfs_share(s)'][0]['nfsshare']
        for details in storage_usage['storage_usage']:
            sharesinusage.append(details['nfs_share(s)'][0]['nfsshare'])

        self.assertEqual(set(sharesinusage), shares)
