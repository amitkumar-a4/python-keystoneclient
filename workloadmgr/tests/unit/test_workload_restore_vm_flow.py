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
from workloadmgr import exception
from workloadmgr import test
from workloadmgr.tests.unit import utils as tests_utils
from workloadmgr.openstack.common import importutils


CONF = cfg.CONF


def get_restore_options():
    return {u'description': u'Restore one day old snapshot',
            u'name': u'TestRestore',
            u'oneclickrestore': False,
            u'openstack': {u'instances': [{u'flavor': {u'disk': 1,
                                                       u'ephemeral': 0,
                                                       u'ram': 512,
                                                       u'swap': u'',
                                                       u'vcpus': 1},
                                           u'id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                                           u'include': True,
                                           u'name': u'vm-4',
                                           u'vdisks': [{u'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b',
                                                        u'new_volume_type': u'ceph'}]},
                                          {u'flavor': {u'disk': 1,
                                                       u'ephemeral': 0,
                                                       u'ram': 512,
                                                       u'swap': u'',
                                                       u'vcpus': 1},
                                           u'id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42',
                                           u'include': True,
                                           u'name': u'vm-2',
                                           u'vdisks': []},
                                          {u'flavor': {u'disk': 1,
                                                       u'ephemeral': 0,
                                                       u'ram': 512,
                                                       u'swap': u'',
                                                       u'vcpus': 1},
                                           u'id': u'1b3a8734-b476-49f9-a959-ea909026b25f',
                                           u'include': True,
                                           u'name': u'vm-3',
                                           u'vdisks': []}],
                            u'networks_mapping': {u'networks': [{u'snapshot_network': {u'id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                                                       u'subnet': {u'id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8'}},
                                                                 u'target_network': {u'id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                                                     u'name': u'private',
                                                                                     u'subnet': {u'id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8'}}}]}},
            u'type': u'openstack',
            u'zone': u'nova'}


class BaseWorkloadTestCase(test.TestCase):
    """Test Case for workloads."""

    def setUp(self):
        super(BaseWorkloadTestCase, self).setUp()
        self.context = context.get_admin_context()

        CONF.set_default(
            'vault_storage_nfs_export',
            'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        self.is_online_patch = patch(
            'workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')
        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True

        patch('workloadmgr.workloads.api.create_trust', lambda x: x).start()
        patch('sys.stderr').start()

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

    def test_get_new_volume_type(self):
        from workloadmgr.virt.libvirt import restore_vm_flow
        new_type = restore_vm_flow.get_new_volume_type(
            get_restore_options()['openstack']['instances'][0],
            u'b07c8751-f475-4f4c-94e7-72733f256b0b',
            "lvm")
        self.assertEqual(new_type, 'ceph')
        new_type = restore_vm_flow.get_new_volume_type(
            get_restore_options()['openstack']['instances'][1],
            u'b07c8751-f475-4f4c-94e7-72733f256b0b',
            "lvm")
        self.assertEqual(new_type, 'lvm')

        new_type = restore_vm_flow.get_new_volume_type(
            get_restore_options()['openstack']['instances'][1],
            u'a07c8751-f475-4f4c-94e7-72733f256b0b',
            "lvm")
        self.assertEqual(new_type, 'lvm')

    def test_get_availability_zone(self):
        from workloadmgr.virt.libvirt import restore_vm_flow

        inst = get_restore_options()['openstack']['instances'][0]
        az = restore_vm_flow.get_availability_zone(inst)
        self.assertEqual(az, None)

        CONF.set_default('default_production_availability_zone', "myzone")
        inst = get_restore_options()['openstack']['instances'][0]
        az = restore_vm_flow.get_availability_zone(inst)
        self.assertEqual(az, 'myzone')

        inst = get_restore_options()['openstack']['instances'][0]
        inst['availability_zone'] = 'nova'
        az = restore_vm_flow.get_availability_zone(inst)

        self.assertEqual(az, 'nova')

    def test_restore_vm(self):

        inst = get_restore_options()['openstack']['instances'][0]
        db = self.db

        instance = {
            'vm_name': u'vm-2',
            'hypervisor_type': 'QEMU',
            'keydata': u'(dp1\nVpublic_key\np2\nVssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDVBsT8QeM6IhauMUnNKDQ2Xm8qoQhgkWPLkNLspEWMMb5QwEE/sDCkp7GHYWmV4rd2d5NKpQfkPTwKfiFfFwwJKwhsWSjY4L3JGuUwDXsirqcQWZc4NRi0xgiCXids6tm+/UEfm9DMKjrbkBLPNvtMBUKRRFBvaoUZh2GNMBcmSaQWhTO6U/q1vCZ8+feCyZTXDU66aOIezkoZjMrV/OZ0IYpVAp6s2WKDdD3k/5oWnJ6ROl3aUSFyfgVHTdiQvUiXyN7JPADdVja1jKp9sCEzggQG4NpVWlB+fjL0GaxDa1WyN4E2lPc4Z0IeH9mkZiFcq47LKrB6Wh23yJ74BxN/ ubuntu@kilocontroller\np3\nsVuser_id\np4\nVe6e3159d1d3d4622befa70dd745af289\np5\nsVname\np6\nVkilocontroller\np7\nsVdeleted\np8\nI00\nsVcreated_at\np9\nV2016-11-22T04:32:28.000000\np10\nsVupdated_at\np11\nNsVfingerprint\np12\nVa9:1e:c1:b0:a4:eb:6e:e6:5a:e8:a1:f6:40:48:d5:1f\np13\nsVdeleted_at\np14\nNsVid\np15\nI1\ns.',
            'hypervisor_hostname': 'None',
            'keyname': u'kilocontroller',
            'vm_id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42'}
        restore = {
            'finished_at': None,
            'updated_at': datetime.datetime(
                2016,
                12,
                4,
                3,
                39,
                25,
                219395),
            'snapshot_id': u'0cc9f9bb-f726-4d2a-a7ae-5cfa80d43a9b',
            'deleted_at': None,
            'id': u'c71f0101-2a47-468e-8b76-a0e7b438e5df',
            'size': 65995264,
            'user_id': u'e6e3159d1d3d4622befa70dd745af289',
            'display_description': u'-',
            'time_taken': 0,
            'version': u'2.2.14',
            'project_id': u'000d038df75743a88cefaacd9b704b94',
            'status': u'executing',
            'deleted': False,
            'warning_msg': None,
            'host': u'tvault-51-1',
            'progress_msg': u'Restore from snapshot is starting',
            'display_name': u'rest',
            'target_platform': u'openstack',
            'error_msg': None,
            'uploaded_size': 0,
            'created_at': datetime.datetime(
                2016,
                12,
                4,
                3,
                39,
                24),
            'progress_percent': 0,
            'restore_type': u'restore',
            'pickle': u'(dp1\nVdescription\np2\nV-\nsVzone\np3\nVnova\np4\nsVoneclickrestore\np5\nI00\nsVopenstack\np6\n(dp7\nVinstances\np8\n(lp9\n(dp10\nVflavor\np11\n(dp12\nVvcpus\np13\nI1\nsVdisk\np14\nI1\nsVephemeral\np15\nI0\nsVram\np16\nI512\nsVswap\np17\nV\nssVinclude\np18\nI01\nsVvdisks\np19\n(lp20\nsVname\np21\nVvm-2\np22\nsVid\np23\nV9634ba8c-8d4f-49cb-9b6f-6b915c09fe42\np24\nsa(dp25\nVflavor\np26\n(dp27\nVvcpus\np28\nI1\nsVdisk\np29\nI1\nsVephemeral\np30\nI0\nsVram\np31\nI512\nsVswap\np32\nV\nssVinclude\np33\nI01\nsVvdisks\np34\n(lp35\nsVname\np36\nVvm-3\np37\nsVid\np38\nV1b3a8734-b476-49f9-a959-ea909026b25f\np39\nsa(dp40\nVflavor\np41\n(dp42\nVvcpus\np43\nI1\nsVdisk\np44\nI0\nsVephemeral\np45\nI0\nsVram\np46\nI64\nsVswap\np47\nV\nssVinclude\np48\nI01\nsVvdisks\np49\n(lp50\n(dp51\nVid\np52\nVc16006a6-60fe-4046-9eb0-35e37fe3e3f4\np53\nsVnew_volume_type\np54\nVceph\np55\nsasVname\np56\nVbootvol\np57\nsVid\np58\nV4f92587b-cf3a-462a-89d4-0f5634293477\np59\nsa(dp60\nVflavor\np61\n(dp62\nVvcpus\np63\nI1\nsVdisk\np64\nI0\nsVephemeral\np65\nI0\nsVram\np66\nI64\nsVswap\np67\nV\nssVinclude\np68\nI01\nsVvdisks\np69\n(lp70\n(dp71\nVid\np72\nV97aafa48-2d2c-4372-85ca-1d9d32cde50e\np73\nsVnew_volume_type\np74\nVceph\np75\nsasVname\np76\nVbootvol-restored\np77\nsVid\np78\nVa0635eb1-7a88-46d0-8c90-fe5b3a4b0132\np79\nsa(dp80\nVflavor\np81\n(dp82\nVvcpus\np83\nI1\nsVdisk\np84\nI0\nsVephemeral\np85\nI0\nsVram\np86\nI64\nsVswap\np87\nV\nssVinclude\np88\nI01\nsVvdisks\np89\n(lp90\n(dp91\nVid\np92\nV92ded426-072c-4645-9f3a-72f9a3ad6899\np93\nsVnew_volume_type\np94\nVceph\np95\nsasVname\np96\nVbootvol\np97\nsVid\np98\nVdc35b6fe-38fb-46d2-bdfb-c9cee76f3991\np99\nsa(dp100\nVflavor\np101\n(dp102\nVvcpus\np103\nI1\nsVdisk\np104\nI1\nsVephemeral\np105\nI0\nsVram\np106\nI512\nsVswap\np107\nV\nssVinclude\np108\nI01\nsVvdisks\np109\n(lp110\n(dp111\nVid\np112\nVb07c8751-f475-4f4c-94e7-72733f256b0b\np113\nsVnew_volume_type\np114\nVceph\np115\nsasVname\np116\nVvm-4\np117\nsVid\np118\nVd4e6e988-21ca-497e-940a-7b2f36426797\np119\nsasVnetworks_mapping\np120\n(dp121\nVnetworks\np122\n(lp123\n(dp124\nVsnapshot_network\np125\n(dp126\nVsubnet\np127\n(dp128\nVid\np129\nV40eeba1b-0803-469c-b4c9-dadb2070f2c8\np130\nssVid\np131\nVb5eef466-1af0-4e5b-a725-54b385e7c42e\np132\nssVtarget_network\np133\n(dp134\nVsubnet\np135\n(dp136\nVid\np137\nV40eeba1b-0803-469c-b4c9-dadb2070f2c8\np138\nssVid\np139\nVb5eef466-1af0-4e5b-a725-54b385e7c42e\np140\nsVname\np141\nVprivate\np142\nssasssVtype\np143\nVopenstack\np144\nsVname\np145\nVrest\np146\ns.'}
        restored_net_resources = {u'fa:16:3e:6c:06:03': {u'status': u'DOWN',
                                                         u'binding:host_id': u'',
                                                         u'name': u'bootvol',
                                                         u'allowed_address_pairs': [],
                                                         u'admin_state_up': True,
                                                         u'network_id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                         u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                                         u'binding:vif_details': {},
                                                         u'binding:vnic_type': u'normal',
                                                         u'binding:vif_type': u'unbound',
                                                         u'device_owner': u'',
                                                         u'production': False,
                                                         u'mac_address': u'fa:16:3e:b8:a0:81',
                                                         u'binding:profile': {},
                                                         u'fixed_ips': [{u'subnet_id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8',
                                                                         u'ip_address': u'10.0.0.28'}],
                                                         u'id': u'd6f750cb-e00d-4ff0-8a5e-28cecb580556',
                                                         u'security_groups': [u'551b0ba0-4e68-4658-b8e1-ce2b7424232f'],
                                                         u'device_id': u''},
                                  u'fa:16:3e:58:7f:b0': {u'status': u'DOWN',
                                                         u'binding:host_id': u'',
                                                         u'name': u'bootvol-restored',
                                                         u'allowed_address_pairs': [],
                                                         u'admin_state_up': True,
                                                         u'network_id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                         u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                                         u'binding:vif_details': {},
                                                         u'binding:vnic_type': u'normal',
                                                         u'binding:vif_type': u'unbound',
                                                         u'device_owner': u'',
                                                         u'production': False,
                                                         u'mac_address': u'fa:16:3e:64:5e:8a',
                                                         u'binding:profile': {},
                                                         u'fixed_ips': [{u'subnet_id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8',
                                                                         u'ip_address': u'10.0.0.27'}],
                                                         u'id': u'e0e79470-8941-4c92-92dc-3130c2d040df',
                                                         u'security_groups': [u'551b0ba0-4e68-4658-b8e1-ce2b7424232f'],
                                                         u'device_id': u''},
                                  u'fa:16:3e:3d:27:b3': {u'status': u'DOWN',
                                                         u'binding:host_id': u'',
                                                         u'name': u'vm-2',
                                                         u'allowed_address_pairs': [],
                                                         u'admin_state_up': True,
                                                         u'network_id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                         u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                                         u'binding:vif_details': {},
                                                         u'binding:vnic_type': u'normal',
                                                         u'binding:vif_type': u'unbound',
                                                         u'device_owner': u'',
                                                         u'production': False,
                                                         u'mac_address': u'fa:16:3e:ff:ad:d0',
                                                         u'binding:profile': {},
                                                         u'fixed_ips': [{u'subnet_id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8',
                                                                         u'ip_address': u'10.0.0.24'}],
                                                         u'id': u'0ccddda6-fbe1-4c02-87e2-6c7953afe1b6',
                                                         u'security_groups': [u'551b0ba0-4e68-4658-b8e1-ce2b7424232f'],
                                                         u'device_id': u''},
                                  u'fa:16:3e:e5:ff:94': {u'status': u'DOWN',
                                                         u'binding:host_id': u'',
                                                         u'name': u'vm-4',
                                                         u'allowed_address_pairs': [],
                                                         u'admin_state_up': True,
                                                         u'network_id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                         u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                                         u'binding:vif_details': {},
                                                         u'binding:vnic_type': u'normal',
                                                         u'binding:vif_type': u'unbound',
                                                         u'device_owner': u'',
                                                         u'production': False,
                                                         u'mac_address': u'fa:16:3e:79:38:34',
                                                         u'binding:profile': {},
                                                         u'fixed_ips': [{u'subnet_id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8',
                                                                         u'ip_address': u'10.0.0.29'}],
                                                         u'id': u'a4a24f29-bc6f-4ce7-b99d-028f1efaba91',
                                                         u'security_groups': [u'551b0ba0-4e68-4658-b8e1-ce2b7424232f'],
                                                         u'device_id': u''},
                                  u'fa:16:3e:12:2a:d8': {u'status': u'DOWN',
                                                         u'binding:host_id': u'',
                                                         u'name': u'bootvol',
                                                         u'allowed_address_pairs': [],
                                                         u'admin_state_up': True,
                                                         u'network_id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                         u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                                         u'binding:vif_details': {},
                                                         u'binding:vnic_type': u'normal',
                                                         u'binding:vif_type': u'unbound',
                                                         u'device_owner': u'',
                                                         u'production': False,
                                                         u'mac_address': u'fa:16:3e:86:b8:8f',
                                                         u'binding:profile': {},
                                                         u'fixed_ips': [{u'subnet_id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8',
                                                                         u'ip_address': u'10.0.0.26'}],
                                                         u'id': u'936f477a-1bc4-4c25-a219-2d8d30bd031b',
                                                         u'security_groups': [u'551b0ba0-4e68-4658-b8e1-ce2b7424232f'],
                                                         u'device_id': u''},
                                  u'fa:16:3e:64:ad:9c': {u'status': u'DOWN',
                                                         u'binding:host_id': u'',
                                                         u'name': u'vm-3',
                                                         u'allowed_address_pairs': [],
                                                         u'admin_state_up': True,
                                                         u'network_id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                         u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                                         u'binding:vif_details': {},
                                                         u'binding:vnic_type': u'normal',
                                                         u'binding:vif_type': u'unbound',
                                                         u'device_owner': u'',
                                                         u'production': False,
                                                         u'mac_address': u'fa:16:3e:67:d3:1b',
                                                         u'binding:profile': {},
                                                         u'fixed_ips': [{u'subnet_id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8',
                                                                         u'ip_address': u'10.0.0.25'}],
                                                         u'id': u'333c25bc-9915-4728-b847-a345d718e035',
                                                         u'security_groups': [u'551b0ba0-4e68-4658-b8e1-ce2b7424232f'],
                                                         u'device_id': u''}}
        restored_security_groups = {
            u'551b0ba0-4e68-4658-b8e1-ce2b7424232f': u'551b0ba0-4e68-4658-b8e1-ce2b7424232f'}
        restored_compute_flavor = "<Flavor: m1.tiny>"
        restored_nics = [{'port-id': u'0ccddda6-fbe1-4c02-87e2-6c7953afe1b6',
                          'net-id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e'}]

        #cntx, db, instance, restore, restored_net_resources,
        #                restored_security_groups, restored_compute_flavor,
        #                restored_nics, instance_options):
