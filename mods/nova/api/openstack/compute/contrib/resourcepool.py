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

authorize_show = extensions.extension_authorizer(
    'compute', 'resourcepool:show')


def make_resourcepool(elem):
    elem.set('name', 'resourcepool')

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


class resourcepoolTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('resourcepool')
        resourcepoolElem = xmlutil.SubTemplateElement(
            root, 'resourcepool', selector='resourcepoolInfo')
        make_resourcepool(resourcepoolElem)
        return xmlutil.MasterTemplate(root, 1, nsmap={
            resourcepool.alias: resourcepool.namespace})


class resourcepoolController(wsgi.Controller):
    """The resourcepool API controller for the OpenStack API."""

    def __init__(self):
        super(resourcepoolController, self).__init__()
        self.servicegroup_api = servicegroup.API()
        self.cm = driver.load_compute_driver(None, "vmwareapi.VMwareVCDriver")
        self.api = compute.HostAPI(vmware_driver=self.cm)

    def _describe_resourcepool(self, context, **kwargs):
        ctxt = context.elevated()
        resourcepool = self.api.resourcepool(ctxt)

        return {'resourcepoolInfo': resourcepool}

    def _describe_resourcepool_verbose(
            self, context, resourcepoolref, **kwargs):
        ctxt = context.elevated()
        resourcepool = self.api.resourcepool(ctxt, resourcepoolref)

        return {'resourcepoolInfo': resourcepool}

    @wsgi.serializers(xml=resourcepoolTemplate)
    def show(self, req, id):
        """Returns a summary of resource pool."""
        context = req.environ['nova.context']
        authorize_show(context)

        return self._describe_resourcepool_verbose(context, id)


class Resourcepool(extensions.ExtensionDescriptor):
    """VMware resourcepool ."""
    name = "resourcepool"
    alias = "os-resourcepool"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "resourcepool/api/v1.1")
    updated = "2014-08-15T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-resourcepool',
                                           resourcepoolController())
        resources.append(res)

        return resources
