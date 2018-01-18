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
                                                 'clusters:list')
authorize_detail = extensions.extension_authorizer('compute',
                                                   'clusters:detail')


def make_cluster(elem):
    elem.set('name', 'clusterName')

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


class ClustersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('Clusters')
        clusterElem = xmlutil.SubTemplateElement(root, 'Cluster',
                                                 selector='ClusterInfo')
        make_cluster(clusterElem)
        return xmlutil.MasterTemplate(root, 1, nsmap={
            Cluster.alias: Cluster.namespace})


class ClusterController(wsgi.Controller):
    """The Cluster API controller for VMware."""

    def __init__(self):
        super(ClusterController, self).__init__()
        self.servicegroup_api = servicegroup.API()
        self.cm = driver.load_compute_driver(None, "vmwareapi.VMwareVCDriver")
        self.api = compute.HostAPI(vmware_driver=self.cm)

    def _describe_clusters(self, context, **kwargs):
        ctxt = context.elevated()
        clusters = self.api.clusters(ctxt)

        return {'ClusterInfo': clusters}

    def _describe_clusters_verbose(self, context, **kwargs):
        ctxt = context.elevated()
        clusters = self.api.clusters(ctxt)

        return {'ClusterInfo': result}

    @wsgi.serializers(xml=ClustersTemplate)
    def index(self, req):
        """Returns a summary list of Clusters in vcenter."""
        context = req.environ['nova.context']
        authorize_list(context)

        return self._describe_clusters(context)

    @wsgi.serializers(xml=ClustersTemplate)
    def detail(self, req):
        """Returns a detailed list of clusters."""
        context = req.environ['nova.context']
        authorize_detail(context)

        return self._describe_clusters_verbose(context)


class Cluster(extensions.ExtensionDescriptor):
    """VMware Cluster ."""
    name = "Cluster"
    alias = "os-clusters"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "cluster/api/v1.1")
    updated = "2014-08-15T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-clusters',
            ClusterController(),
            collection_actions={
                'detail': 'GET'})
        resources.append(res)

        return resources
