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
import uuid

import eventlet
import mock
from mock import patch
import mox
from oslo.config import cfg

from workloadmgr import context
from workloadmgr import db
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.tests.unit import utils as tests_utils
from workloadmgr.openstack.common import importutils
from workloadmgr.openstack.common import fileutils
#from workloadmgr.workloads.api import API

CONF = cfg.CONF

class BaseWorkloadAPITestCase(test.TestCase):
    """Test Case for workloads."""
    def setUp(self):
        super(BaseWorkloadAPITestCase, self).setUp()
        self.context = context.get_admin_context()

        self.is_online_patch = patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')

        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True

        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        patch('workloadmgr.workloads.api.create_trust', lambda x: x).start()
        patch('sys.stderr').start()
        patch('workloadmgr.autolog.log_method').start()

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
            'error_msg': '',
            'instances': [],
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': -1,
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()

        import workloadmgr.vault.vault

        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        for snapshot in self.workloadAPI.snapshot_get_all(self.context):
            self.db.snapshot_update(self.context, snapshot.id, 
                                    { 'status': 'available' })
            self.db.snapshot_delete(self.context, snapshot.id)
        for workload in self.workloadAPI.workload_get_all(self.context):
            self.db.workload_update(self.context, workload.id, 
                                    { 'status': 'available' })
            for vm in self.db.workload_vms_get(self.context, workload.id):
                self.db.workload_vms_delete(self.context, vm.vm_id, workload.id)
            self.db.workload_delete(self.context, workload.id)

        for share in ['server1:nfsshare1','server2:nfsshare2','server3:nfsshare3']:
            backup_target = workloadmgr.vault.vault.get_backup_target(share)
            shutil.rmtree(backup_target.mount_path)
            fileutils.ensure_tree(backup_target.mount_path)
        super(BaseWorkloadAPITestCase, self).tearDown()

    def test_API_init(self):
        self.assertTrue(hasattr(self.workloadAPI, "workloads_rpcapi"))
        self.assertTrue(hasattr(self.workloadAPI, "scheduler_rpcapi"))
        self.assertTrue(hasattr(self.workloadAPI, "_engine"))
        self.assertTrue(hasattr(self.workloadAPI, "_jobstore"))
        self.assertTrue(hasattr(self.workloadAPI, "_scheduler"))

    def test_workload_type_crud(self):
        for x in range(10):

            name = "workload_type_%d" % x
            description = "workload_type_%d for dummies" % x
            is_public = True
            metadata = {'key1': 'value1',
                        'key2': 'value2',
                        'key3': 'value3',
                        'key4': 'value4',
                        'key5': 'value5',}

            self.workloadAPI.workload_type_create(
                self.context, str(uuid.uuid4()), name,
                description, is_public, metadata)

        wtypes = self.workloadAPI.workload_type_get_all(self.context)
        self.assertGreaterEqual(len(wtypes), 10)
        for wt in wtypes:
            self.workloadAPI.workload_type_get(self.context, wt.id)
            self.workloadAPI.workload_type_show(self.context, wt.id)

            self.workloadAPI.workload_type_delete(self.context, wt.id)

        wtypes = self.workloadAPI.workload_type_get_all(self.context)
        self.assertGreaterEqual(len(wtypes), 0)

    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_create_no_instances(self, log_mock, mock_get_servers):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = []
        jobschedule =  {'start_date': '06/05/2014',
                        'end_date': '07/05/2015',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.assertRaises(exception.InvalidRequest,
                          self.workloadAPI.workload_create,
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_create_invalid_instances(self, log_mock, mock_get_servers):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': str(uuid.uuid4())}]
        jobschedule =  {'start_date': '06/05/2014',
                        'end_date': '07/05/2015',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.assertRaises(exception.InstanceNotFound,
                          self.workloadAPI.workload_create,
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_create_invalid_workload_type(self, log_mock, mock_get_servers,
                                                   trust_create_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'start_date': '06/05/2014',
                        'end_date': '07/05/2015',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'
        self.assertRaises(exception.Invalid,
                          self.workloadAPI.workload_create,
                          self.context, name, description,
                          str(uuid.uuid4()), source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_create_with_two_instances(self, log_mock, mock_get_servers,
                                                trust_create_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'start_date': '06/05/2014',
                        'end_date': '07/05/2015',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)


    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_create_with_two_instances_with_job_scheduler(self, log_mock, mock_get_servers,
                                                                   trust_create_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)
        self.assertTrue('nextrun' in workload['jobschedule'])

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        self.db.workload_delete(self.context, wl.workload_id)

    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_modify_invalid_instances(self, log_mock, mock_get_servers,
                                               trust_create_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)

        # negative tests
        # instances is not a dict
        self.assertRaises(exception.Invalid,
                          self.workloadAPI.workload_modify,
                          self.context, workload['id'], workload)

    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_modify_invalid_instance_id(self, log_mock, mock_get_servers,
                                                 trust_create_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)

        insts = []
        for ins in workload['instances']:
            ins['instance-id'] = ins.pop('id')
            insts.append(ins)
 
        insts.append({'instance-id': str(uuid.uuid4())})
        workload['instances'] = insts
     
        # negative tests
        # instances is not a dict
        self.assertRaises(exception.Invalid,
                          self.workloadAPI.workload_modify,
                          self.context, workload['id'], workload)

    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_modify_instance_id_of_existing_workload(self, log_mock, mock_get_servers,
                                                              trust_create_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)

        instances = [{'instance-id': 'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991'}]
        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        wl2 = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, wl2.id)), 1)
        self.assertEqual(self.db.workload_get(self.context, wl2.id).id, wl2.id)
        wl2 = self.workloadAPI.workload_show(self.context, wl2.id)

        insts = []
        for ins in workload['instances']:
            ins['instance-id'] = ins.pop('id')
            insts.append(ins)
 
        insts.append({'instance-id': 'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991'})
        workload['instances'] = insts
     
        # negative tests
        # instances is not a dict
        self.assertRaises(exception.Invalid,
                          self.workloadAPI.workload_modify,
                          self.context, workload['id'], workload)

    @patch('workloadmgr.workloads.workload_utils.upload_workload_db_entry')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_modify_add_new_instance(self, log_mock, mock_get_servers,
                                              trust_create_mock, set_meta_item_mock,
                                              delete_meta_mock, upload_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',
                    'backup_media_target': 'server2:nfsshare2'}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)

        insts = []
        for ins in workload['instances']:
            ins['instance-id'] = ins.pop('id')
            insts.append(ins)
 
        insts.append({'instance-id': 'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991'})
        workload['instances'] = insts

        for wl in self.db.workload_vm_get_by_id(self.context, 'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991'):
            self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        # negative tests
        # instances is not a dict
        self.workloadAPI.workload_modify(self.context, workload['id'], workload)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload['id'])), 3)
        self.assertEqual(self.db.workload_get(self.context, workload['id']).id, workload['id'])
        wl2 = self.workloadAPI.workload_show(self.context, workload['id'])

    @patch('workloadmgr.workloads.workload_utils.upload_workload_db_entry')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_modify_remove_instance(self, log_mock, mock_get_servers,
                                              trust_create_mock, set_meta_item_mock,
                                              delete_meta_mock, upload_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',
                    'backup_media_target': 'server2:nfsshare2'}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)

        insts = []
        for ins in workload['instances'][1:]:
            ins['instance-id'] = ins.pop('id')
            insts.append(ins)
 
        workload['instances'] = insts

        # negative tests
        # instances is not a dict
        self.workloadAPI.workload_modify(self.context, workload['id'], workload)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload['id'])), 1)
        self.assertEqual(self.db.workload_get(self.context, workload['id']).id, workload['id'])
        wl2 = self.workloadAPI.workload_show(self.context, workload['id'])

    @patch('workloadmgr.workloads.workload_utils.upload_workload_db_entry')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_modify_change_name_desc(self, log_mock, mock_get_servers,
                                              trust_create_mock, set_meta_item_mock,
                                              delete_meta_mock, upload_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',
                    'backup_media_target': 'server2:nfsshare2'}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)

        workload['name'] = 'changed name'
        workload['description'] = 'changed description'
        workload.pop('instances')
        self.workloadAPI.workload_modify(self.context, workload['id'], workload)

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload['id'])), 2)
        self.assertEqual(self.db.workload_get(self.context, workload['id']).id, workload['id'])
        wl2 = self.workloadAPI.workload_show(self.context, workload['id'])
        self.assertEqual(wl2['display_name'], 'changed name')
        self.assertEqual(wl2['display_description'], 'changed description')

    @patch('workloadmgr.workloads.workload_utils.upload_workload_db_entry')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workloads.api.API.trust_create')
    @patch('workloadmgr.compute.nova.API.get_servers')
    @patch('workloadmgr.autolog.Logger.log')
    def test_workload_reset(self, log_mock, mock_get_servers,
                            trust_create_mock, set_meta_item_mock,
                            delete_meta_mock, upload_mock):

        mock_get_servers.side_effect = tests_utils.get_vms
        x = 0
        name = "workload_type_%d" % x
        description = "workload_type_%d for dummies" % x
        is_public = True
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3',
                    'key4': 'value4',
                    'key5': 'value5',
                    'backup_media_target': 'server2:nfsshare2'}

        workload_type_id = str(uuid.uuid4())
        self.workloadAPI.workload_type_create(
                self.context, workload_type_id, name,
                description, is_public, metadata)
        source_platform = 'openstack'
        name = 'test-workload'
        description = 'test-workload'
        instances = [{'instance-id': '4f92587b-cf3a-462a-89d4-0f5634293477'},
                     {'instance-id': 'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132'}]

        for instance in instances:
            for wl in self.db.workload_vm_get_by_id(self.context, instance['instance-id']):
                self.db.workload_vms_delete(self.context, wl.vm_id, wl.workload_id)

        jobschedule =  {'enabled': True,
                        'start_date': '06/05/2014',
                        'end_date': '07/05/2019',
                        'interval': '1 hr',
                        'start_time': '2:30 PM',
                        'fullbackup_interval': -1,
                        'retention_policy_type': 'Number of Snapshots to Keep',
                        'retention_policy_value': '30'}
        availability_zone = 'testnova'
        self.context.user_id = str(uuid.uuid4())
        self.context.project_id = '000d038df75743a88cefaacd9b704b94'
        self.context.tenant_id = '000d038df75743a88cefaacd9b704b94'

        workload = self.workloadAPI.workload_create(
                          self.context, name, description,
                          workload_type_id, source_platform,
                          instances, jobschedule, metadata,
                          availability_zone=availability_zone)

        self.db.workload_update(self.context, workload.id,
                                {'status': 'available',})

        self.assertEqual(len(self.db.workload_vms_get(self.context, workload.id)), 2)
        self.assertEqual(self.db.workload_get(self.context, workload.id).id, workload.id)
        workload = self.workloadAPI.workload_show(self.context, workload.id)

        self.workloadAPI.workload_reset(self.context, workload['id'])

    def test_get_import_workloads_list(self):
        pass

    def test_import_workloads(self):
        pass

    def test_get_nodes(self):
        pass

    def test_remove_node(self):
        pass

    def test_get_contego_status(self):
        pass

    def add_node(self):
        pass

    def test_get_storage_usage(self):
        pass

    def test_get_recentactivities(self):
        pass

    def test_get_auditlog(self):
        pass

    def test_is_workload_paused(self):
        pass

    def test_workload_pause(self):
        pass

    def test_workload_resume(self):
        pass

    def test_workload_unlock(self):
        pass

    def test_workload_snapshot(self):
        pass

    def test_snapshot_get(self):
        pass

    def test_snapshot_show(self):
        pass

    def test_snapshot_delete(self):
        pass

    def test_snapshot_restore(self):
        pass

    def test_snapshot_cancel(self):
        pass

    def test_snapshot_mount(self):
        pass

    def test_snapshot_dismount(self):
        pass

    def test_mounted_list(self):
        pass

    def test_restore_get(self):
        pass

    def test_restore_show(self):
        pass

    def test_restore_cancel(self):
        pass
