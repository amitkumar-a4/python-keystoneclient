# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2014 Trilio Data, Inc


import os
import six

from workloadmgr import context
from workloadmgr import db


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
            #NOTE(bcwaldon): disallow lazy-loading if already loaded once
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
    instdata.append({u'OS-EXT-STS:task_state': None, u'addresses': {u'br-int': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:9f:9d:d3', u'version': 4, u'addr': u'172.17.17.19', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/e44e5170-255d-42fb-a603-89fa171104e1', u'rel': u'self'}, {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/e44e5170-255d-42fb-a603-89fa171104e1', u'rel': u'bookmark'}], u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000007', u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:36.000000', u'flavor': {u'id': u'3f086923-a0ec-4610-8ab4-ccd1d40b73eb', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/3f086923-a0ec-4610-8ab4-ccd1d40b73eb', u'rel': u'bookmark'}]}, u'id': u'e44e5170-255d-42fb-a603-89fa171104e1', u'security_groups': [{u'name': u'default'}], u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763', u'OS-DCF:diskConfig': u'MANUAL', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'tvault_az', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2014-09-07T23:41:36Z', u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b', u'OS-EXT-SRV-ATTR:host': u'cloudvault1', u'OS-SRV-USG:terminated_at': None, u'key_name': None, u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)', u'name': u'd8848b37-1f6a-4a60-9aa5-d7763f710f2a', u'created': u'2014-09-07T23:41:27Z', u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'imported_from_vcenter': u'True', u'vmware_uuid': u'50378ee9-30ec-d38a-9132-4aad1463b168'}})
    instdata.append({u'OS-EXT-STS:task_state': None, u'addresses': {u'br-int': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:87:af:d1', u'version': 4, u'addr': u'172.17.17.21', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/b66be913-9f3e-4adf-9274-4a36e980ff25', u'rel': u'self'}, {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/b66be913-9f3e-4adf-9274-4a36e980ff25', u'rel': u'bookmark'}], u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000006', u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:36.000000', u'flavor': {u'id': u'ab136999-e31e-421f-a6c9-22e9434402c3', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/ab136999-e31e-421f-a6c9-22e9434402c3', u'rel': u'bookmark'}]}, u'id': u'b66be913-9f3e-4adf-9274-4a36e980ff25', u'security_groups': [{u'name': u'default'}], u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763', u'OS-DCF:diskConfig': u'MANUAL', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'tvault_az', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2014-09-07T23:41:37Z', u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b', u'OS-EXT-SRV-ATTR:host': u'cloudvault1', u'OS-SRV-USG:terminated_at': None, u'key_name': None, u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)', u'name': u'testVM', u'created': u'2014-09-07T23:41:27Z', u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'imported_from_vcenter': u'True', u'vmware_uuid': u'50379ef0-13df-6aff-084a-abe9d01047f8'}})
    instdata.append({u'OS-EXT-STS:task_state': None, u'addresses': {u'br100': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:1f:da:be', u'version': 4, u'addr': u'172.17.17.20', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/f6792af5-ffaa-407b-8401-f8246323dedf', u'rel': u'self'}, {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/f6792af5-ffaa-407b-8401-f8246323dedf', u'rel': u'bookmark'}], u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000005', u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:36.000000', u'flavor': {u'id': u'956b96d1-34d7-43a2-8d77-639f14167d02', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/956b96d1-34d7-43a2-8d77-639f14167d02', u'rel': u'bookmark'}]}, u'id': u'f6792af5-ffaa-407b-8401-f8246323dedf', u'security_groups': [{u'name': u'default'}], u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763', u'OS-DCF:diskConfig': u'MANUAL', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'tvault_az', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2014-09-07T23:41:36Z', u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b', u'OS-EXT-SRV-ATTR:host': u'cloudvault1', u'OS-SRV-USG:terminated_at': None, u'key_name': None, u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)', u'name': u'vm1', u'created': u'2014-09-07T23:41:26Z', u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'imported_from_vcenter': u'True', u'vmware_uuid': u'5037bc07-3324-08b4-40ab-40b4edb75076'}})
    instdata.append({u'OS-EXT-STS:task_state': None, u'addresses': {u'dswitch-pg1': [{u'OS-EXT-IPS-MAC:mac_addr': u'fa:16:3e:b2:d1:42', u'version': 4, u'addr': u'172.17.17.22', u'OS-EXT-IPS:type': u'fixed'}]}, u'links': [{u'href': u'http://localhost:8774/v2/4273759bc7414cd8bc4137acfe2a3e2f/servers/144775cc-764b-4af4-99b3-ac6df0cabf98', u'rel': u'self'}, {u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/servers/144775cc-764b-4af4-99b3-ac6df0cabf98', u'rel': u'bookmark'}], u'image': {u'id': u'ac3a8810-be39-4854-9eea-e07a8f49e157', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/images/ac3a8810-be39-4854-9eea-e07a8f49e157', u'rel': u'bookmark'}]}, u'OS-EXT-STS:vm_state': u'active', u'OS-EXT-SRV-ATTR:instance_name': u'instance-00000003', u'OS-SRV-USG:launched_at': u'2014-09-07T23:41:35.000000', u'flavor': {u'id': u'b2681ed4-f520-479c-a92a-8236ff17e0e3', u'links': [{u'href': u'http://localhost:8774/4273759bc7414cd8bc4137acfe2a3e2f/flavors/b2681ed4-f520-479c-a92a-8236ff17e0e3', u'rel': u'bookmark'}]}, u'id': u'144775cc-764b-4af4-99b3-ac6df0cabf98', u'security_groups': [{u'name': u'default'}], u'user_id': u'bc43e7db6dff48ca8818d4c35c9f2763', u'OS-DCF:diskConfig': u'MANUAL', u'accessIPv4': u'', u'accessIPv6': u'', u'progress': 0, u'OS-EXT-STS:power_state': 1, u'OS-EXT-AZ:availability_zone': u'tvault_az', u'config_drive': u'', u'status': u'ACTIVE', u'updated': u'2014-09-07T23:41:35Z', u'hostId': u'94d4e1905b237492ff98a5bab28828a8e7245578c0c6554e73c2628b', u'OS-EXT-SRV-ATTR:host': u'cloudvault1', u'OS-SRV-USG:terminated_at': None, u'key_name': None, u'OS-EXT-SRV-ATTR:hypervisor_hostname': u'domain-c7(OSCluster)', u'name': u'vmware1', u'created': u'2014-09-07T23:41:25Z', u'tenant_id': u'222382a82d844e1184d1bc8344cc54f2', u'os-extended-volumes:volumes_attached': [], u'metadata': {u'imported_from_vcenter': u'True', u'vmware_uuid': u'50373b8e-cc23-80ed-538d-8834621806fb'}})

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
    hvdata.append({"service": {"host": "openstack01", "id": 2}, "vcpus_used": 4, "hypervisor_type": "QEMU", "local_gb_used": 80, "hypervisor_hostname": "openstack01", "id": 1, "memory_mb": 16049, "current_workload": 0, "vcpus": 8, "free_ram_mb": 7345, "running_vms": 4, "free_disk_gb": 362, "hypervisor_version": 1004000, "disk_available_least": 226, "local_gb": 442, "cpu_info": "{\"vendor\": \"Intel\", \"model\": \"Penryn\", \"arch\": \"x86_64\", \"features\": [\"osxsave\", \"xsave\", \"dca\", \"pdcm\", \"xtpr\", \"tm2\", \"est\", \"vmx\", \"ds_cpl\", \"monitor\", \"dtes64\", \"pbe\", \"tm\", \"ht\", \"ss\", \"acpi\", \"ds\", \"vme\"], \"topology\": {\"cores\": 4, \"threads\": 1, \"sockets\": 2}}", "memory_mb_used": 8704})
    hypervisors = []
    for hv in hvdata:
        i = Resource(object(), hv)
        hypervisors.append(i) 
    return hypervisors

def build_hypervisors():
    hvdata = []
    hvdata.append({u'service': {u'host': u'cloudvault1', u'id': 5}, u'vcpus_used': 11, u'hypervisor_type': u'VMware vCenter Server', u'local_gb_used': 164, u'hypervisor_hostname': u'domain-c7(OSCluster)', u'id': 1, u'memory_mb': 13447, u'current_workload': 0, u'vcpus': 8, u'free_ram_mb': -3449, u'running_vms': 7, u'free_disk_gb': -28, u'hypervisor_version': 5005000, u'disk_available_least': None, u'local_gb': 136, u'cpu_info': u'{"model": ["Intel(R) Xeon(R) CPU           L5420  @ 2.50GHz"], "vendor": ["Dell"], "topology": {"cores": 8, "threads": 8}}', u'memory_mb_used': 16896})

    hypervisors = []
    for hv in hvdata:
        i = Resource(object(), hv)
        hypervisors.append(i) 
    return hypervisors
