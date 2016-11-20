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
#from workloadmgr.workloads.api import API

CONF = cfg.CONF

def get_instances():
    instances = [{u'instance-id': u'4f92587b-cf3a-462a-89d4-0f5634293477', 'instance-name': 'vm1'},
                 {u'instance-id': u'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132', 'instance-name': 'vm2'},
                 {u'instance-id': u'd4e6e988-21ca-497e-940a-7b2f36426797', 'instance-name': 'vm3'},
                 {u'instance-id': u'1b3a8734-b476-49f9-a959-ea909026b25f', 'instance-name': 'vm4'},
                 {u'instance-id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', 'instance-name': 'vm5'}]
    return instances


def get_restore_options():
    return { u'description': u'Restore one day old snapshot',
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
                                                                 u'target_network': {u'id': u'b5eef466-1af0-4e5b-a725-54b385e7c42e',
                                                                                     u'name': u'private',
                                                                                     u'subnet': {u'id': u'40eeba1b-0803-469c-b4c9-dadb2070f2c8'}}}]}},
             u'type': u'openstack',
             u'zone': u'nova'}


def get_vms(cntx, admin=False):
    vms = []
    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:12:2a:d8', u'version': 4, u'addr': u'10.0.0.18', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477', u'rel': u'bookmark'}], 'image': u'', 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-00000010', 'OS-SRV-USG:launched_at': u'2016-11-29T03:00:46.000000', 'flavor': {u'id': u'42', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}]}, 'id': u'4f92587b-cf3a-462a-89d4-0f5634293477', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'MANUAL', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-29T03:02:24Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'bootvol', 'created': u'2016-11-29T03:00:37Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [{u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:12:2a:d8', u'version': 4, u'addr': u'10.0.0.18', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477', u'rel': u'bookmark'}], u'image': u'', u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000010', u'OS-SRV-USG:launched_at': u'2016-11-29T03:00:46.000000', u'flavor': {u'id': u'42', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}]}, u'id': u'4f92587b-cf3a-462a-89d4-0f5634293477', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'MANUAL', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-29T03:02:24Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'bootvol', u'created': u'2016-11-29T03:00:37Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [{u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}], u'metadata': {}}, 'metadata': {}, '_loaded': True}))

    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:58:7f:b0', u'version': 4, u'addr': u'10.0.0.17', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132', u'rel': u'bookmark'}], 'image': u'', 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000f', 'OS-SRV-USG:launched_at': u'2016-11-29T02:49:26.000000', 'flavor': {u'id': u'42', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}]}, 'id': u'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'MANUAL', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-29T02:50:48Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'bootvol-restored', 'created': u'2016-11-29T02:49:16Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [{u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:58:7f:b0', u'version': 4, u'addr': u'10.0.0.17', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132', u'rel': u'bookmark'}], u'image': u'', u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000f', u'OS-SRV-USG:launched_at': u'2016-11-29T02:49:26.000000', u'flavor': {u'id': u'42', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}]}, u'id': u'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'MANUAL', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-29T02:50:48Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'bootvol-restored', u'created': u'2016-11-29T02:49:16Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [{u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}], u'metadata': {}}, 'metadata': {}, '_loaded': True}))

    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6c:06:03', u'version': 4, u'addr': u'10.0.0.16', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991', u'rel': u'bookmark'}], 'image': u'', 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000e', 'OS-SRV-USG:launched_at': u'2016-11-29T02:45:32.000000', 'flavor': {u'id': u'42', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}]}, 'id': u'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-29T02:45:32Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'bootvol', 'created': u'2016-11-29T02:45:10Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [{u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6c:06:03', u'version': 4, u'addr': u'10.0.0.16', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991', u'rel': u'bookmark'}], u'image': u'', u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000e', u'OS-SRV-USG:launched_at': u'2016-11-29T02:45:32.000000', u'flavor': {u'id': u'42', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}]}, u'id': u'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-29T02:45:32Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'bootvol', u'created': u'2016-11-29T02:45:10Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [{u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}], u'metadata': {u'workload_id': u'62ca7590-11eb-481f-9197-7a2572fc73ed', u'workload_name': u'bootvol'}}, 'metadata': {u'workload_id': u'62ca7590-11eb-481f-9197-7a2572fc73ed', u'workload_name': u'bootvol'}, '_loaded': True}))
    vms.append(bunchify( {'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:e5:ff:94', u'version': 4, u'addr': u'10.0.0.14', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797', u'rel': u'bookmark'}], 'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000d', 'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', 'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, 'id': u'd4e6e988-21ca-497e-940a-7b2f36426797', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-26T08:26:09Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'vm-4', 'created': u'2016-11-26T08:25:56Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:e5:ff:94', u'version': 4, u'addr': u'10.0.0.14', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797', u'rel': u'bookmark'}], u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000d', u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', u'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, u'id': u'd4e6e988-21ca-497e-940a-7b2f36426797', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-26T08:26:09Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'vm-4', u'created': u'2016-11-26T08:25:56Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [], u'metadata': {}}, 'metadata': {}, '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:64:ad:9c', u'version': 4, u'addr': u'10.0.0.13', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f', u'rel': u'bookmark'}], 'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000c', 'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', 'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, 'id': u'1b3a8734-b476-49f9-a959-ea909026b25f', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-26T08:26:09Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'vm-3', 'created': u'2016-11-26T08:25:56Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:64:ad:9c', u'version': 4, u'addr': u'10.0.0.13', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f', u'rel': u'bookmark'}], u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000c', u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', u'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, u'id': u'1b3a8734-b476-49f9-a959-ea909026b25f', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-26T08:26:09Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'vm-3', u'created': u'2016-11-26T08:25:56Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [], u'metadata': {}}, 'metadata': {}, '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:3d:27:b3', u'version': 4, u'addr': u'10.0.0.15', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', u'rel': u'bookmark'}], 'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000b', 'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', 'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, 'id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-26T08:26:09Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'vm-2', 'created': u'2016-11-26T08:25:55Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:3d:27:b3', u'version': 4, u'addr': u'10.0.0.15', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', u'rel': u'bookmark'}], u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000b', u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', u'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, u'id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-26T08:26:09Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'vm-2', u'created': u'2016-11-26T08:25:55Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [], u'metadata': {}}, 'metadata': {}, '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:b4:80:be', u'version': 4, u'addr': u'10.0.0.12', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d', u'rel': u'bookmark'}], 'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000a', 'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', 'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, 'id': u'2b2e372e-ba6f-4bbd-8a8c-522de89c391d', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-26T08:26:09Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'vm-1', 'created': u'2016-11-26T08:25:55Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:b4:80:be', u'version': 4, u'addr': u'10.0.0.12', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d', u'rel': u'bookmark'}], u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000a', u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000', u'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, u'id': u'2b2e372e-ba6f-4bbd-8a8c-522de89c391d', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-26T08:26:09Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'vm-1', u'created': u'2016-11-26T08:25:55Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'workload_id': u'7256e3a4-4326-4042-85c6-adc41b7e6f60', u'workload_name': u'vm3'}}, 'metadata': {u'workload_id': u'7256e3a4-4326-4042-85c6-adc41b7e6f60', u'workload_name': u'vm3'}, '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6b:4e:38', u'version': 4, u'addr': u'10.0.0.11', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21', u'rel': u'bookmark'}], 'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-00000009', 'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000', 'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, 'id': u'275f9587-dfdf-457a-9926-0f21e9c1eb21', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-26T08:22:55Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'vm-2', 'created': u'2016-11-26T08:22:22Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6b:4e:38', u'version': 4, u'addr': u'10.0.0.11', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21', u'rel': u'bookmark'}], u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000009', u'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000', u'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, u'id': u'275f9587-dfdf-457a-9926-0f21e9c1eb21', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-26T08:22:55Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'vm-2', u'created': u'2016-11-26T08:22:22Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'workload_id': u'c173d256-0d01-45dc-b6db-c3454cf0c30f', u'workload_name': u'vm2'}}, 'metadata': {u'workload_id': u'c173d256-0d01-45dc-b6db-c3454cf0c30f', u'workload_name': u'vm2'}, '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:1e:77:4c', u'version': 4, u'addr': u'10.0.0.10', u'OS-EXT-IPS:type': u'fixed'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b', u'rel': u'bookmark'}], 'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-00000008', 'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000', 'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, 'id': u'aef3fbf0-e621-459e-8237-12ac9254411b', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-26T08:22:55Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'vm-1', 'created': u'2016-11-26T08:22:21Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:1e:77:4c', u'version': 4, u'addr': u'10.0.0.10', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b', u'rel': u'bookmark'}], u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000008', u'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000', u'flavor': {u'id': u'1', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}]}, u'id': u'aef3fbf0-e621-459e-8237-12ac9254411b', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-26T08:22:55Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'vm-1', u'created': u'2016-11-26T08:22:21Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'workload_id': u'4672d6bb-abc1-4a72-b0b7-cc0791bfa221', u'workload_name': u'vm1'}}, 'metadata': {u'workload_id': u'4672d6bb-abc1-4a72-b0b7-cc0791bfa221', u'workload_name': u'vm1'}, '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None, 'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b', u'version': 4, u'addr': u'10.0.0.7', u'OS-EXT-IPS:type': u'fixed'}, {u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b', u'version': 4, u'addr': u'172.24.4.3', u'OS-EXT-IPS:type': u'floating'}]}, 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f', u'rel': u'bookmark'}], 'image': {u'id': u'31e3a8ba-d377-4024-aa84-204f5c4099e7', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/31e3a8ba-d377-4024-aa84-204f5c4099e7', u'rel': u'bookmark'}]}, 'manager': 'servermanager', 'OS-EXT-STS:vm_state': u'active', 'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005', 'OS-SRV-USG:launched_at': u'2016-11-22T05:10:57.000000', 'flavor': {u'id': u'3', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/3', u'rel': u'bookmark'}]}, 'id': u'28b734f3-4f25-4626-9155-c2d7bddabf3f', 'security_groups': [{u'name': u'default'}], 'user_id': u'e6e3159d1d3d4622befa70dd745af289', 'OS-DCF:diskConfig': u'AUTO', 'accessIPv4': u'', 'accessIPv6': u'', 'progress': 0, 'OS-EXT-STS:power_state': 1, 'OS-EXT-AZ:availability_zone': u'nova', 'config_drive': u'', 'status': u'ACTIVE', 'updated': u'2016-11-23T22:50:47Z', 'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', 'OS-EXT-SRV-ATTR:host': u'kilocontroller', 'OS-SRV-USG:terminated_at': None, 'key_name': u'kilocontroller', 'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', 'name': u'windows', 'created': u'2016-11-22T04:51:50Z', 'tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-extended-volumes:volumes_attached': [], '_info': {u'OS-EXT-STS:task_state': None, u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b', u'version': 4, u'addr': u'10.0.0.7', u'OS-EXT-IPS:type': u'fixed'}, {u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b', u'version': 4, u'addr': u'172.24.4.3', u'OS-EXT-IPS:type': u'floating'}]}, u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f', u'rel': u'bookmark'}], u'image': {u'id': u'31e3a8ba-d377-4024-aa84-204f5c4099e7', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/31e3a8ba-d377-4024-aa84-204f5c4099e7', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005', u'OS-SRV-USG:launched_at': u'2016-11-22T05:10:57.000000', u'flavor': {u'id': u'3', u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/3', u'rel': u'bookmark'}]}, u'id': u'28b734f3-4f25-4626-9155-c2d7bddabf3f', u'security_groups': [{u'name': u'default'}], u'user_id': u'e6e3159d1d3d4622befa70dd745af289', u'OS-DCF:diskConfig': u'AUTO', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'nova', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2016-11-23T22:50:47Z', u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452', u'OS-EXT-SRV-ATTR:host': u'kilocontroller', u'OS-SRV-USG:terminated_at': None, u'key_name': u'kilocontroller', u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller', u'name': u'windows', u'created': u'2016-11-22T04:51:50Z', u'tenant_id': u'000d038df75743a88cefaacd9b704b94', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'workload_id': u'dea51ebc-e0de-4032-b10c-1faceb4592d2', u'workload_name': u'wlm1'}}, 'metadata': {u'workload_id': u'dea51ebc-e0de-4032-b10c-1faceb4592d2', u'workload_name': u'wlm1'}, '_loaded': True}))
    return vms


def get_server_by_id(context, vm_id, admin=False):
    vms = get_vms(context)
    for vm in vms:
        if vm.id == vm_id:
            return vm
    return None

def get_flavors(context):
    flavors = {}

    flavors['1'] = bunchify({'name': u'm1.tiny', 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}], 'ram': 512, 'vcpus': 1, 'id': u'1', 'OS-FLV-DISABLED:disabled': False, 'manager': 'FlavorManager', 'swap': u'0', 'os-flavor-access:is_public': True, 'rxtx_factor': 1.0, '_info': {u'name': u'm1.tiny', u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1', u'rel': u'bookmark'}], u'ram': 512, u'OS-FLV-DISABLED:disabled': False, u'vcpus': 1, u'swap': u'0', u'os-flavor-access:is_public': True, u'rxtx_factor': 1.0, u'OS-FLV-EXT-DATA:ephemeral': 0, u'disk': 1, u'id': u'1'}, 'disk': 1, 'ephemeral': 0, 'OS-FLV-EXT-DATA:ephemeral': 0, '_loaded': True})

    flavors['42'] = bunchify({'name': u'm1.tiny', 'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}], 'ram': 8192, 'vcpus': 4, 'id': u'42', 'OS-FLV-DISABLED:disabled': False, 'manager': 'FlavorManager', 'swap': u'0', 'os-flavor-access:is_public': True, 'rxtx_factor': 1.0, '_info': {u'name': u'm1.medium', u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'self'}, {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42', u'rel': u'bookmark'}], u'ram': 8192, u'OS-FLV-DISABLED:disabled': False, u'vcpus': 4, u'swap': u'0', u'os-flavor-access:is_public': True, u'rxtx_factor': 1.0, u'OS-FLV-EXT-DATA:ephemeral': 0, u'disk': 40, u'id': u'1'}, 'disk': 40, 'ephemeral': 0, 'OS-FLV-EXT-DATA:ephemeral': 0, '_loaded': True})
 
    return flavors


def get_flavor_by_id(context, id):
    return get_flavors(context)[id]


def get_flavors_for_test(context):
    return get_flavors(context).values()


def get_volume_id(context, id, no_translate=True):
    volumes = {}
    volumes['b07c8751-f475-4f4c-94e7-72733f256b0b'] = bunchify({'attachments': [{u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'b07c8751-f475-4f4c-94e7-72733f256b0b', u'device': u'/dev/vdb', u'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b'}], 'availability_zone': u'nova', 'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', 'encrypted': False, 'os-volume-replication:extended_status': None, 'manager': 'VolumeManager', 'os-volume-replication:driver_data': None, 'snapshot_id': None, 'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b', 'size': 20, 'display_name': u'vol2', 'display_description': None, 'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-vol-mig-status-attr:migstat': None, 'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}, 'status': u'in-use', 'multiattach': u'false', 'source_volid': None, 'os-vol-mig-status-attr:name_id': None, 'bootable': u'false', 'created_at': u'2016-12-02T15:43:09.000000', 'volume_type': u'ceph', '_info': {u'status': u'in-use', u'display_name': u'vol2', u'attachments': [{u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'b07c8751-f475-4f4c-94e7-72733f256b0b', u'device': u'/dev/vdb', u'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b'}], u'availability_zone': u'nova', u'bootable': u'false', u'encrypted': False, u'created_at': u'2016-12-02T15:43:09.000000', u'multiattach': u'false', u'os-vol-mig-status-attr:migstat': None, u'os-volume-replication:driver_data': None, u'os-volume-replication:extended_status': None, u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', u'snapshot_id': None, u'display_description': None, u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', u'source_volid': None, u'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b', u'size': 20, u'volume_type': u'ceph', u'os-vol-mig-status-attr:name_id': None, u'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}}, '_loaded': True})

    volumes['c16006a6-60fe-4046-9eb0-35e37fe3e3f4'] = bunchify({'attachments': [{u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4', u'device': u'/dev/vdb', u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}], 'availability_zone': u'nova', 'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', 'encrypted': False, 'os-volume-replication:extended_status': None, 'manager': 'VolumeManager', 'os-volume-replication:driver_data': None, 'snapshot_id': None, 'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4', 'size': 40, 'display_name': u'vol2', 'display_description': None, 'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-vol-mig-status-attr:migstat': None, 'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}, 'status': u'in-use', 'multiattach': u'false', 'source_volid': None, 'os-vol-mig-status-attr:name_id': None, 'bootable': u'false', 'created_at': u'2016-12-02T15:43:09.000000', 'volume_type': u'ceph', '_info': {u'status': u'in-use', u'display_name': u'vol2', u'attachments': [{u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4', u'device': u'/dev/vdb', u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}], u'availability_zone': u'nova', u'bootable': u'false', u'encrypted': False, u'created_at': u'2016-12-02T15:43:09.000000', u'multiattach': u'false', u'os-vol-mig-status-attr:migstat': None, u'os-volume-replication:driver_data': None, u'os-volume-replication:extended_status': None, u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', u'snapshot_id': None, u'display_description': None, u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', u'source_volid': None, u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4', u'size': 40, u'volume_type': u'ceph', u'os-vol-mig-status-attr:name_id': None, u'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}}, '_loaded': True})

    volumes['92ded426-072c-4645-9f3a-72f9a3ad6899'] = bunchify({'attachments': [{u'server_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899', u'device': u'/dev/vdb', u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}], 'availability_zone': u'nova', 'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', 'encrypted': False, 'os-volume-replication:extended_status': None, 'manager': 'VolumeManager', 'os-volume-replication:driver_data': None, 'snapshot_id': None, 'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899', 'size': 80, 'display_name': u'vol2', 'display_description': None, 'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-vol-mig-status-attr:migstat': None, 'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}, 'status': u'in-use', 'multiattach': u'false', 'source_volid': None, 'os-vol-mig-status-attr:name_id': None, 'bootable': u'false', 'created_at': u'2016-12-02T15:43:09.000000', 'volume_type': u'ceph', '_info': {u'status': u'in-use', u'display_name': u'vol2', u'attachments': [{u'server_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899', u'device': u'/dev/vdb', u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}], u'availability_zone': u'nova', u'bootable': u'false', u'encrypted': False, u'created_at': u'2016-12-02T15:43:09.000000', u'multiattach': u'false', u'os-vol-mig-status-attr:migstat': None, u'os-volume-replication:driver_data': None, u'os-volume-replication:extended_status': None, u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', u'snapshot_id': None, u'display_description': None, u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', u'source_volid': None, u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899', u'size': 80, u'volume_type': u'ceph', u'os-vol-mig-status-attr:name_id': None, u'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}}, '_loaded': True})

    volumes['97aafa48-2d2c-4372-85ca-1d9d32cde50e'] = bunchify({'attachments': [{u'server_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e', u'device': u'/dev/vdb', u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}], 'availability_zone': u'nova', 'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', 'encrypted': False, 'os-volume-replication:extended_status': None, 'manager': 'VolumeManager', 'os-volume-replication:driver_data': None, 'snapshot_id': None, 'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e', 'size': 160, 'display_name': u'vol2', 'display_description': None, 'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', 'os-vol-mig-status-attr:migstat': None, 'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}, 'status': u'in-use', 'multiattach': u'false', 'source_volid': None, 'os-vol-mig-status-attr:name_id': None, 'bootable': u'false', 'created_at': u'2016-12-02T15:43:09.000000', 'volume_type': u'ceph', '_info': {u'status': u'in-use', u'display_name': u'vol2', u'attachments': [{u'server_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e', u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042', u'host_name': None, u'volume_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e', u'device': u'/dev/vdb', u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}], u'availability_zone': u'nova', u'bootable': u'false', u'encrypted': False, u'created_at': u'2016-12-02T15:43:09.000000', u'multiattach': u'false', u'os-vol-mig-status-attr:migstat': None, u'os-volume-replication:driver_data': None, u'os-volume-replication:extended_status': None, u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph', u'snapshot_id': None, u'display_description': None, u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94', u'source_volid': None, u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e', u'size': 160, u'volume_type': u'ceph', u'os-vol-mig-status-attr:name_id': None, u'metadata': {u'readonly': u'False', u'attached_mode': u'rw'}}, '_loaded': True})
    return volumes[id]


class BaseWorkloadTestCase(test.TestCase):
    """Test Case for workloads."""
    def setUp(self):
        super(BaseWorkloadTestCase, self).setUp()
        self.context = context.get_admin_context()


        CONF.set_default('vault_storage_nfs_export',
                         'server1:nfsshare1, server2:nfsshare2, server3:nfsshare3')

        patch('workloadmgr.workloads.api.create_trust', lambda x: x).start()
        patch('sys.stderr').start()
        self.is_online_patch = patch('workloadmgr.vault.vault.NfsTrilioVaultBackupTarget.is_online')
        self.subprocess_patch = patch('subprocess.check_call')
        self.MockMethod = self.is_online_patch.start()
        self.SubProcessMockMethod = self.subprocess_patch.start()
        self.MockMethod.return_value = True
        self.SubProcessMockMethod.return_value = True

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
            'host': CONF.host,}

    def tearDown(self):
        self.is_online_patch.stop()
        self.subprocess_patch.stop()
        super(BaseWorkloadTestCase, self).tearDown()

    def test_create_delete_workload(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '-1',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }
                    expected['status'] = 'available'
                    self.assertEqual(workload_id, self.db.workload_get(self.context, workload_id).id)

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)


    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    def test_create_delete_multivm_workload(self,
                                            set_meta_item_mock,
                                            delete_meta_mock,
                                            get_server_by_id_mock,
                                            get_flavor_by_id_mock,
                                            get_volume_mock):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager

        get_server_by_id_mock.side_effect = get_server_by_id
        get_flavor_by_id_mock.side_effect = get_flavor_by_id
        get_volume_mock.side_effect = get_volume_id
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values

                    self.workload_params['instances'] = get_instances()
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '-1',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }
                    expected['status'] = 'available'
                    self.assertEqual(workload_id, self.db.workload_get(self.context, workload_id).id)

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)

    def test_create_delete_workload_fullbackup_always(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': 0,
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '0',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }
                    expected['status'] = 'available'
                    self.assertEqual(workload_id, self.db.workload_get(self.context, workload_id).id)

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)

    def test_create_delete_workload_fullbackup_interval(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 10737418240],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
                    self.assertEqual(workload_id,
                                     self.db.workload_get(self.context,
                                                          workload_id).id)
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            self.assertEqual(meta.value, 'server1:nfsshare1')
                     
                    self.assertEqual(workload.status, 'available')
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '10',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)

    def test_create_delete_workload_with_one_nfs_full(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 5 * 10737418240],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
                    self.assertEqual(workload_id,
                                     self.db.workload_get(self.context,
                                                          workload_id).id)
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            self.assertEqual(meta.value, 'server2:nfsshare2')
                     
                    self.assertEqual(workload.status, 'available')
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '10',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
    def test_create_delete_workload_with_two_nfs_full(self):
        """Test workload can be created and deleted."""

        import workloadmgr.vault.vault
        import workloadmgr.workloads.manager
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                              {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                              {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                    mock_method2.side_effect = values
                    workload = tests_utils.create_workload(
                        self.context,
                        availability_zone=CONF.storage_availability_zone,
                        **self.workload_params)
                    workload_id = workload['id']
                    self.workload.workload_create(self.context, workload_id)
                    workload = self.db.workload_get(self.context, workload_id)
                    self.assertEqual(workload_id,
                                     self.db.workload_get(self.context,
                                                          workload_id).id)
                    for meta in workload.metadata:
                        if meta.key == 'backup_media_target':
                            self.assertEqual(meta.value, 'server3:nfsshare3')
                     
                    self.assertEqual(workload.status, 'available')
                    expected = {
                        'status': 'creating',
                        'display_name': 'test_workload',
                        'availability_zone': 'nova',
                        'tenant_id': 'fake',
                        'project_id': 'fake',
                        'created_at': 'DONTCARE',
                        'workload_id': workload_id,
                        'workload_type': None,
                        'user_id': 'fake',
                        'launched_at': 'DONTCARE',
                        'jobschedule': {'start_date': '06/05/2014',
                                        'end_date': '07/05/2015',
                                        'interval': '1 hr',
                                        'start_time': '2:30 PM',
                                        'fullbackup_interval': '10',
                                        'retention_policy_type': 'Number of Snapshots to Keep',
                                        'retention_policy_value': '30'}
                    }

                    self.workload.workload_delete(self.context, workload_id)
                    #workload = db.workload_get(self.context, workload_id)
                    #self.assertEqual(workload['status'], 'deleted')
                    self.assertRaises(exception.NotFound,
                                      db.workload_get,
                                      self.context,
                                      workload_id)
    def test_create_workload_with_invalid_workload_type(self):
        """Test workload can be created and deleted."""
        pass

    @patch('sys.stderr')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.initflow')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_snapshot(self, mock_get_servers, m1, m2, m3):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.return_value = []
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])
                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')


    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.workflows.serialworkflow.SerialWorkflow.execute')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_snapshot(self, mock_get_servers, m2,
                                                 set_meta_item_mock,
                                                 delete_meta_mock,
                                                 get_server_by_id_mock,
                                                 get_flavor_by_id_mock,
                                                 get_volume_mock):
        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = get_vms
        get_server_by_id_mock.side_effect = get_server_by_id
        get_flavor_by_id_mock.side_effect = get_flavor_by_id
        get_volume_mock.side_effect = get_volume_id
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            **self.workload_params)
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])
                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_snapshot_workflow_execute(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = get_vms
        get_server_by_id_mock.side_effect = get_server_by_id
        get_flavor_by_id_mock.side_effect = get_flavor_by_id
        get_volume_mock.side_effect = get_volume_id
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            **self.workload_params)
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)
  
                        # check all database records before deleting snapshots and workloads

    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_snapshot_workflow_execute_incr(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = get_vms
        get_server_by_id_mock.side_effect = get_server_by_id
        get_flavor_by_id_mock.side_effect = get_flavor_by_id
        get_volume_mock.side_effect = get_volume_id
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            **self.workload_params)
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')
  
                        # check all database records before deleting snapshots and workloads

    @patch('workloadmgr.workflows.vmtasks_openstack.post_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_keypairs')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavors')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_restore_workflow_execute(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_flavors_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy,
        pre_restore_vm_mock,
        restore_keypairs_mock,
        restore_vm_mock,
        post_restore_vm_mock):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = get_vms
        get_server_by_id_mock.side_effect = get_server_by_id
        get_flavor_by_id_mock.side_effect = get_flavor_by_id
        get_volume_mock.side_effect = get_volume_id
        get_flavors_mock.side_effect = get_flavors_for_test
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            **self.workload_params)
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        set_meta_item_mock.reset_mock()
                        delete_meta_mock.reset_mock()
                        pre_snapshot_vm_mock.reset_mock()
                        snapshot_vm_networks_mock.reset_mock()
                        snapshot_vm_security_groups.reset_mock()
                        snapshot_flavors_mock.reset_mock()
                        freeze_vm_mock.reset_mock()
                        thaw_vm_mock.reset_mock()
                        snapshot_vm_mock.reset_mock()
                        get_snapshot_data_size_mock.reset_mock()
                        upload_snapshot_mock.reset_mock()
                        post_snapshot_mock.reset_mock()
                        apply_retention_policy.reset_mock()

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])

                        self.assertEqual(set_meta_item_mock.call_count, 10)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')
  
                        options = get_restore_options()
                        restore = tests_utils.create_restore(self.context,
                                                              snapshot['id'],
                                                              display_name='test_snapshot',
                                                              display_description='this is a test snapshot',
                                                              options=options)
                        restore_id = restore['id']
                        self.workload.snapshot_restore(self.context, restore_id)
                        restore = self.db.restore_get(self.context, restore['id'])
                        self.assertEqual(restore.status, 'available')

                        self.assertEqual(pre_restore_vm_mock.call_count, 5)
                        self.assertEqual(restore_keypairs_mock.call_count, 1)
                        self.assertEqual(restore_vm_mock.call_count, 5)
                        self.assertEqual(post_restore_vm_mock.call_count, 5)

    @patch('workloadmgr.workflows.vmtasks_openstack.post_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.restore_keypairs')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_restore_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.apply_retention_policy')
    @patch('workloadmgr.workflows.vmtasks_openstack.post_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.upload_snapshot')
    @patch('workloadmgr.workflows.vmtasks_openstack.get_snapshot_data_size',
           return_value = {'vm_data_size': 1024 * 1024 * 1024 * 5})
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.thaw_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.freeze_vm')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_security_groups')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_flavors')
    @patch('workloadmgr.workflows.vmtasks_openstack.snapshot_vm_networks')
    @patch('workloadmgr.workflows.vmtasks_openstack.pre_snapshot_vm')
    @patch('workloadmgr.volume.cinder.API.get')
    @patch('workloadmgr.compute.nova.API.get_flavors')
    @patch('workloadmgr.compute.nova.API.get_flavor_by_id')
    @patch('workloadmgr.compute.nova.API.get_server_by_id')
    @patch('workloadmgr.compute.nova.API.delete_meta')
    @patch('workloadmgr.compute.nova.API.set_meta_item')
    @patch('workloadmgr.compute.nova.API.get_servers')
    def test_workload_with_multiple_vms_restore_workflow_execute_restore_vm_flow(
        self, mock_get_servers,
        set_meta_item_mock,
        delete_meta_mock,
        get_server_by_id_mock,
        get_flavor_by_id_mock,
        get_flavors_mock,
        get_volume_mock,
        pre_snapshot_vm_mock,
        snapshot_vm_networks_mock,
        snapshot_vm_security_groups,
        snapshot_flavors_mock,
        freeze_vm_mock,
        thaw_vm_mock,
        snapshot_vm_mock,
        get_snapshot_data_size_mock,
        upload_snapshot_mock,
        post_snapshot_mock,
        apply_retention_policy,
        pre_restore_vm_mock,
        restore_keypairs_mock,
        restore_vm_networks_mock,
        post_restore_vm_mock):

        """Test workload can be created and deleted."""
        import workloadmgr.vault.vault
        import workloadmgr.compute.nova
        import workloadmgr.workloads.manager

        mock_get_servers.side_effect = get_vms
        get_server_by_id_mock.side_effect = get_server_by_id
        get_flavor_by_id_mock.side_effect = get_flavor_by_id
        get_volume_mock.side_effect = get_volume_id
        get_flavors_mock.side_effect = get_flavors_for_test
        self.workload_params = {
            'status': 'creating',
            'jobschedule': pickle.dumps({'start_date': '06/05/2014',
                            'end_date': '07/05/2015',
                            'interval': '1 hr',
                            'start_time': '2:30 PM',
                            'fullbackup_interval': '10',
                            'retention_policy_type': 'Number of Snapshots to Keep',
                            'retention_policy_value': '30'}),
            'host': CONF.host,}
        with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                          'is_mounted', return_value=True) as mock_method1:
            with patch.object(workloadmgr.vault.vault.NfsTrilioVaultBackupTarget,
                              'get_total_capacity', return_value=None) as mock_method2:
                with patch.object(workloadmgr.workloads.manager.WorkloadMgrManager,
                                  'workload_reset', return_value=None) as mock_method3:
                    with patch.object(workloadmgr.compute.nova,
                                      '_get_tenant_context', return_value=None) as mock_method4:
                        values = [{'server1:nfsshare1': [1099511627776, 1099511627776],}.values()[0],
                                  {'server2:nfsshare2': [1099511627776, 1099511627776],}.values()[0],
                                  {'server3:nfsshare3': [1099511627776, 7 * 10737418240],}.values()[0],]

                        mock_method2.side_effect = values

                        def _get_tenant_context(context):
                            return context

                        mock_method4.side_effect = _get_tenant_context
                        workload_type = tests_utils.create_workload_type(self.context,
                                                         display_name='Serial',
                                                         display_description='this is a test workload_type',
                                                         status='available',
                                                         is_public=True,
                                                         metadata=None)

                        self.workload_params['instances'] = get_instances()
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            **self.workload_params)
                        workload = tests_utils.create_workload(
                            self.context,
                            availability_zone=CONF.storage_availability_zone,
                            workload_type_id=workload_type.id,
                            **self.workload_params)
                        workload_id = workload['id']
                        self.workload.workload_create(self.context, workload_id)

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])
                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')

                        self.assertEqual(set_meta_item_mock.call_count, 20)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        set_meta_item_mock.reset_mock()
                        delete_meta_mock.reset_mock()
                        pre_snapshot_vm_mock.reset_mock()
                        snapshot_vm_networks_mock.reset_mock()
                        snapshot_vm_security_groups.reset_mock()
                        snapshot_flavors_mock.reset_mock()
                        freeze_vm_mock.reset_mock()
                        thaw_vm_mock.reset_mock()
                        snapshot_vm_mock.reset_mock()
                        get_snapshot_data_size_mock.reset_mock()
                        upload_snapshot_mock.reset_mock()
                        post_snapshot_mock.reset_mock()
                        apply_retention_policy.reset_mock()

                        snapshot = tests_utils.create_snapshot(self.context,
                                                               workload_id,
                                                               display_name='test_snapshot',
                                                               display_description='this is a test snapshot',
                                                               snapshot_type='full',
                                                               status='creating')
                        self.workload.workload_snapshot(self.context, snapshot['id'])

                        self.assertEqual(set_meta_item_mock.call_count, 10)
                        self.assertEqual(delete_meta_mock.call_count, 5)
                        self.assertEqual(pre_snapshot_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_networks_mock.call_count, 1)
                        self.assertEqual(snapshot_vm_security_groups.call_count, 1)
                        self.assertEqual(snapshot_flavors_mock.call_count, 1)
                        self.assertEqual(freeze_vm_mock.call_count, 5)
                        self.assertEqual(thaw_vm_mock.call_count, 5)
                        self.assertEqual(snapshot_vm_mock.call_count, 5)
                        self.assertEqual(get_snapshot_data_size_mock.call_count, 5)
                        self.assertEqual(upload_snapshot_mock.call_count, 5)
                        self.assertEqual(post_snapshot_mock.call_count, 5)
                        self.assertEqual(apply_retention_policy.call_count, 1)

                        snapshot = self.db.snapshot_get(self.context, snapshot['id'])

                        self.assertEqual(snapshot.display_name, 'test_snapshot')
                        self.assertEqual(snapshot.status, 'available')
  
                        options = get_restore_options()
                        restore = tests_utils.create_restore(self.context,
                                                              snapshot['id'],
                                                              display_name='test_snapshot',
                                                              display_description='this is a test snapshot',
                                                              options=options)
                        restore_id = restore['id']
                        self.workload.snapshot_restore(self.context, restore_id)
                        restore = self.db.restore_get(self.context, restore['id'])
                        self.assertEqual(restore.status, 'available')

                        self.assertEqual(pre_restore_vm_mock.call_count, 5)
                        self.assertEqual(restore_keypairs_mock.call_count, 1)
                        self.assertEqual(restore_vm_mock.call_count, 5)
