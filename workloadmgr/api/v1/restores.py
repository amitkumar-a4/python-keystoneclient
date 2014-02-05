# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The restores api."""

import webob
from webob import exc
from xml.dom import minidom
from cgi import parse_qs, escape

from workloadmgr.api import common
from workloadmgr.api import wsgi
from workloadmgr.api import xmlutil
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import strutils
from workloadmgr import utils
from workloadmgr import workloads as workloadAPI
from workloadmgr.api.views import restores as restore_views


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


def make_restore(elem):
    elem.set('id')
    elem.set('status')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
  
class RestoreTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('restore', selector='restore')
        make_restore(root)
        return xmlutil.MasterTemplate(root, 1)

class RestoresTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('restores')
        elem = xmlutil.SubTemplateElement(root, 'restore',
                                          selector='restores')
        make_restore(elem)
        return xmlutil.MasterTemplate(root, 1)

class RestoreDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        restore = self._extract_restore(dom)
        return {'body': {'restore': restore}}

    def _extract_restore(self, node):
        restore = {}
        restore_node = self.find_first_child_named(node, 'restore')
        if restore_node.getAttribute('restore_id'):
            restore['restore_id'] = restore_node.getAttribute('restore_id')
        return restore


class RestoresController(wsgi.Controller):
    """The restores API controller for the OpenStack API."""

    _view_builder_class = restore_views.ViewBuilder
    
    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(RestoresController, self).__init__()

    @wsgi.serializers(xml=RestoreTemplate)
    def show(self, req, id):
        """Return data about the given Restore."""
        context = req.environ['workloadmgr.context']

        try:
            restore = self.workload_api.restore_show(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return self._view_builder.detail(req, restore)
        #return {'restore': _translate_restore_detail_view(context, restore)}

    def delete(self, req, id):
        """Delete a restore."""
        context = req.environ['workloadmgr.context']

        LOG.audit(_("Delete restore with id: %s"), id, context=context)

        try:
            self.workload_api.restore_delete(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=RestoresTemplate)
    def index(self, req, snapshot_id=None):
        """Returns a summary list of restores."""
        return self._get_restores(req, snapshot_id, is_detail=False)

    @wsgi.serializers(xml=RestoresTemplate)
    def detail(self, req, snapshot_id=None):
        """Returns a detailed list of restores."""
        return self._get_restores(req, snapshot_id, is_detail=True)

    def _get_restores(self, req, snapshot_id, is_detail):
        """Returns a list of restores, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        if not snapshot_id:
            snapshot_id = req.GET.get('snapshot_id', None)
        if snapshot_id:
            restores_all = self.workload_api.restore_get_all(context, snapshot_id)
        else:
            restores_all = self.workload_api.restore_get_all(context)
   
        limited_list = common.limited(restores_all, req)
        
        #TODO(giri): implement the search_opts to specify the filters
        restores = []
        for restore in limited_list:
            if (restore['deleted'] == False) and (restore['restore_type'] != 'test'):
                restores.append(restore)        

        if is_detail:
            restores = self._view_builder.detail_list(req, restores)
        else:
            restores = self._view_builder.summary_list(req, restores)
        return restores
    
def create_resource(ext_mgr):
    return wsgi.Resource(RestoresController(ext_mgr))
