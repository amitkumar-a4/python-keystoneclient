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

authorize_show = extensions.extension_authorizer('compute', 'vmnetwork:show')


def make_vmnetwork(elem):
    elem.set('name', 'vmnetwork')

    zoneStateElem.set('available')

    hostsElem = xmlutil.SubTemplateElement(elem, 'hosts', selector='hosts')
    hostElem = xmlutil.SubTemplateElement(hostsElem, 'host',
                                          selector=xmlutil.get_items)
    hostElem.set('name', 0)

    dcsElem = xmlutil.SubTemplateElement(elem, 'vmnetworks', selector=1)
    dcElem = xmlutil.SubTemplateElement(elem, 'vmnetwork',
                                        selector=xmlutil.get_items)
    dcElem.set('name', 0)

    networksElem = xmlutil.SubTemplateElement(elem, 'networks', selector=1)
    networkElem = xmlutil.SubTemplateElement(elem, 'network',
                                             selector=xmlutil.get_items)
    networkElem.set('name', 0)

    svcStateElem.set('available')
    svcStateElem.set('active')
    svcStateElem.set('updated_at')


class vmnetworkTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('vmnetwork')
        vmnetworkElem = xmlutil.SubTemplateElement(root, 'vmnetwork',
                                                   selector='vmnetworkInfo')
        make_vmnetwork(vmnetworkElem)
        return xmlutil.MasterTemplate(root, 1, nsmap={
            vmnetwork.alias: vmnetwork.namespace})


class vmnetworkController(wsgi.Controller):
    """The vmnetwork API controller for the OpenStack API."""

    def __init__(self):
        super(vmnetworkController, self).__init__()
        self.servicegroup_api = servicegroup.API()
        self.cm = driver.load_compute_driver(None, "vmwareapi.VMwareVCDriver")
        self.api = compute.HostAPI(vmware_driver=self.cm)

    def _describe_vmnetwork(self, context, **kwargs):
        ctxt = context.elevated()
        vmnetwork = self.api.vmnetwork(ctxt)

        return {'vmnetworkInfo': vmnetwork}

    def _describe_vmnetwork_verbose(self, context, vmnetworkref, **kwargs):
        ctxt = context.elevated()
        vmnetwork = self.api.vmnetwork(ctxt, vmnetworkref)

        return {'vmnetworkInfo': vmnetwork}

    @wsgi.serializers(xml=vmnetworkTemplate)
    def show(self, req, id):
        """Returns a summary of resource pool."""
        context = req.environ['nova.context']
        authorize_show(context)

        return self._describe_vmnetwork_verbose(context, id)


class Vmnetwork(extensions.ExtensionDescriptor):
    """VMware vmnetwork ."""
    name = "vmnetwork"
    alias = "os-vmnetwork"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "vmnetwork/api/v1.1")
    updated = "2014-08-15T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-vmnetwork',
                                           vmnetworkController())
        resources.append(res)

        return resources
