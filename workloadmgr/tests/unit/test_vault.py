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
