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

authorize_show = extensions.extension_authorizer('compute', 'datastore:show')


def make_datastore(elem):
    elem.set('name', 'datastore')

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


class datastoreTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('datastore')
        datastoreElem = xmlutil.SubTemplateElement(root, 'datastore',
                                                   selector='datastoreInfo')
        make_datastore(datastoreElem)
        return xmlutil.MasterTemplate(root, 1, nsmap={
            datastore.alias: datastore.namespace})


class datastoreController(wsgi.Controller):
    """The datastore API controller for the OpenStack API."""

    def __init__(self):
        super(datastoreController, self).__init__()
        self.servicegroup_api = servicegroup.API()
        self.cm = driver.load_compute_driver(None, "vmwareapi.VMwareVCDriver")
        self.api = compute.HostAPI(vmware_driver=self.cm)

    def _describe_datastore(self, context, **kwargs):
        ctxt = context.elevated()
        datastore = self.api.datastore(ctxt)

        return {'datastoreInfo': datastore}

    def _describe_datastore_verbose(self, context, datastoreref, **kwargs):
        ctxt = context.elevated()
        datastore = self.api.datastore(ctxt, datastoreref)

        return {'datastoreInfo': datastore}

    @wsgi.serializers(xml=datastoreTemplate)
    def show(self, req, id):
        """Returns a summary of resource pool."""
        context = req.environ['nova.context']
        authorize_show(context)

        return self._describe_datastore_verbose(context, id)


class Datastore(extensions.ExtensionDescriptor):
    """VMware datastore ."""
    name = "datastore"
    alias = "os-datastore"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "datastore/api/v1.1")
    updated = "2014-08-15T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-datastore',
                                           datastoreController())
        resources.append(res)

        return resources
