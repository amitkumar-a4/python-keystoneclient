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

class BaseWorkloadUtilTestCase(test.TestCase):
    """Test Case for workload_utils."""
    def setUp(self):
        super(BaseWorkloadUtilTestCase, self).setUp()

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
        self.context.is_admin = False

        self.nfsshares = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                          {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                          {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()

        import workloadmgr.vault.vault
        for share in ['server1:nfsshare1','server2:nfsshare2','server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)

        super(BaseWorkloadUtilTestCase, self).tearDown()

    @patch('subprocess.check_call')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.get_total_capacity')
    @patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
    def test_upload_settings_db_entry(self, mock_method1, mock_method2,
                                      mock_method3):

        import workloadmgr.vault.vault
        from workloadmgr.workloads import workload_utils

        mock_method2.side_effect = self.nfsshares
        backup_target = workloadmgr.vault.vault.get_backup_target('server3:nfsshare3')
        fileutils.ensure_tree(os.path.join(backup_target.mount_path, CONF.cloud_unique_id))
        with open(os.path.join(backup_target.mount_path,
                               CONF.cloud_unique_id, "settings_db"), "w") as f:
             f.write(json.dumps([]))

        for s in self.db.setting_get_all(self.context, read_deleted='no'):
            try:
                self.db.setting_delete(self.context, s.name)
            except:
                pass

        for s in range(10):
            setting = {u'category': "fake",
                       u'name': "fake-%d" % s,
                       u'description': "Controls fake scheduler status",
                       u'value': True,
                       u'user_id': self.context.user_id,
                       u'project_id': self.context.project_id,
                       u'tenant_id': self.context.tenant_id,
                       u'is_public': False,
                       u'is_hidden': True,
                       u'metadata': {},
                       u'type': "fake-scheduler-setting",}

            sdb = self.db.setting_create(self.context, setting)

        workload_utils.upload_settings_db_entry(self.context)

        settings_db = self.db.setting_get_all(self.context, read_deleted='no')
        self.assertEqual(len(settings_db), 10)

        settings_path = os.path.join(backup_target.mount_path,
                                     CONF.cloud_unique_id, "settings_db")
        settings_json = backup_target.get_object(settings_path)
        settings = json.loads(settings_json)
        self.assertEqual(len(settings), 10)

        for s in self.db.setting_get_all(None, read_deleted = 'no'):
            try:
                self.db.setting_delete(self.context, s.name)
            except:
                pass

    def test_upload_workload_db_entry(self):
        pass

    def test_upload_snapshot_db_entry(self):
        pass

    def test_snapshot_delete(self):
        pass

    def test_delete_if_chain(self):
        pass

    def test_common_apply_retention_policy(self):
        pass
