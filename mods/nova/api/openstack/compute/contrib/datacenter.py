# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Trilio Data, Inc
#

from oslo.config import cfg

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import db
from nova import servicegroup

from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt import driver

CONF = cfg.CONF

authorize_list = extensions.extension_authorizer('compute',
                                                 'datacenters:list')
authorize_detail = extensions.extension_authorizer('compute',
                                                   'datacenters:detail')


def make_datacenter(elem):
    elem.set('name', 'datacenterName')

    zoneStateElem.set('available')

    hostsElem = xmlutil.SubTemplateElement(elem, 'hosts', selector='hosts')
    hostElem = xmlutil.SubTemplateElement(hostsElem, 'host',
                                          selector=xmlutil.get_items)
    hostElem.set('name', 0)

    dcsElem = xmlutil.SubTemplateElement(elem, 'datastores', selector=1)
    dcElem = xmlutil.SubTemplateElement(elem, 'datastore',
                                        selector=xmlutil.get_items)
    dcElem.set('name', 0)

    networksElem = xmlutil.SubTemplateElement(elem, 'networks', selector=1)
    networkElem = xmlutil.SubTemplateElement(elem, 'network',
                                             selector=xmlutil.get_items)
    networkElem.set('name', 0)

    svcStateElem.set('available')
    svcStateElem.set('active')
    svcStateElem.set('updated_at')


class DatacentersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('Datacenters')
        datacenterElem = xmlutil.SubTemplateElement(root, 'Datacenter',
                                                    selector='DatacenterInfo')
        make_datacenter(datacenterElem)
        return xmlutil.MasterTemplate(root, 1, nsmap={
            Datacenter.alias: Datacenter.namespace})


class DatacenterController(wsgi.Controller):
    """The Datacenter API controller for the OpenStack API."""

    def __init__(self):
        super(DatacenterController, self).__init__()
        self.servicegroup_api = servicegroup.API()
        self.cm = driver.load_compute_driver(None, "vmwareapi.VMwareVCDriver")
        self.api = compute.HostAPI(vmware_driver=self.cm)

    def _describe_datacenters(self, context, **kwargs):
        ctxt = context.elevated()
        datacenters = self.api.datacenters(ctxt)

        return {'DatacenterInfo': datacenters}

    def _describe_datacenters_verbose(self, context, **kwargs):
        ctxt = context.elevated()
        datacenters = self.api.datacenters(ctxt)

        result = []
        for zone in available_zones:
            hosts = {}
            for host in zone_hosts.get(zone, []):
                hosts[host] = {}
                for service in host_services[zone + host]:
                    alive = self.servicegroup_api.service_is_up(service)
                    hosts[host][service['binary']] = {'available': alive,
                                                      'active': True != service['disabled'],
                                                      'updated_at': service['updated_at']}
            result.append({'zoneName': zone,
                           'zoneState': {'available': True},
                           "hosts": hosts})

        for zone in not_available_zones:
            result.append({'zoneName': zone,
                           'zoneState': {'available': False},
                           "hosts": None})
        return {'DatacenterInfo': result}

    @wsgi.serializers(xml=DatacentersTemplate)
    def index(self, req):
        """Returns a summary list of Datacenters zone."""
        context = req.environ['nova.context']
        authorize_list(context)

        return self._describe_datacenters(context)

    @wsgi.serializers(xml=DatacentersTemplate)
    def detail(self, req):
        """Returns a detailed list of datacenters."""
        context = req.environ['nova.context']
        authorize_detail(context)

        return self._describe_datacenters_verbose(context)


class Datacenter(extensions.ExtensionDescriptor):
    """VMware Datacenter ."""
    name = "Datacenter"
    alias = "os-datacenters"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "datacenter/api/v1.1")
    updated = "2014-08-15T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-datacenters',
            DatacenterController(),
            collection_actions={
                'detail': 'GET'})
        resources.append(res)

        return resources
