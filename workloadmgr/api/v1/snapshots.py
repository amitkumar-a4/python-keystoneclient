# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The snapshots api."""

import webob
from webob import exc
from xml.dom import minidom

from workloadmgr.api import common
from workloadmgr.api import wsgi
from workloadmgr.api import xmlutil
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import strutils
from workloadmgr import utils
from workloadmgr import workloads as workloadAPI
from workloadmgr.api.views import snapshots as snapshot_views


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

def make_snapshot_restore(elem):
    elem.set('snapshot_id')
    
class SnapshotRestoreTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('restore', selector='restore')
        make_snapshot_restore(root)
        alias = Snapshots.alias
        namespace = Snapshots.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})

class RestoreDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        restore = self._extract_restore(dom)
        return {'body': {'restore': restore}}

    def _extract_restore(self, node):
        restore = {}
        restore_node = self.find_first_child_named(node, 'restore')
        if restore_node.getAttribute('snapshot_id'):
            restore['snapshot_id'] = restore_node.getAttribute('snapshot_id')
        return restore


class SnapshotsController(wsgi.Controller):
    """The snapshots API controller for the OpenStack API."""

    _view_builder_class = snapshot_views.ViewBuilder
    
    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(SnapshotsController, self).__init__()

    @wsgi.serializers(xml=SnapshotTemplate)
    def show(self, req, id, workload_id=None):
        """Return data about the given Snapshot."""
        context = req.environ['workloadmgr.context']

        try:
            snapshot = self.workload_api.snapshot_show(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return {'snapshot': _translate_snapshot_detail_view(context, snapshot)}

    def delete(self, req, id, workload_id=None):
        """Delete a snapshot."""
        context = req.environ['workloadmgr.context']

        LOG.audit(_("Delete snapshot with id: %s"), id, context=context)

        try:
            snapshot = self.workload_api.snapshot_get(context, id)
            self.workload_api.deletesnapshot(context, snapshot)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def index(self, req, workload_id=None):
        """Returns a summary list of snapshots."""
        return self._get_snapshots(req, workload_id, is_detail=False)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def detail(self, req, workload_id=None):
        """Returns a detailed list of snapshots."""
        return self._get_snapshots(req, workload_id, is_detail=True)

    def _get_snapshots(self, req, workload_id, is_detail):
        """Returns a list of snapshots, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        if not workload_id:
            workload_id = req.GET.get('workload_id', None)
        if workload_id:
            snapshots = self.workload_api.snapshot_get_all(context, workload_id)
        else:
            snapshots = self.workload_api.snapshot_get_all(context)
   
        limited_list = common.limited(snapshots, req)

        if is_detail:
            snapshots = self._view_builder.detail_list(req, limited_list)
        else:
            snapshots = self._view_builder.summary_list(req, limited_list)
        return snapshots
    
    @wsgi.response(202)
    @wsgi.serializers(xml=SnapshotRestoreTemplate)
    @wsgi.deserializers(xml=RestoreDeserializer)
    def restore(self, req, id, workload_id=None, body=None):
        """Restore an existing snapshot"""
        snapshot_id = id
        LOG.debug(_('Restoring snapshot %(snapshot_id)s') % locals())
        context = req.environ['workloadmgr.context']
        LOG.audit(_("Restoring snapshot %(snapshot_id)s"),
                  locals(), context=context)

        try:
            self.workload_api.snapshot_restore(context, snapshot_id = snapshot_id )
        except exception.InvalidInput as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.InvalidWorkloadMgr as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.VolumeSizeExceedsAvailableQuota as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.message, headers={'Retry-After': 0})
        except exception.VolumeLimitExceeded as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.message, headers={'Retry-After': 0})

        return webob.Response(status_int=202)


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))