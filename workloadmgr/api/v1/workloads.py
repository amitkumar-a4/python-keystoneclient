# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The workloads api."""

import webob
from webob import exc
from xml.dom import minidom

from cgi import parse_qs, escape
from workloadmgr.api import extensions
from workloadmgr.api import wsgi
from workloadmgr.api import common
from workloadmgr.api.views import workloads as workload_views
from workloadmgr.api import xmlutil
from workloadmgr import workloads as workloadAPI
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def make_workload(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('vault_service')
    elem.set('vm_id')
    elem.set('object_count')
    elem.set('availability_zone')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
    elem.set('fail_reason')



class WorkloadMgrTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workload', selector='workload')
        make_workload(root)
        alias = WorkloadMgrs.alias
        namespace = WorkloadMgrs.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class WorkloadMgrsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workloads')
        elem = xmlutil.SubTemplateElement(root, 'workload', selector='workloads')
        make_workload(elem)
        alias = WorkloadMgrs.alias
        namespace = WorkloadMgrs.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})

class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        workload = self._extract_workload(dom)
        return {'body': {'workload': workload}}

    def _extract_workload(self, node):
        workload = {}
        workload_node = self.find_first_child_named(node, 'workload')

        attributes = ['vault_service', 'display_name',
                      'display_description', 'instance_id']

        for attr in attributes:
            if workload_node.getAttribute(attr):
                workload[attr] = workload_node.getAttribute(attr)
        return workload

class WorkloadMgrsController(wsgi.Controller):
    """The API controller """

    _view_builder_class = workload_views.ViewBuilder

    def __init__(self):
        self.workload_api = workloadAPI.API()
        super(WorkloadMgrsController, self).__init__()

    @wsgi.serializers(xml=WorkloadMgrTemplate)
    def show(self, req, id):
        """Return data about the given workload."""
        LOG.debug(_('show called for member %s'), id)
        context = req.environ['workloadmgr.context']

        try:
            workload = self.workload_api.workload_show(context, workload_id=id)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        return self._view_builder.detail(req, workload)

    def delete(self, req, id):
        """Delete a workload."""
        LOG.debug(_('delete called for member %s'), id)
        context = req.environ['workloadmgr.context']

        LOG.audit(_('Delete workload with id: %s'), id, context=context)

        try:
            self.workload_api.workload_delete(context, id)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidWorkloadMgr as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))

        return webob.Response(status_int=202)

    def snapshot(self, req, id):
        """snapshot a workload."""
        LOG.debug(_('snapshot called for workload %s'), id)
        context = req.environ['workloadmgr.context']
        full = None;
        if ('QUERY_STRING' in req.environ) :
            qs=parse_qs(req.environ['QUERY_STRING'])
            var = parse_qs(req.environ['QUERY_STRING'])
            full = var.get('full',[''])[0]
            full = escape(full)

        LOG.audit(_('snapshot workload: %s'), id, context=context)
 
        try:
            if(full and full == '1'):
                full = True
            else:
                full = False    
            self.workload_api.workload_snapshot(context, id, full)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidWorkloadMgr as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))

        return webob.Response(status_int=202)

    @wsgi.serializers(xml=WorkloadMgrsTemplate)
    def index(self, req):
        """Returns a summary list of workloads."""
        return self._get_workloads(req, is_detail=False)

    @wsgi.serializers(xml=WorkloadMgrsTemplate)
    def detail(self, req):
        """Returns a detailed list of workloads."""
        return self._get_workloads(req, is_detail=True)

    def _get_workloads(self, req, is_detail):
        """Returns a list of workloadmgr, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        workloads = self.workload_api.workload_get_all(context)
        limited_list = common.limited(workloads, req)

        if is_detail:
            workloads = self._view_builder.detail_list(req, limited_list)
        else:
            workloads = self._view_builder.summary_list(req, limited_list)
        return workloads

    @wsgi.response(202)
    @wsgi.serializers(xml=WorkloadMgrTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new workload."""
        LOG.debug(_('Creating new workload %s'), body)
        if not self.is_valid_body(body, 'workload'):
            raise exc.HTTPBadRequest()

        context = req.environ['workloadmgr.context']

        try:
            workload = body['workload']
            instances = workload.get('instances')
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)
        vault_service = workload.get('vault_service', None)
        name = workload.get('name', None)
        description = workload.get('description', None)
        hours = workload.get('hours', 24);

        LOG.audit(_("Creating workload"), locals(), context=context)

        try:
            new_snapshot = self.workload_api.workload_create(context, name, 
                                                             description, instances,
                                                             vault_service, hours)
            new_snapshot_dict = self.workload_api.workload_show(context, new_snapshot.id)
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
 
        retval = self._view_builder.summary(req, new_snapshot_dict)
        return retval


def create_resource():
    return wsgi.Resource(WorkloadMgrsController())

