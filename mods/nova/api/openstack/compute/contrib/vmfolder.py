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

authorize_show = extensions.extension_authorizer('compute', 'vmfolder:show')


def make_vmfolder(elem):
    elem.set('name', 'vmfolder')

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


class vmfolderTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('vmfolder')
        vmfolderElem = xmlutil.SubTemplateElement(root, 'vmfolder',
                                                  selector='vmfolderInfo')
        make_vmfolder(vmfolderElem)
        return xmlutil.MasterTemplate(root, 1, nsmap={
            vmfolder.alias: vmfolder.namespace})


class vmfolderController(wsgi.Controller):
    """The vmfolder API controller for the OpenStack API."""

    def __init__(self):
        super(vmfolderController, self).__init__()
        self.servicegroup_api = servicegroup.API()
        self.cm = driver.load_compute_driver(None, "vmwareapi.VMwareVCDriver")
        self.api = compute.HostAPI(vmware_driver=self.cm)

    def _describe_vmfolder(self, context, **kwargs):
        ctxt = context.elevated()
        vmfolder = self.api.vmfolder(ctxt)

        return {'vmfolderInfo': vmfolder}

    def _describe_vmfolder_verbose(self, context, vmfolderref, **kwargs):
        ctxt = context.elevated()
        vmfolder = self.api.vmfolder(ctxt, vmfolderref)

        return {'vmfolderInfo': vmfolder}

    @wsgi.serializers(xml=vmfolderTemplate)
    def show(self, req, id):
        """Returns a summary list of Datacenters zone."""
        context = req.environ['nova.context']
        authorize_show(context)

        return self._describe_vmfolder_verbose(context, id)


class Vmfolder(extensions.ExtensionDescriptor):
    """VMware vmfolder ."""
    name = "vmfolder"
    alias = "os-vmfolder"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "vmfolder/api/v1.1")
    updated = "2014-08-15T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-vmfolder',
                                           vmfolderController())
        resources.append(res)

        return resources
