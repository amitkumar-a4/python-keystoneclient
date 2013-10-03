# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The workloadmanager snapshots api."""

import webob
from webob import exc
from xml.dom import minidom

from workloadmanager.api import common
from workloadmanager.api import wsgi
from workloadmanager.api import xmlutil
from workloadmanager import exception
from workloadmanager import flags
from workloadmanager.openstack.common import log as logging
from workloadmanager.openstack.common import strutils
from workloadmanager import utils
from workloadmanager import workloads as workloadsAPI
from workloadmanager.api.views import snapshots as snapshot_views


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


def _translate_snapshot_detail_view(context, snapshot):
    """Maps keys for snapshots details view."""

    d = _translate_snapshot_summary_view(context, snapshot)

    return d


def _translate_snapshot_summary_view(context, snapshot):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = snapshot['id']
    d['created_at'] = snapshot['created_at']
    d['status'] = snapshot['status']
 
    return d


def make_snapshot(elem):
    elem.set('id')
    elem.set('status')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
    


class SnapshotTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshot', selector='snapshot')
        make_snapshot(root)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshots')
        elem = xmlutil.SubTemplateElement(root, 'snapshot',
                                          selector='snapshots')
        make_snapshot(elem)
        return xmlutil.MasterTemplate(root, 1)

def make_snapshot_hydrate(elem):
    elem.set('snapshot_id')
    
class SnapshotHydrateTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hydrate', selector='hydrate')
        make_snapshot_hydrate(root)
        alias = Snapshots.alias
        namespace = Snapshots.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})

class HydrateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        hydrate = self._extract_hydrate(dom)
        return {'body': {'hydrate': hydrate}}

    def _extract_hydrate(self, node):
        hydrate = {}
        hydrate_node = self.find_first_child_named(node, 'hydrate')
        if hydrate_node.getAttribute('snapshot_id'):
            hydrate['snapshot_id'] = hydrate_node.getAttribute('snapshot_id')
        return hydrate


class SnapshotsController(wsgi.Controller):
    """The snapshots API controller for the workloadmanager API."""

    _view_builder_class = snapshot_views.ViewBuilder
    
    def __init__(self, ext_mgr=None):
        self.workloads_api = workloadsAPI.API()
        self.ext_mgr = ext_mgr
        super(SnapshotsController, self).__init__()

    @wsgi.serializers(xml=SnapshotTemplate)
    def show(self, req, id):
        """Return data about the given Snapshot."""
        context = req.environ['workloadmanager.context']

        try:
            snapshot = self.workloads_api.snapshot_show(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return {'snapshot': _translate_snapshot_detail_view(context, snapshot)}

    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['workloadmanager.context']

        LOG.audit(_("Delete snapshot with id: %s"), id, context=context)

        try:
            snapshot = self.workloads_api.snapshot_get(context, id)
            self.workloads_api.deletesnapshot(context, snapshot)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def index(self, req):
        """Returns a summary list of snapshots."""
        return self._get_snapshots(req, is_detail=False)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def detail(self, req):
        """Returns a detailed list of snapshots."""
        return self._get_snapshots(req, is_detail=True)

    def _get_snapshots(self, req, is_detail):
        """Returns a list of snapshots, transformed through view builder."""
        context = req.environ['workloadmanager.context']
        snapshot_id = req.GET.get('snapshot_id', None)
        if snapshot_id:
            snapshots = self.workloads_api.snapshot_get_all(context, snapshot_id)
        else:
            snapshots = self.workloads_api.snapshot_get_all(context)
   
        limited_list = common.limited(snapshots, req)

        if is_detail:
            snapshots = self._view_builder.detail_list(req, limited_list)
        else:
            snapshots = self._view_builder.summary_list(req, limited_list)
        return snapshots
    
    @wsgi.response(202)
    @wsgi.serializers(xml=SnapshotHydrateTemplate)
    @wsgi.deserializers(xml=HydrateDeserializer)
    def hydrate(self, req, id):
        """Restore an existing snapshot"""
        snapshot_id = id
        LOG.debug(_('Restoring snapshot %(snapshot_id)s') % locals())
        context = req.environ['workloadmanager.context']
        LOG.audit(_("Hydrating snapshot %(snapshot_id)s"),
                  locals(), context=context)

        try:
            self.workloads_api.snapshot_hydrate(context, snapshot_id = snapshot_id )
        except exception.InvalidInput as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.InvalidSnapshot as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.SnapshotNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        return webob.Response(status_int=202)


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))
