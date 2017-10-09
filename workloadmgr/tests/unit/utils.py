# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2014 Trilio Data, Inc


from bunch import bunchify, unbunchify
import cPickle as pickle
import os
import errno
import six

from workloadmgr import context
from workloadmgr import db
from workloadmgr import utils


def get_test_admin_context():
    return context.get_admin_context()


def create_workload(ctxt,
                    host='test_host',
                    display_name='test_workload',
                    display_description='this is a test workload',
                    status='available',
                    source_platform='openstack',
                    workload_type_id='test_workload_type',
                    availability_zone='nova',
                    jobschedule='test_jobschedule',
                    instances=[],
                    **kwargs):
    """Create a workload object in the DB."""
    workload_type = db.workload_type_get(ctxt, workload_type_id)
    workload = {}
    workload['host'] = host
    workload['user_id'] = ctxt.user_id
    workload['project_id'] = ctxt.project_id
    workload['status'] = status
    workload['display_name'] = display_name
    workload['display_description'] = display_description
    workload['availability_zone'] = availability_zone
    workload['source_platform'] = source_platform
    workload['workload_type_id'] = workload_type_id
    workload['jobschedule'] = jobschedule
    for key in kwargs:
        workload[key] = kwargs[key]

    workload = db.workload_create(ctxt, workload)

    for instance in instances:
        values = {'workload_id': workload.id,
                  'vm_id': instance['instance-id'],
                  'vm_name': instance['instance-name'],
                  'status': 'available',
                  'metadata': instance.get('metadata', {})}
        vm = db.workload_vms_create(ctxt, values)

    return workload


def create_workload_type(ctxt,
                         display_name='test_workload_type',
                         display_description='this is a test workload_type',
                         status='available',
                         is_public=True,
                         metadata=None):
    workloadtype = {}
    if metadata is None:
        metadata = {}
    workloadtype['user_id'] = ctxt.user_id
    workloadtype['project_id'] = ctxt.project_id
    workloadtype['status'] = status
    workloadtype['display_name'] = display_name
    workloadtype['display_description'] = display_description
    workloadtype['metadata'] = metadata
    workloadtype['is_public'] = is_public
    return db.workload_type_create(ctxt, workloadtype)


def create_snapshot(ctxt,
                    workload_id,
                    display_name='test_snapshot',
                    display_description='this is a test snapshot',
                    snapshot_type='full',
                    status='creating'):
    workload = db.workload_get(ctxt, workload_id)
    snapshot = {}
    snapshot['workload_id'] = workload_id
    snapshot['user_id'] = ctxt.user_id
    snapshot['project_id'] = ctxt.project_id
    snapshot['status'] = status
    snapshot['display_name'] = display_name
    snapshot['display_description'] = display_description
    snapshot['snapshot_type'] = snapshot_type
    return db.snapshot_create(ctxt, snapshot)


def create_restore(ctxt,
                   snapshot_id,
                   display_name='test_restore',
                   display_description='this is a test snapshot',
                   options=[]):
    snapshot = db.snapshot_get(ctxt, snapshot_id)
    values = {'user_id': ctxt.user_id,
              'project_id': ctxt.project_id,
              'snapshot_id': snapshot_id,
              'restore_type': "restore",
              'display_name': display_name,
              'display_description': display_description,
              'pickle': pickle.dumps(options, 0),
              'host': '',
              'status': 'restoring', }
    restore = db.restore_create(ctxt, values)

    db.restore_update(ctxt,
                      restore.id,
                      {'progress_percent': 0,
                       'progress_msg': 'Restore operation is scheduled',
                       'status': 'restoring'
                       })
    return restore


class Resource(object):
    """Base class for OpenStack resources (tenant, user, etc.).

    This is pretty much just a bag for attributes.
    """

    HUMAN_ID = False
    NAME_ATTR = 'name'

    def __init__(self, manager, info, loaded=False):
        """Populate and bind to a manager.

        :param manager: BaseManager object
        :param info: dictionary representing resource attributes
        :param loaded: prevent lazy-loading if set to True
        """
        self.manager = manager
        self._info = info
        self._add_details(info)
        self._loaded = loaded

    def __repr__(self):
        reprkeys = sorted(k
                          for k in self.__dict__.keys()
                          if k[0] != '_' and k != 'manager')
        info = ", ".join("%s=%s" % (k, getattr(self, k)) for k in reprkeys)
        return "<%s %s>" % (self.__class__.__name__, info)

    @property
    def human_id(self):
        """Human-readable ID which can be used for bash completion.
        """
        if self.NAME_ATTR in self.__dict__ and self.HUMAN_ID:
            return strutils.to_slug(getattr(self, self.NAME_ATTR))
        return None

    def _add_details(self, info):
        for (k, v) in six.iteritems(info):
            try:
                setattr(self, k, v)
                self._info[k] = v
            except AttributeError:
                # In this case we already defined the attribute on the class
                pass

    def __getattr__(self, k):
        if k not in self.__dict__:
            # NOTE(bcwaldon): disallow lazy-loading if already loaded once
            if not self.is_loaded():
                self.get()
                return self.__getattr__(k)

            raise AttributeError(k)
        else:
            return self.__dict__[k]

    def get(self):
        """Support for lazy loading details.

        Some clients, such as novaclient have the option to lazy load the
        details, details which can be loaded with this function.
        """
        # set_loaded() first ... so if we have to bail, we know we tried.
        self.set_loaded(True)
        if not hasattr(self.manager, 'get'):
            return

        new = self.manager.get(self.id)
        if new:
            self._add_details(new._info)

    def __eq__(self, other):
        if not isinstance(other, Resource):
            return NotImplemented
        # two resources of different types are not equal
        if not isinstance(other, self.__class__):
            return False
        if hasattr(self, 'id') and hasattr(other, 'id'):
            return self.id == other.id
        return self._info == other._info

    def is_loaded(self):
        return self._loaded

    def set_loaded(self, val):
        self._loaded = val

    def to_dict(self):
        return copy.deepcopy(self._info)


def build_instances():
    instdata = []
    instdata.append({u'OS-EXT-STS:task_state': None,
                     u'addresses': {u'br-int': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:9f:9d:d3',
                                                 u'version': 4,
                                                 u'addr': u'172.17.17.19',
                                                 u'OS-EXT-IPS:type': u'fixed'}]},
                     u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/e44e5170-255d-42fb-a603-89fa171104e1',
                                 u'rel': u'self'},
                                {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/e44e5170-255d-42fb-a603-89fa171104e1',
                                 u'rel': u'bookmark'}],
                     u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157',
                                u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157',
                                            u'rel': u'bookmark'}]},
                     u'OS-EXT-STS:vm_state': u'active',
                     u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000007',
                     u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:36.000000',
                     u'flavor': {u'id': u'3f086923-a0ec-4610-8ab4-ccd1d40b73eb',
                                 u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/3f086923-a0ec-4610-8ab4-ccd1d40b73eb',
                                             u'rel': u'bookmark'}]},
                     u'id': u'e44e5170-255d-42fb-a603-89fa171104e1',
                     u'security_groups': [{u'name': u'default'}],
                     u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763',
                     u'OS-DCF:diskConfig': u'MANUAL',
                     u'accessIPv4': u'',
                     u'accessIPv6': u'',
                     u'progress': 0,
                     u'OS-EXT-STS:power_state': 1,
                     u'OS-EXT-AZ:availability_zone': u'tvault_az',
                     u'config_drive': u'',
                     u'status': u'ACTIVE',
                     u'updated': u'2014-09-07T23:41:36Z',
                     u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b',
                     u'OS-EXT-SRV-ATTR:host': u'cloudvault1',
                     u'OS-SRV-USG:terminated_at': None,
                     u'key_name': None,
                     u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)',
                     u'name': u'd8848b37-1f6a-4a60-9aa5-d7763f710f2a',
                     u'created': u'2014-09-07T23:41:27Z',
                     u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2',
                     u'os-extended-volumes:volumes_attached': [],
                     u'metadata': {u'imported_from_vcenter': u'True',
                                   u'vmware_uuid': u'50378ee9-30ec-d38a-9132-4aad1463b168'}})
    instdata.append({u'OS-EXT-STS:task_state': None,
                     u'addresses': {u'br-int': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:87:af:d1',
                                                 u'version': 4,
                                                 u'addr': u'172.17.17.21',
                                                 u'OS-EXT-IPS:type': u'fixed'}]},
                     u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/b66be913-9f3e-4adf-9274-4a36e980ff25',
                                 u'rel': u'self'},
                                {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/b66be913-9f3e-4adf-9274-4a36e980ff25',
                                 u'rel': u'bookmark'}],
                     u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157',
                                u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157',
                                            u'rel': u'bookmark'}]},
                     u'OS-EXT-STS:vm_state': u'active',
                     u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000006',
                     u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:36.000000',
                     u'flavor': {u'id': u'ab136999-e31e-421f-a6c9-22e9434402c3',
                                 u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/ab136999-e31e-421f-a6c9-22e9434402c3',
                                             u'rel': u'bookmark'}]},
                     u'id': u'b66be913-9f3e-4adf-9274-4a36e980ff25',
                     u'security_groups': [{u'name': u'default'}],
                     u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763',
                     u'OS-DCF:diskConfig': u'MANUAL',
                     u'accessIPv4': u'',
                     u'accessIPv6': u'',
                     u'progress': 0,
                     u'OS-EXT-STS:power_state': 1,
                     u'OS-EXT-AZ:availability_zone': u'tvault_az',
                     u'config_drive': u'',
                     u'status': u'ACTIVE',
                     u'updated': u'2014-09-07T23:41:37Z',
                     u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b',
                     u'OS-EXT-SRV-ATTR:host': u'cloudvault1',
                     u'OS-SRV-USG:terminated_at': None,
                     u'key_name': None,
                     u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)',
                     u'name': u'testVM',
                     u'created': u'2014-09-07T23:41:27Z',
                     u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2',
                     u'os-extended-volumes:volumes_attached': [],
                     u'metadata': {u'imported_from_vcenter': u'True',
                                   u'vmware_uuid': u'50379ef0-13df-6aff-084a-abe9d01047f8'}})
    instdata.append({u'OS-EXT-STS:task_state': None,
                     u'addresses': {u'br100': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:1f:da:be',
                                                u'version': 4,
                                                u'addr': u'172.17.17.20',
                                                u'OS-EXT-IPS:type': u'fixed'}]},
                     u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/f6792af5-ffaa-407b-8401-f8246323dedf',
                                 u'rel': u'self'},
                                {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/f6792af5-ffaa-407b-8401-f8246323dedf',
                                 u'rel': u'bookmark'}],
                     u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157',
                                u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157',
                                            u'rel': u'bookmark'}]},
                     u'OS-EXT-STS:vm_state': u'active',
                     u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005',
                     u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:36.000000',
                     u'flavor': {u'id': u'956b96d1-34d7-43a2-8d77-639f14167d02',
                                 u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/956b96d1-34d7-43a2-8d77-639f14167d02',
                                             u'rel': u'bookmark'}]},
                     u'id': u'f6792af5-ffaa-407b-8401-f8246323dedf',
                     u'security_groups': [{u'name': u'default'}],
                     u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763',
                     u'OS-DCF:diskConfig': u'MANUAL',
                     u'accessIPv4': u'',
                     u'accessIPv6': u'',
                     u'progress': 0,
                     u'OS-EXT-STS:power_state': 1,
                     u'OS-EXT-AZ:availability_zone': u'tvault_az',
                     u'config_drive': u'',
                     u'status': u'ACTIVE',
                     u'updated': u'2014-09-07T23:41:36Z',
                     u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b',
                     u'OS-EXT-SRV-ATTR:host': u'cloudvault1',
                     u'OS-SRV-USG:terminated_at': None,
                     u'key_name': None,
                     u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)',
                     u'name': u'vm1',
                     u'created': u'2014-09-07T23:41:26Z',
                     u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2',
                     u'os-extended-volumes:volumes_attached': [],
                     u'metadata': {u'imported_from_vcenter': u'True',
                                   u'vmware_uuid': u'5037bc07-3324-08b4-40ab-40b4edb75076'}})
    instdata.append({u'OS-EXT-STS:task_state': None,
                     u'addresses': {u'dswitch-pg1': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:b2:d1:42',
                                                      u'version': 4,
                                                      u'addr': u'172.17.17.22',
                                                      u'OS-EXT-IPS:type': u'fixed'}]},
                     u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/144775cc-764b-4af4-99b3-ac6df0cabf98',
                                 u'rel': u'self'},
                                {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/144775cc-764b-4af4-99b3-ac6df0cabf98',
                                 u'rel': u'bookmark'}],
                     u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157',
                                u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157',
                                            u'rel': u'bookmark'}]},
                     u'OS-EXT-STS:vm_state': u'active',
                     u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000003',
                     u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:35.000000',
                     u'flavor': {u'id': u'b2681ed4-f520-479c-a92a-8236ff17e0e3',
                                 u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/b2681ed4-f520-479c-a92a-8236ff17e0e3',
                                             u'rel': u'bookmark'}]},
                     u'id': u'144775cc-764b-4af4-99b3-ac6df0cabf98',
                     u'security_groups': [{u'name': u'default'}],
                     u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763',
                     u'OS-DCF:diskConfig': u'MANUAL',
                     u'accessIPv4': u'',
                     u'accessIPv6': u'',
                     u'progress': 0,
                     u'OS-EXT-STS:power_state': 1,
                     u'OS-EXT-AZ:availability_zone': u'tvault_az',
                     u'config_drive': u'',
                     u'status': u'ACTIVE',
                     u'updated': u'2014-09-07T23:41:35Z',
                     u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b',
                     u'OS-EXT-SRV-ATTR:host': u'cloudvault1',
                     u'OS-SRV-USG:terminated_at': None,
                     u'key_name': None,
                     u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)',
                     u'name': u'vmware1',
                     u'created': u'2014-09-07T23:41:25Z',
                     u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2',
                     u'os-extended-volumes:volumes_attached': [],
                     u'metadata': {u'imported_from_vcenter': u'True',
                                   u'vmware_uuid': u'50373b8e-cc23-80ed-538d-8834621806fb'}})

    instances = []
    for inst in instdata:
        i = Resource(object(), inst)
        instances.append(i)
    return instances


def build_mongodb_instances():
    instdata = \
        [
            {"OS-EXT-STS:task_state": None, "addresses": {"Samnetwork": [{"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:23:0f:ff", "version": 4, "addr": "172.17.17.9", "OS-EXT-IPS:type": "fixed"}, {"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:23:0f:ff", "version": 4, "addr": "192.168.1.229", "OS-EXT-IPS:type": "floating"}]}, "links": [{"href": "http://192.168.1.150:8774/v2/88d70d82f90d4ac792788256210e944e/servers/e0354cfe-a3ae-4801-ac78-34f1cb319d0d", "rel": "self"}, {"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/servers/e0354cfe-a3ae-4801-ac78-34f1cb319d0d", "rel": "bookmark"}], "image": {"id": "82348d2c-b77d-4ae3-9e36-4aaa40f1bc73", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/images/82348d2c-b77d-4ae3-9e36-4aaa40f1bc73", "rel": "bookmark"}]}, "OS-EXT-STS:vm_state": "active", "OS-EXT-SRV-ATTR:instance_name": "instance-00000007", "OS-SRV-USG:launched_at": "2014-09-12T01:37:24.000000", "flavor": {"id": "2", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/flavors/2", "rel": "bookmark"}]}, "id": "e0354cfe-a3ae-4801-ac78-34f1cb319d0d", "security_groups": [{"name": "default"}], "user_id": "acb068e9fa4e426c851633d22202d889", "OS-DCF:diskConfig": "MANUAL", "accessIPv4": "", "accessIPv6": "", "progress": 0, "OS-EXT-STS:power_state": 1, "OS-EXT-AZ:availability_zone": "nova", "config_drive": "", "status": "ACTIVE", "updated": "2014-09-12T01:37:24Z", "hostId": "561e155675cca6f493d88dd8acf85bdf415d7133cbb7c0a402fd4b2a", "OS-EXT-SRV-ATTR:host": "openstack01", "OS-SRV-USG:terminated_at": None, "key_name": "os01", "OS-EXT-SRV-ATTR:hypervisor_hostname": "openstack01", "name": "mongodb3", "created": "2014-09-12T01:37:17Z", "tenant_id": "d04f28ada9f94d09b3ca0965c3411dc7", "os-extended-volumes:volumes_attached": [], "metadata": {}
             },
            {"OS-EXT-STS:task_state": None, "addresses": {"Samnetwork": [{"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:e3:97:ec", "version": 4, "addr": "172.17.17.8", "OS-EXT-IPS:type": "fixed"}, {"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:e3:97:ec", "version": 4, "addr": "192.168.1.228", "OS-EXT-IPS:type": "floating"}]}, "links": [{"href": "http://192.168.1.150:8774/v2/88d70d82f90d4ac792788256210e944e/servers/204fa447-9ae0-4b04-9c6a-bd40e4e75b72", "rel": "self"}, {"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/servers/204fa447-9ae0-4b04-9c6a-bd40e4e75b72", "rel": "bookmark"}], "image": {"id": "4e8cb371-3b1f-454c-a5f5-dc76e186f58f", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/images/4e8cb371-3b1f-454c-a5f5-dc76e186f58f", "rel": "bookmark"}]}, "OS-EXT-STS:vm_state": "active", "OS-EXT-SRV-ATTR:instance_name": "instance-00000006", "OS-SRV-USG:launched_at": "2014-09-12T01:37:08.000000", "flavor": {"id": "2", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/flavors/2", "rel": "bookmark"}]}, "id": "204fa447-9ae0-4b04-9c6a-bd40e4e75b72", "security_groups": [{"name": "default"}], "user_id": "acb068e9fa4e426c851633d22202d889", "OS-DCF:diskConfig": "MANUAL", "accessIPv4": "", "accessIPv6": "", "progress": 0, "OS-EXT-STS:power_state": 1, "OS-EXT-AZ:availability_zone": "nova", "config_drive": "", "status": "ACTIVE", "updated": "2014-09-12T01:37:08Z", "hostId": "561e155675cca6f493d88dd8acf85bdf415d7133cbb7c0a402fd4b2a", "OS-EXT-SRV-ATTR:host": "openstack01", "OS-SRV-USG:terminated_at": None, "key_name": "os01", "OS-EXT-SRV-ATTR:hypervisor_hostname": "openstack01", "name": "mongodb2", "created": "2014-09-12T01:37:00Z", "tenant_id": "d04f28ada9f94d09b3ca0965c3411dc7", "os-extended-volumes:volumes_attached": [], "metadata": {}
             },
            {"OS-EXT-STS:task_state": None, "addresses": {"Samnetwork": [{"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:5b:9b:bb", "version": 4, "addr": "172.17.17.7", "OS-EXT-IPS:type": "fixed"}, {"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:5b:9b:bb", "version": 4, "addr": "192.168.1.227", "OS-EXT-IPS:type": "floating"}]}, "links": [{"href": "http://192.168.1.150:8774/v2/88d70d82f90d4ac792788256210e944e/servers/57a73841-f78b-44a9-a39c-dcec805ba677", "rel": "self"}, {"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/servers/57a73841-f78b-44a9-a39c-dcec805ba677", "rel": "bookmark"}], "image": {"id": "78f8d580-9310-4e7f-9fde-3032f59b2997", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/images/78f8d580-9310-4e7f-9fde-3032f59b2997", "rel": "bookmark"}]}, "OS-EXT-STS:vm_state": "active", "OS-EXT-SRV-ATTR:instance_name": "instance-00000005", "OS-SRV-USG:launched_at": "2014-09-12T01:36:47.000000", "flavor": {"id": "2", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/flavors/2", "rel": "bookmark"}]}, "id": "57a73841-f78b-44a9-a39c-dcec805ba677", "security_groups": [{"name": "default"}], "user_id": "acb068e9fa4e426c851633d22202d889", "OS-DCF:diskConfig": "MANUAL", "accessIPv4": "", "accessIPv6": "", "progress": 0, "OS-EXT-STS:power_state": 1, "OS-EXT-AZ:availability_zone": "nova", "config_drive": "", "status": "ACTIVE", "updated": "2014-09-12T01:36:47Z", "hostId": "561e155675cca6f493d88dd8acf85bdf415d7133cbb7c0a402fd4b2a", "OS-EXT-SRV-ATTR:host": "openstack01", "OS-SRV-USG:terminated_at": None, "key_name": "os01", "OS-EXT-SRV-ATTR:hypervisor_hostname": "openstack01", "name": "mongodb1", "created": "2014-09-12T01:36:42Z", "tenant_id": "d04f28ada9f94d09b3ca0965c3411dc7", "os-extended-volumes:volumes_attached": [], "metadata": {}
             },
            {"OS-EXT-STS:task_state": None, "addresses": {"Samnetwork": [{"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:7c:0f:ae", "version": 4, "addr": "172.17.17.6", "OS-EXT-IPS:type": "fixed"}, {"OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:7c:0f:ae", "version": 4, "addr": "192.168.1.230", "OS-EXT-IPS:type": "floating"}]}, "links": [{"href": "http://192.168.1.150:8774/v2/88d70d82f90d4ac792788256210e944e/servers/343e7249-1cf6-4a1f-a3c1-8e4da48e18ba", "rel": "self"}, {"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/servers/343e7249-1cf6-4a1f-a3c1-8e4da48e18ba", "rel": "bookmark"}], "image": {"id": "e86a41de-6682-4da4-acff-bf4091b03ee6", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/images/e86a41de-6682-4da4-acff-bf4091b03ee6", "rel": "bookmark"}]}, "OS-EXT-STS:vm_state": "active", "OS-EXT-SRV-ATTR:instance_name": "instance-00000004", "OS-SRV-USG:launched_at": "2014-09-12T01:29:31.000000", "flavor": {"id": "2", "links": [{"href": "http://192.168.1.150:8774/88d70d82f90d4ac792788256210e944e/flavors/2", "rel": "bookmark"}]}, "id": "343e7249-1cf6-4a1f-a3c1-8e4da48e18ba", "security_groups": [{"name": "default"}], "user_id": "acb068e9fa4e426c851633d22202d889", "OS-DCF:diskConfig": "MANUAL", "accessIPv4": "", "accessIPv6": "", "progress": 0, "OS-EXT-STS:power_state": 1, "OS-EXT-AZ:availability_zone": "nova", "config_drive": "", "status": "ACTIVE", "updated": "2014-09-12T01:29:31Z", "hostId": "561e155675cca6f493d88dd8acf85bdf415d7133cbb7c0a402fd4b2a", "OS-EXT-SRV-ATTR:host": "openstack01", "OS-SRV-USG:terminated_at": None, "key_name": "os01", "OS-EXT-SRV-ATTR:hypervisor_hostname": "openstack01", "name": "mongodb4", "created": "2014-09-12T01:23:06Z", "tenant_id": "d04f28ada9f94d09b3ca0965c3411dc7", "os-extended-volumes:volumes_attached": [], "metadata": {}
             }
        ]

    instances = []
    for inst in instdata:
        i = Resource(object(), inst)
        instances.append(i)
    return instances


def build_mongodb_hypervisors():
    hvdata = []
    hvdata.append({"service": {"host": "openstack01", "id": 2}, "vcpus_used": 4, "hypervisor_type": "QEMU", "local_gb_used": 80, "hypervisor_hostname": "openstack01", "id": 1, "memory_mb": 16049, "current_workload": 0, "vcpus": 8, "free_ram_mb": 7345, "running_vms": 4, "free_disk_gb": 362, "hypervisor_version": 1004000, "disk_available_least": 226, "local_gb": 442,
                   "cpu_info": "{\"vendor\": \"Intel\", \"model\": \"Penryn\", \"arch\": \"x86_64\", \"features\": [\"osxsave\", \"xsave\", \"dca\", \"pdcm\", \"xtpr\", \"tm2\", \"est\", \"vmx\", \"ds_cpl\", \"monitor\", \"dtes64\", \"pbe\", \"tm\", \"ht\", \"ss\", \"acpi\", \"ds\", \"vme\"], \"topology\": {\"cores\": 4, \"threads\": 1, \"sockets\": 2}}", "memory_mb_used": 8704})
    hypervisors = []
    for hv in hvdata:
        i = Resource(object(), hv)
        hypervisors.append(i)
    return hypervisors


def build_hypervisors():
    hvdata = []
    hvdata.append(
        {
            u'service': {
                u'host': u'cloudvault1',
                u'id': 5},
            u'vcpus_used': 11,
            u'hypervisor_type': u'VMware vCenter Server',
            u'local_gb_used': 164,
            u'hypervisor_hostname': u'domain-c7(OSCluster)',
            u'id': 1,
            u'memory_mb': 13447,
            u'current_workload': 0,
            u'vcpus': 8,
            u'free_ram_mb': -3449,
            u'running_vms': 7,
            u'free_disk_gb': -28,
            u'hypervisor_version': 5005000,
            u'disk_available_least': None,
            u'local_gb': 136,
            u'cpu_info': u'{"model": ["Intel(R) Xeon(R) CPU           L5420  @ 2.50GHz"], "vendor": ["Dell"], "topology": {"cores": 8, "threads": 8}}',
            u'memory_mb_used': 16896})

    hypervisors = []
    for hv in hvdata:
        i = Resource(object(), hv)
        hypervisors.append(i)
    return hypervisors


def get_instances():
    instances = [{u'instance-id': u'4f92587b-cf3a-462a-89d4-0f5634293477', u'vm_id': u'4f92587b-cf3a-462a-89d4-0f5634293477', 'instance-name': 'vm1'},
                 {u'instance-id': u'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                  u'vm_id': u'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                  'instance-name': 'vm2'},
                 {u'instance-id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                  u'vm_id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                  'instance-name': 'vm3'},
                 {u'instance-id': u'1b3a8734-b476-49f9-a959-ea909026b25f',
                  u'vm_id': u'1b3a8734-b476-49f9-a959-ea909026b25f',
                  'instance-name': 'vm4'},
                 {u'instance-id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', u'vm_id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42', 'instance-name': 'vm5'}]
    return instances


def get_restore_options():
    return {u'description': u'Restore one day old snapshot',
            u'name': u'TestRestore',
            u'oneclickrestore': False,
            u'restore_type': 'selective',
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


def get_vms(cntx, admin=False):
    vms = []
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:12:2a:d8',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.18',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477',
                                    u'rel': u'bookmark'}],
                         'image': u'',
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-00000010',
                         'OS-SRV-USG:launched_at': u'2016-11-29T03:00:46.000000',
                         'flavor': {u'id': u'42',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                u'rel': u'bookmark'}]},
                         'id': u'4f92587b-cf3a-462a-89d4-0f5634293477',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'MANUAL',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-29T03:02:24Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'bootvol',
                         'created': u'2016-11-29T03:00:37Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [{u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:12:2a:d8',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.18',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/4f92587b-cf3a-462a-89d4-0f5634293477',
                                               u'rel': u'bookmark'}],
                                   u'image': u'',
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000010',
                                   u'OS-SRV-USG:launched_at': u'2016-11-29T03:00:46.000000',
                                   u'flavor': {u'id': u'42',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'4f92587b-cf3a-462a-89d4-0f5634293477',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'MANUAL',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-29T03:02:24Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'bootvol',
                                   u'created': u'2016-11-29T03:00:37Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [{u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}],
                                   u'metadata': {}},
                         'metadata': {},
                         '_loaded': True}))

    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:58:7f:b0',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.17',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                                    u'rel': u'bookmark'}],
                         'image': u'',
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000f',
                         'OS-SRV-USG:launched_at': u'2016-11-29T02:49:26.000000',
                         'flavor': {u'id': u'42',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                u'rel': u'bookmark'}]},
                         'id': u'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'MANUAL',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-29T02:50:48Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'bootvol-restored',
                         'created': u'2016-11-29T02:49:16Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [{u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:58:7f:b0',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.17',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                                               u'rel': u'bookmark'}],
                                   u'image': u'',
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000f',
                                   u'OS-SRV-USG:launched_at': u'2016-11-29T02:49:26.000000',
                                   u'flavor': {u'id': u'42',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'a0635eb1-7a88-46d0-8c90-fe5b3a4b0132',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'MANUAL',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-29T02:50:48Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'bootvol-restored',
                                   u'created': u'2016-11-29T02:49:16Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [{u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}],
                                   u'metadata': {}},
                         'metadata': {},
                         '_loaded': True}))

    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6c:06:03',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.16',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991',
                                    u'rel': u'bookmark'}],
                         'image': u'',
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000e',
                         'OS-SRV-USG:launched_at': u'2016-11-29T02:45:32.000000',
                         'flavor': {u'id': u'42',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                u'rel': u'bookmark'}]},
                         'id': u'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-29T02:45:32Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'bootvol',
                         'created': u'2016-11-29T02:45:10Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [{u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6c:06:03',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.16',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/dc35b6fe-38fb-46d2-bdfb-c9cee76f3991',
                                               u'rel': u'bookmark'}],
                                   u'image': u'',
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000e',
                                   u'OS-SRV-USG:launched_at': u'2016-11-29T02:45:32.000000',
                                   u'flavor': {u'id': u'42',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'dc35b6fe-38fb-46d2-bdfb-c9cee76f3991',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-29T02:45:32Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'bootvol',
                                   u'created': u'2016-11-29T02:45:10Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [{u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}],
                                   u'metadata': {u'workload_id': u'62ca7590-11eb-481f-9197-7a2572fc73ed',
                                                 u'workload_name': u'bootvol'}},
                         'metadata': {u'workload_id': u'62ca7590-11eb-481f-9197-7a2572fc73ed',
                                      u'workload_name': u'bootvol'},
                         '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:e5:ff:94',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.14',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797',
                                    u'rel': u'bookmark'}],
                         'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                   u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                               u'rel': u'bookmark'}]},
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000d',
                         'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                         'flavor': {u'id': u'1',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                u'rel': u'bookmark'}]},
                         'id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-26T08:26:09Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'vm-4',
                         'created': u'2016-11-26T08:25:56Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:e5:ff:94',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.14',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/d4e6e988-21ca-497e-940a-7b2f36426797',
                                               u'rel': u'bookmark'}],
                                   u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                                          u'rel': u'bookmark'}]},
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000d',
                                   u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                                   u'flavor': {u'id': u'1',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-26T08:26:09Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'vm-4',
                                   u'created': u'2016-11-26T08:25:56Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [],
                                   u'metadata': {}},
                         'metadata': {},
                         '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:64:ad:9c',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.13',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f',
                                    u'rel': u'bookmark'}],
                         'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                   u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                               u'rel': u'bookmark'}]},
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000c',
                         'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                         'flavor': {u'id': u'1',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                u'rel': u'bookmark'}]},
                         'id': u'1b3a8734-b476-49f9-a959-ea909026b25f',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-26T08:26:09Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'vm-3',
                         'created': u'2016-11-26T08:25:56Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:64:ad:9c',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.13',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/1b3a8734-b476-49f9-a959-ea909026b25f',
                                               u'rel': u'bookmark'}],
                                   u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                                          u'rel': u'bookmark'}]},
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000c',
                                   u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                                   u'flavor': {u'id': u'1',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'1b3a8734-b476-49f9-a959-ea909026b25f',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-26T08:26:09Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'vm-3',
                                   u'created': u'2016-11-26T08:25:56Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [],
                                   u'metadata': {}},
                         'metadata': {},
                         '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:3d:27:b3',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.15',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42',
                                    u'rel': u'bookmark'}],
                         'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                   u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                               u'rel': u'bookmark'}]},
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000b',
                         'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                         'flavor': {u'id': u'1',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                u'rel': u'bookmark'}]},
                         'id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-26T08:26:09Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'vm-2',
                         'created': u'2016-11-26T08:25:55Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:3d:27:b3',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.15',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/9634ba8c-8d4f-49cb-9b6f-6b915c09fe42',
                                               u'rel': u'bookmark'}],
                                   u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                                          u'rel': u'bookmark'}]},
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000b',
                                   u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                                   u'flavor': {u'id': u'1',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'9634ba8c-8d4f-49cb-9b6f-6b915c09fe42',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-26T08:26:09Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'vm-2',
                                   u'created': u'2016-11-26T08:25:55Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [],
                                   u'metadata': {}},
                         'metadata': {},
                         '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:b4:80:be',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.12',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d',
                                    u'rel': u'bookmark'}],
                         'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                   u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                               u'rel': u'bookmark'}]},
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000a',
                         'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                         'flavor': {u'id': u'1',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                u'rel': u'bookmark'}]},
                         'id': u'2b2e372e-ba6f-4bbd-8a8c-522de89c391d',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-26T08:26:09Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'vm-1',
                         'created': u'2016-11-26T08:25:55Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:b4:80:be',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.12',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/2b2e372e-ba6f-4bbd-8a8c-522de89c391d',
                                               u'rel': u'bookmark'}],
                                   u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                                          u'rel': u'bookmark'}]},
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-0000000a',
                                   u'OS-SRV-USG:launched_at': u'2016-11-26T08:26:08.000000',
                                   u'flavor': {u'id': u'1',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'2b2e372e-ba6f-4bbd-8a8c-522de89c391d',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-26T08:26:09Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'vm-1',
                                   u'created': u'2016-11-26T08:25:55Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [],
                                   u'metadata': {u'workload_id': u'7256e3a4-4326-4042-85c6-adc41b7e6f60',
                                                 u'workload_name': u'vm3'}},
                         'metadata': {u'workload_id': u'7256e3a4-4326-4042-85c6-adc41b7e6f60',
                                      u'workload_name': u'vm3'},
                         '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6b:4e:38',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.11',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21',
                                    u'rel': u'bookmark'}],
                         'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                   u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                               u'rel': u'bookmark'}]},
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-00000009',
                         'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000',
                         'flavor': {u'id': u'1',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                u'rel': u'bookmark'}]},
                         'id': u'275f9587-dfdf-457a-9926-0f21e9c1eb21',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-26T08:22:55Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'vm-2',
                         'created': u'2016-11-26T08:22:22Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:6b:4e:38',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.11',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/275f9587-dfdf-457a-9926-0f21e9c1eb21',
                                               u'rel': u'bookmark'}],
                                   u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                                          u'rel': u'bookmark'}]},
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000009',
                                   u'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000',
                                   u'flavor': {u'id': u'1',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'275f9587-dfdf-457a-9926-0f21e9c1eb21',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-26T08:22:55Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'vm-2',
                                   u'created': u'2016-11-26T08:22:22Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [],
                                   u'metadata': {u'workload_id': u'c173d256-0d01-45dc-b6db-c3454cf0c30f',
                                                 u'workload_name': u'vm2'}},
                         'metadata': {u'workload_id': u'c173d256-0d01-45dc-b6db-c3454cf0c30f',
                                      u'workload_name': u'vm2'},
                         '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:1e:77:4c',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.10',
                                                     u'OS-EXT-IPS:type': u'fixed'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b',
                                    u'rel': u'bookmark'}],
                         'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                   u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                               u'rel': u'bookmark'}]},
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-00000008',
                         'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000',
                         'flavor': {u'id': u'1',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                u'rel': u'bookmark'}]},
                         'id': u'aef3fbf0-e621-459e-8237-12ac9254411b',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-26T08:22:55Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'vm-1',
                         'created': u'2016-11-26T08:22:21Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:1e:77:4c',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.10',
                                                                u'OS-EXT-IPS:type': u'fixed'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/aef3fbf0-e621-459e-8237-12ac9254411b',
                                               u'rel': u'bookmark'}],
                                   u'image': {u'id': u'cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/cc72d01b-6d9d-4d06-b3e4-c97978ce0257',
                                                          u'rel': u'bookmark'}]},
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000008',
                                   u'OS-SRV-USG:launched_at': u'2016-11-26T08:22:55.000000',
                                   u'flavor': {u'id': u'1',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'aef3fbf0-e621-459e-8237-12ac9254411b',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-26T08:22:55Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'vm-1',
                                   u'created': u'2016-11-26T08:22:21Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [],
                                   u'metadata': {u'workload_id': u'4672d6bb-abc1-4a72-b0b7-cc0791bfa221',
                                                 u'workload_name': u'vm1'}},
                         'metadata': {u'workload_id': u'4672d6bb-abc1-4a72-b0b7-cc0791bfa221',
                                      u'workload_name': u'vm1'},
                         '_loaded': True}))
    vms.append(bunchify({'OS-EXT-STS:task_state': None,
                         'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                                     u'version': 4,
                                                     u'addr': u'10.0.0.7',
                                                     u'OS-EXT-IPS:type': u'fixed'},
                                                    {u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                                     u'version': 4,
                                                     u'addr': u'172.24.4.3',
                                                     u'OS-EXT-IPS:type': u'floating'}]},
                         'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                                    u'rel': u'self'},
                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                                    u'rel': u'bookmark'}],
                         'image': {u'id': u'31e3a8ba-d377-4024-aa84-204f5c4099e7',
                                   u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/31e3a8ba-d377-4024-aa84-204f5c4099e7',
                                               u'rel': u'bookmark'}]},
                         'manager': 'servermanager',
                         'OS-EXT-STS:vm_state': u'active',
                         'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005',
                         'OS-SRV-USG:launched_at': u'2016-11-22T05:10:57.000000',
                         'flavor': {u'id': u'3',
                                    u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/3',
                                                u'rel': u'bookmark'}]},
                         'id': u'28b734f3-4f25-4626-9155-c2d7bddabf3f',
                         'security_groups': [{u'name': u'default'}],
                         'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                         'OS-DCF:diskConfig': u'AUTO',
                         'accessIPv4': u'',
                         'accessIPv6': u'',
                         'progress': 0,
                         'OS-EXT-STS:power_state': 1,
                         'OS-EXT-AZ:availability_zone': u'nova',
                         'config_drive': u'',
                         'status': u'ACTIVE',
                         'updated': u'2016-11-23T22:50:47Z',
                         'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                         'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                         'OS-SRV-USG:terminated_at': None,
                         'key_name': u'kilocontroller',
                         'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                         'name': u'windows',
                         'created': u'2016-11-22T04:51:50Z',
                         'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                         'os-extended-volumes:volumes_attached': [],
                         '_info': {u'OS-EXT-STS:task_state': None,
                                   u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                                                u'version': 4,
                                                                u'addr': u'10.0.0.7',
                                                                u'OS-EXT-IPS:type': u'fixed'},
                                                               {u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                                                u'version': 4,
                                                                u'addr': u'172.24.4.3',
                                                                u'OS-EXT-IPS:type': u'floating'}]},
                                   u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                                               u'rel': u'self'},
                                              {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                                               u'rel': u'bookmark'}],
                                   u'image': {u'id': u'31e3a8ba-d377-4024-aa84-204f5c4099e7',
                                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/31e3a8ba-d377-4024-aa84-204f5c4099e7',
                                                          u'rel': u'bookmark'}]},
                                   u'OS-EXT-STS:vm_state': u'active',
                                   u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005',
                                   u'OS-SRV-USG:launched_at': u'2016-11-22T05:10:57.000000',
                                   u'flavor': {u'id': u'3',
                                               u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/3',
                                                           u'rel': u'bookmark'}]},
                                   u'id': u'28b734f3-4f25-4626-9155-c2d7bddabf3f',
                                   u'security_groups': [{u'name': u'default'}],
                                   u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                                   u'OS-DCF:diskConfig': u'AUTO',
                                   u'accessIPv4': u'',
                                   u'accessIPv6': u'',
                                   u'progress': 0,
                                   u'OS-EXT-STS:power_state': 1,
                                   u'OS-EXT-AZ:availability_zone': u'nova',
                                   u'config_drive': u'',
                                   u'status': u'ACTIVE',
                                   u'updated': u'2016-11-23T22:50:47Z',
                                   u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                                   u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                                   u'OS-SRV-USG:terminated_at': None,
                                   u'key_name': u'kilocontroller',
                                   u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                                   u'name': u'windows',
                                   u'created': u'2016-11-22T04:51:50Z',
                                   u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                   u'os-extended-volumes:volumes_attached': [],
                                   u'metadata': {u'workload_id': u'dea51ebc-e0de-4032-b10c-1faceb4592d2',
                                                 u'workload_name': u'wlm1'}},
                         'metadata': {u'workload_id': u'dea51ebc-e0de-4032-b10c-1faceb4592d2',
                                      u'workload_name': u'wlm1'},
                         '_loaded': True}))
    return vms


def get_server_by_id(context, vm_id, admin=False):
    vms = get_vms(context)
    for vm in vms:
        if vm.id == vm_id:
            return vm

    vm = bunchify({'OS-EXT-STS:task_state': None,
                   'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                               u'version': 4,
                                               u'addr': u'10.0.0.7',
                                               u'OS-EXT-IPS:type': u'fixed'},
                                              {u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                               u'version': 4,
                                               u'addr': u'172.24.4.3',
                                               u'OS-EXT-IPS:type': u'floating'}]},
                   'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                              u'rel': u'self'},
                             {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                              u'rel': u'bookmark'}],
                   'image': {u'id': u'31e3a8ba-d377-4024-aa84-204f5c4099e7',
                             u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/31e3a8ba-d377-4024-aa84-204f5c4099e7',
                                         u'rel': u'bookmark'}]},
                   'manager': 'servermanager',
                   'OS-EXT-STS:vm_state': u'active',
                   'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005',
                   'OS-SRV-USG:launched_at': u'2016-11-22T05:10:57.000000',
                   'flavor': {u'id': u'3',
                              u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/3',
                                          u'rel': u'bookmark'}]},
                   'id': vm_id,
                   'security_groups': [{u'name': u'default'}],
                   'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                   'OS-DCF:diskConfig': u'AUTO',
                   'accessIPv4': u'',
                   'accessIPv6': u'',
                   'progress': 0,
                   'OS-EXT-STS:power_state': 1,
                   'OS-EXT-AZ:availability_zone': u'nova',
                   'config_drive': u'',
                   'status': u'ACTIVE',
                   'updated': u'2016-11-23T22:50:47Z',
                   'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                   'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                   'OS-SRV-USG:terminated_at': None,
                   'key_name': u'kilocontroller',
                   'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                   'name': u'windows',
                   'created': u'2016-11-22T04:51:50Z',
                   'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                   'os-extended-volumes:volumes_attached': [],
                   '_info': {u'OS-EXT-STS:task_state': None,
                             u'addresses': {u'private': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                                          u'version': 4,
                                                          u'addr': u'10.0.0.7',
                                                          u'OS-EXT-IPS:type': u'fixed'},
                                                         {u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:04:9f:2b',
                                                          u'version': 4,
                                                          u'addr': u'172.24.4.3',
                                                          u'OS-EXT-IPS:type': u'floating'}]},
                             u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                                         u'rel': u'self'},
                                        {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/servers/28b734f3-4f25-4626-9155-c2d7bddabf3f',
                                         u'rel': u'bookmark'}],
                             u'image': {u'id': u'31e3a8ba-d377-4024-aa84-204f5c4099e7',
                                        u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/images/31e3a8ba-d377-4024-aa84-204f5c4099e7',
                                                    u'rel': u'bookmark'}]},
                             u'OS-EXT-STS:vm_state': u'active',
                             u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005',
                             u'OS-SRV-USG:launched_at': u'2016-11-22T05:10:57.000000',
                             u'flavor': {u'id': u'3',
                                         u'links': [{u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/3',
                                                     u'rel': u'bookmark'}]},
                             u'id': u'28b734f3-4f25-4626-9155-c2d7bddabf3f',
                             u'security_groups': [{u'name': u'default'}],
                             u'user_id': u'e6e3159d1d3d4622befa70dd745af289',
                             u'OS-DCF:diskConfig': u'AUTO',
                             u'accessIPv4': u'',
                             u'accessIPv6': u'',
                             u'progress': 0,
                             u'OS-EXT-STS:power_state': 1,
                             u'OS-EXT-AZ:availability_zone': u'nova',
                             u'config_drive': u'',
                             u'status': u'ACTIVE',
                             u'updated': u'2016-11-23T22:50:47Z',
                             u'hostId': u'39f3f43d9ec6267bcc27b25e56ef12707c469b9c50cdcaf0813f2452',
                             u'OS-EXT-SRV-ATTR:host': u'kilocontroller',
                             u'OS-SRV-USG:terminated_at': None,
                             u'key_name': u'kilocontroller',
                             u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'kilocontroller',
                             u'name': u'windows',
                             u'created': u'2016-11-22T04:51:50Z',
                             u'tenant_id': u'000d038df75743a88cefaacd9b704b94',
                             u'os-extended-volumes:volumes_attached': [],
                             u'metadata': {u'workload_id': u'dea51ebc-e0de-4032-b10c-1faceb4592d2',
                                           u'workload_name': u'wlm1'}},
                   'metadata': {u'workload_id': u'dea51ebc-e0de-4032-b10c-1faceb4592d2',
                                u'workload_name': u'wlm1'},
                   '_loaded': True})
    return vm


def get_flavors(context):
    flavors = {}

    flavors['1'] = bunchify({'name': u'm1.tiny',
                             'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/1',
                                        u'rel': u'self'},
                                       {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                        u'rel': u'bookmark'}],
                             'ram': 512,
                             'vcpus': 1,
                             'id': u'1',
                             'OS-FLV-DISABLED:disabled': False,
                             'manager': 'FlavorManager',
                             'swap': u'0',
                             'os-flavor-access:is_public': True,
                             'rxtx_factor': 1.0,
                             '_info': {u'name': u'm1.tiny',
                                       u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                   u'rel': u'self'},
                                                  {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/1',
                                                   u'rel': u'bookmark'}],
                                       u'ram': 512,
                                       u'OS-FLV-DISABLED:disabled': False,
                                       u'vcpus': 1,
                                       u'swap': u'0',
                                       u'os-flavor-access:is_public': True,
                                       u'rxtx_factor': 1.0,
                                       u'OS-FLV-EXT-DATA:ephemeral': 0,
                                       u'disk': 1,
                                       u'id': u'1'},
                             'disk': 1,
                             'ephemeral': 0,
                             'OS-FLV-EXT-DATA:ephemeral': 0,
                             '_loaded': True})

    flavors['42'] = bunchify({'name': u'm1.tiny',
                              'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/42',
                                         u'rel': u'self'},
                                        {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                         u'rel': u'bookmark'}],
                              'ram': 8192,
                              'vcpus': 4,
                              'id': u'42',
                              'OS-FLV-DISABLED:disabled': False,
                              'manager': 'FlavorManager',
                              'swap': u'0',
                              'os-flavor-access:is_public': True,
                              'rxtx_factor': 1.0,
                              '_info': {u'name': u'm1.medium',
                                        u'links': [{u'href': u'http://192.168.1.106:8774/v2/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                    u'rel': u'self'},
                                                   {u'href': u'http://192.168.1.106:8774/000d038df75743a88cefaacd9b704b94/flavors/42',
                                                    u'rel': u'bookmark'}],
                                        u'ram': 8192,
                                        u'OS-FLV-DISABLED:disabled': False,
                                        u'vcpus': 4,
                                        u'swap': u'0',
                                        u'os-flavor-access:is_public': True,
                                        u'rxtx_factor': 1.0,
                                        u'OS-FLV-EXT-DATA:ephemeral': 0,
                                        u'disk': 40,
                                        u'id': u'1'},
                              'disk': 40,
                              'ephemeral': 0,
                              'OS-FLV-EXT-DATA:ephemeral': 0,
                              '_loaded': True})

    return flavors


def get_flavor_by_id(context, id):
    return get_flavors(context)[id]


def get_flavors_for_test(context):
    return get_flavors(context).values()


def get_volume_id(context, id, no_translate=True):
    volumes = {}
    volumes['b07c8751-f475-4f4c-94e7-72733f256b0b'] = bunchify(
        {
            'attachments': [
                {
                    u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                    u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                    u'host_name': None,
                    u'volume_id': u'b07c8751-f475-4f4c-94e7-72733f256b0b',
                    u'device': u'/dev/vdb',
                    u'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b'}],
            'availability_zone': u'nova',
            'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
            'encrypted': False,
            'os-volume-replication:extended_status': None,
            'manager': 'VolumeManager',
            'os-volume-replication:driver_data': None,
            'snapshot_id': None,
            'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b',
            'size': 20,
            'display_name': u'vol2',
            'display_description': None,
            'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
            'os-vol-mig-status-attr:migstat': None,
            'metadata': {
                u'readonly': u'False',
                u'attached_mode': u'rw'},
            'status': u'in-use',
            'multiattach': u'false',
            'source_volid': None,
            'os-vol-mig-status-attr:name_id': None,
            'bootable': u'false',
            'created_at': u'2016-12-02T15:43:09.000000',
            'volume_type': u'ceph',
            '_info': {
                        u'status': u'in-use',
                        u'display_name': u'vol2',
                        u'attachments': [
                            {
                                u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                                u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                                u'host_name': None,
                                u'volume_id': u'b07c8751-f475-4f4c-94e7-72733f256b0b',
                                u'device': u'/dev/vdb',
                                u'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b'}],
                u'availability_zone': u'nova',
                u'bootable': u'false',
                u'encrypted': False,
                u'created_at': u'2016-12-02T15:43:09.000000',
                u'multiattach': u'false',
                                u'os-vol-mig-status-attr:migstat': None,
                                u'os-volume-replication:driver_data': None,
                                u'os-volume-replication:extended_status': None,
                                u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
                                u'snapshot_id': None,
                                u'display_description': None,
                                u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                u'source_volid': None,
                                u'id': u'b07c8751-f475-4f4c-94e7-72733f256b0b',
                                u'size': 20,
                                u'volume_type': u'ceph',
                                u'os-vol-mig-status-attr:name_id': None,
                                u'metadata': {
                                    u'readonly': u'False',
                                    u'attached_mode': u'rw'}},
            '_loaded': True})

    volumes['c16006a6-60fe-4046-9eb0-35e37fe3e3f4'] = bunchify(
        {
            'attachments': [
                {
                    u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                    u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                    u'host_name': None,
                    u'volume_id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4',
                    u'device': u'/dev/vdb',
                    u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}],
            'availability_zone': u'nova',
            'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
            'encrypted': False,
            'os-volume-replication:extended_status': None,
            'manager': 'VolumeManager',
            'os-volume-replication:driver_data': None,
            'snapshot_id': None,
            'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4',
            'size': 40,
            'display_name': u'vol2',
            'display_description': None,
            'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
            'os-vol-mig-status-attr:migstat': None,
            'metadata': {
                u'readonly': u'False',
                u'attached_mode': u'rw'},
            'status': u'in-use',
            'multiattach': u'false',
            'source_volid': None,
            'os-vol-mig-status-attr:name_id': None,
            'bootable': u'false',
            'created_at': u'2016-12-02T15:43:09.000000',
            'volume_type': u'ceph',
            '_info': {
                        u'status': u'in-use',
                        u'display_name': u'vol2',
                        u'attachments': [
                            {
                                u'server_id': u'd4e6e988-21ca-497e-940a-7b2f36426797',
                                u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                                u'host_name': None,
                                u'volume_id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4',
                                u'device': u'/dev/vdb',
                                u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4'}],
                u'availability_zone': u'nova',
                u'bootable': u'false',
                u'encrypted': False,
                u'created_at': u'2016-12-02T15:43:09.000000',
                u'multiattach': u'false',
                                u'os-vol-mig-status-attr:migstat': None,
                                u'os-volume-replication:driver_data': None,
                                u'os-volume-replication:extended_status': None,
                                u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
                                u'snapshot_id': None,
                                u'display_description': None,
                                u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                u'source_volid': None,
                                u'id': u'c16006a6-60fe-4046-9eb0-35e37fe3e3f4',
                                u'size': 40,
                                u'volume_type': u'ceph',
                                u'os-vol-mig-status-attr:name_id': None,
                                u'metadata': {
                                    u'readonly': u'False',
                                    u'attached_mode': u'rw'}},
            '_loaded': True})

    volumes['92ded426-072c-4645-9f3a-72f9a3ad6899'] = bunchify(
        {
            'attachments': [
                {
                    u'server_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899',
                    u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                    u'host_name': None,
                    u'volume_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899',
                    u'device': u'/dev/vdb',
                    u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}],
            'availability_zone': u'nova',
            'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
            'encrypted': False,
            'os-volume-replication:extended_status': None,
            'manager': 'VolumeManager',
            'os-volume-replication:driver_data': None,
            'snapshot_id': None,
            'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899',
            'size': 80,
            'display_name': u'vol2',
            'display_description': None,
            'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
            'os-vol-mig-status-attr:migstat': None,
            'metadata': {
                u'readonly': u'False',
                u'attached_mode': u'rw'},
            'status': u'in-use',
            'multiattach': u'false',
            'source_volid': None,
            'os-vol-mig-status-attr:name_id': None,
            'bootable': u'false',
            'created_at': u'2016-12-02T15:43:09.000000',
            'volume_type': u'ceph',
            '_info': {
                        u'status': u'in-use',
                        u'display_name': u'vol2',
                        u'attachments': [
                            {
                                u'server_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899',
                                u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                                u'host_name': None,
                                u'volume_id': u'92ded426-072c-4645-9f3a-72f9a3ad6899',
                                u'device': u'/dev/vdb',
                                u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899'}],
                u'availability_zone': u'nova',
                u'bootable': u'false',
                u'encrypted': False,
                u'created_at': u'2016-12-02T15:43:09.000000',
                u'multiattach': u'false',
                                u'os-vol-mig-status-attr:migstat': None,
                                u'os-volume-replication:driver_data': None,
                                u'os-volume-replication:extended_status': None,
                                u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
                                u'snapshot_id': None,
                                u'display_description': None,
                                u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                u'source_volid': None,
                                u'id': u'92ded426-072c-4645-9f3a-72f9a3ad6899',
                                u'size': 80,
                                u'volume_type': u'ceph',
                                u'os-vol-mig-status-attr:name_id': None,
                                u'metadata': {
                                    u'readonly': u'False',
                                    u'attached_mode': u'rw'}},
            '_loaded': True})

    volumes['97aafa48-2d2c-4372-85ca-1d9d32cde50e'] = bunchify(
        {
            'attachments': [
                {
                    u'server_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e',
                    u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                    u'host_name': None,
                    u'volume_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e',
                    u'device': u'/dev/vdb',
                    u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}],
            'availability_zone': u'nova',
            'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
            'encrypted': False,
            'os-volume-replication:extended_status': None,
            'manager': 'VolumeManager',
            'os-volume-replication:driver_data': None,
            'snapshot_id': None,
            'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e',
            'size': 160,
            'display_name': u'vol2',
            'display_description': None,
            'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
            'os-vol-mig-status-attr:migstat': None,
            'metadata': {
                u'readonly': u'False',
                u'attached_mode': u'rw'},
            'status': u'in-use',
            'multiattach': u'false',
            'source_volid': None,
            'os-vol-mig-status-attr:name_id': None,
            'bootable': u'false',
            'created_at': u'2016-12-02T15:43:09.000000',
            'volume_type': u'ceph',
            '_info': {
                        u'status': u'in-use',
                        u'display_name': u'vol2',
                        u'attachments': [
                            {
                                u'server_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e',
                                u'attachment_id': u'ca8ce5ab-4b54-4795-9b89-919aa9271042',
                                u'host_name': None,
                                u'volume_id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e',
                                u'device': u'/dev/vdb',
                                u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e'}],
                u'availability_zone': u'nova',
                u'bootable': u'false',
                u'encrypted': False,
                u'created_at': u'2016-12-02T15:43:09.000000',
                u'multiattach': u'false',
                                u'os-vol-mig-status-attr:migstat': None,
                                u'os-volume-replication:driver_data': None,
                                u'os-volume-replication:extended_status': None,
                                u'os-vol-host-attr:host': u'kilocontroller@ceph#ceph',
                                u'snapshot_id': None,
                                u'display_description': None,
                                u'os-vol-tenant-attr:tenant_id': u'000d038df75743a88cefaacd9b704b94',
                                u'source_volid': None,
                                u'id': u'97aafa48-2d2c-4372-85ca-1d9d32cde50e',
                                u'size': 160,
                                u'volume_type': u'ceph',
                                u'os-vol-mig-status-attr:name_id': None,
                                u'metadata': {
                                    u'readonly': u'False',
                                    u'attached_mode': u'rw'}},
            '_loaded': True})

    volumes[id].__dict__ = unbunchify(volumes[id])
    return volumes[id]


def get_glance_image(*args, **kwargs):
    return {'status': u'active', 'name': u'cirros-0.3.4-x86_64-uec', 'deleted': False, 'container_format': u'ami', 'created_at': '2017', 'disk_format': u'ami', 'updated_at': '2017', 'id': u'27d059ff-909e-4a84-9901-2ec62bb5407e', 'owner': u'd79496254ddd476891a5fba637ec100e',
            'min_ram': 0, 'checksum': u'eb9139e4942121f22bbc2afc0400b2a4', 'min_disk': 0, 'is_public': True, 'deleted_at': None, 'properties': {u'kernel_id': u'a873ad90-20d8-421c-99dc-3dbbd0e7721f', u'ramdisk_id': u'6163a31f-f06d-4b22-b30a-f6a13345014d'}, 'size': 25165824}


def _get_interfaces(*args, **kwargs):
    interface = bunchify(
        {
            'fixed_ips': [
                {
                    u'subnet_id': u'39afe48d-3b15-42f8-bdaf-9bf815e7015c',
                    u'ip_address': u'10.0.0.3'}],
            'port_state': u'ACTIVE',
            'manager': 'ServerManager',
            'mac_addr': u'fa:16:3e:7e:c5:88',
            '_info': {
                u'port_state': u'ACTIVE',
                u'port_id': u'f5f1b34e-40de-49a6-a2c4-6d2283630502',
                u'fixed_ips': [
                        {
                            u'subnet_id': u'39afe48d-3b15-42f8-bdaf-9bf815e7015c',
                            u'ip_address': u'10.0.0.3'}],
                u'net_id': u'7e5e75f5-872d-43e9-a00e-b791862d3378',
                u'mac_addr': u'fa:16:3e:7e:c5:88'},
            'port_id': u'f5f1b34e-40de-49a6-a2c4-6d2283630502',
            'net_id': u'7e5e75f5-872d-43e9-a00e-b791862d3378',
            '_loaded': True})
    interfaces = []
    interfaces.append(interface)
    return interfaces


def _port_data(*args, **kwargs):
    return {u'port': {u'status': u'ACTIVE', u'binding:host_id': u'kilocontroller', u'name': u'', u'allowed_address_pairs': [], u'admin_state_up': True, u'network_id': u'7e5e75f5-872d-43e9-a00e-b791862d3378', u'tenant_id': u'4cdf6b19c2644369a5e64277810d8016', u'extra_dhcp_opts': [], u'binding:vif_details': {u'port_filter': True, u'ovs_hybrid_plug': True}, u'binding:vif_type': u'ovs',
                      u'device_owner': u'compute:nova', u'mac_address': u'fa:16:3e:7e:c5:88', u'binding:profile': {}, u'binding:vnic_type': u'normal', u'fixed_ips': [{u'subnet_id': u'39afe48d-3b15-42f8-bdaf-9bf815e7015c', u'ip_address': u'10.0.0.3'}], u'id': u'f5f1b34e-40de-49a6-a2c4-6d2283630502', u'security_groups': [u'2aa7b3e8-ed27-48b8-8fb7-5ba29efe1e6d'], u'device_id': u'18ee5bb3-385d-4e1b-a87b-b60cd626c4f7'}}


def _subnets_data(*args, **kwargs):
    return {'subnets': [{u'name': u'private-subnet', u'enable_dhcp': True, u'network_id': u'7e5e75f5-872d-43e9-a00e-b791862d3378', u'tenant_id': u'4cdf6b19c2644369a5e64277810d8016', u'dns_nameservers': [], u'ipv6_ra_mode': None, u'allocation_pools': [
        {u'start': u'10.0.0.2', u'end': u'10.0.0.254'}], u'gateway_ip': u'10.0.0.1', u'ipv6_address_mode': None, u'ip_version': 4, u'host_routes': [], u'cidr': u'10.0.0.0/24', u'id': u'39afe48d-3b15-42f8-bdaf-9bf815e7015c', u'subnetpool_id': None}]}


def _network(*args, **kwargs):
    return {u'status': u'ACTIVE', u'subnets': [u'39afe48d-3b15-42f8-bdaf-9bf815e7015c'], u'name': u'private', u'provider:physical_network': None, u'router:external': False, u'tenant_id': u'4cdf6b19c2644369a5e64277810d8016',
            u'admin_state_up': True, 'label': u'private', u'mtu': 0, u'shared': False, u'provider:network_type': u'vxlan', u'id': u'7e5e75f5-872d-43e9-a00e-b791862d3378', u'provider:segmentation_id': 1099}


def _routers_data(*args, **kwargs):
    return [{u'status': u'ACTIVE', u'external_gateway_info': {u'network_id': u'4477fb7e-78e7-45fb-9ba0-14ee79f2d97a', u'enable_snat': True, u'external_fixed_ips': [{u'subnet_id': u'2be808b5-2fd6-4883-a611-df527355ba80',
                                                                                                                                                                     u'ip_address': u'172.24.4.2'}]}, u'name': u'router1', u'admin_state_up': True, u'tenant_id': u'4cdf6b19c2644369a5e64277810d8016', u'distributed': False, u'routes': [], u'ha': False, u'id': u'495d3f5e-eb3c-475a-9e96-f6fa16044a1f'}]


def _router_ports(*args, **kwargs):
    return [{u'status': u'ACTIVE', u'binding:host_id': u'kilocontroller', u'name': u'', u'allowed_address_pairs': [], u'admin_state_up': True, u'network_id': u'7e5e75f5-872d-43e9-a00e-b791862d3378', u'tenant_id': u'4cdf6b19c2644369a5e64277810d8016', u'extra_dhcp_opts': [], u'binding:vif_details': {u'port_filter': True, u'ovs_hybrid_plug': True}, u'binding:vif_type': u'ovs',
             u'device_owner': u'network:router_interface', u'mac_address': u'fa:16:3e:d9:55:c3', u'binding:profile': {}, u'binding:vnic_type': u'normal', u'fixed_ips': [{u'subnet_id': u'39afe48d-3b15-42f8-bdaf-9bf815e7015c', u'ip_address': u'10.0.0.1'}], u'id': u'e91aae8b-3259-45d9-b52d-af3a2a2072a2', u'security_groups': [], u'device_id': u'495d3f5e-eb3c-475a-9e96-f6fa16044a1f'}]


def _router_ext_ports(*args, **kwargs):
    return [{u'status': u'ACTIVE', u'binding:host_id': u'kilocontroller', u'name': u'', u'allowed_address_pairs': [], u'admin_state_up': True, u'network_id': u'4477fb7e-78e7-45fb-9ba0-14ee79f2d97a', u'tenant_id': u'', u'extra_dhcp_opts': [], u'binding:vif_details': {u'port_filter': True, u'ovs_hybrid_plug': True}, u'binding:vif_type': u'ovs',
             u'device_owner': u'network:router_gateway', u'mac_address': u'fa:16:3e:7f:2e:ae', u'binding:profile': {}, u'binding:vnic_type': u'normal', u'fixed_ips': [{u'subnet_id': u'2be808b5-2fd6-4883-a611-df527355ba80', u'ip_address': u'172.24.4.2'}], u'id': u'26168992-778b-416b-8253-458c4ff38b1f', u'security_groups': [], u'device_id': u'495d3f5e-eb3c-475a-9e96-f6fa16044a1f'}]


def _ext_subnets_data(*args, **kwargs):
    return {'subnets': [{u'name': u'public-subnet', u'enable_dhcp': False, u'network_id': u'4477fb7e-78e7-45fb-9ba0-14ee79f2d97a', u'tenant_id': u'd79496254ddd476891a5fba637ec100e', u'dns_nameservers': [], u'ipv6_ra_mode': None, u'allocation_pools': [
        {u'start': u'172.24.4.2', u'end': u'172.24.4.254'}], u'gateway_ip': u'172.24.4.1', u'ipv6_address_mode': None, u'ip_version': 4, u'host_routes': [], u'cidr': u'172.24.4.0/24', u'id': u'2be808b5-2fd6-4883-a611-df527355ba80', u'subnetpool_id': None}]}


def _snapshot_data_ex(*args, **kwargs):
    return {u'disks_info': [{u'dev': u'vda', u'snapshot_name': u'triliovault:416620e5-e5f6-40a7-a8ca-f422b9be381b', u'backings': [{u'path': u'rbd:vms/18ee5bb3-385d-4e1b-a87b-b60cd626c4f7_disk', u'size': 1073741824}], u'volume_id': None, u'path': u'rbd:vms/18ee5bb3-385d-4e1b-a87b-b60cd626c4f7_disk', u'size': 1073741824, u'type': u'network', u'backend': u'rbdboot'}, {u'status': u'creating', u'display_name': u'TrilioVaultSnapshot', u'created_at': u'2017-01-20T01:35:50.315882',
                                                                                                                                                                                                                                                                                                                                                                                u'size': 1073741824, u'display_description': u'TrilioVault initiated snapshot', u'volume_size': 1, u'dev': u'vdb', u'backings': [{u'path': u'6847f146-bf45-46f7-9860-0f35734b2f30', u'size': 1073741824}], u'volume_id': u'e24b486e-189d-48a6-aacb-4329e43ce9a1', u'progress': None, u'path': u'volumes/volume-e24b486e-189d-48a6-aacb-4329e43ce9a1', u'project_id': u'4cdf6b19c2644369a5e64277810d8016', u'id': u'6847f146-bf45-46f7-9860-0f35734b2f30', u'backend': u'rbd'}]}


def create_qcow2_image(source, out_format="qcow2",
                       size="1G", run_as_root=False):

    def _mkdir_p(path):
        try:
            os.makedirs(path)
        except OSError as exc:  # Python >2.5
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                raise

    _mkdir_p(os.path.dirname(source))
    cmd = ('qemu-img', 'create', '-f', out_format, source, "1G")
    utils.execute(*cmd, run_as_root=run_as_root)
