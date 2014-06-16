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
from workloadmgr.api.views import snapshots as snapshot_views
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
    elem.set('vm_id')
    elem.set('object_count')
    elem.set('availability_zone')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
    elem.set('fail_reason')



class WorkloadTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workload', selector='workload')
        make_workload(root)
        alias = WorkloadMgrs.alias
        namespace = WorkloadMgrs.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class WorkloadsTemplate(xmlutil.TemplateBuilder):
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

class UpdateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        workload = self._extract_workload(dom)
        return {'body': {'workload': workload}}

    def _extract_workload(self, node):
        workload = {}
        workload_node = self.find_first_child_named(node, 'workload')

        attributes = ['display_name', 'display_description']

        for attr in attributes:
            if workload_node.getAttribute(attr):
                workload[attr] = workload_node.getAttribute(attr)
        return workload

class WorkloadMgrsController(wsgi.Controller):
    """The API controller """

    _view_builder_class = workload_views.ViewBuilder
    snapshot_view_builder = snapshot_views.ViewBuilder()

    def __init__(self):
        self.workload_api = workloadAPI.API()
        super(WorkloadMgrsController, self).__init__()

    @wsgi.serializers(xml=WorkloadTemplate)
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

    def snapshot(self, req, id, body=None):
        """snapshot a workload."""
        LOG.debug(_('snapshot called for workload %s'), id)
        context = req.environ['workloadmgr.context']
        full = None
        if ('QUERY_STRING' in req.environ) :
            qs=parse_qs(req.environ['QUERY_STRING'])
            var = parse_qs(req.environ['QUERY_STRING'])
            full = var.get('full',[''])[0]
            full = escape(full)

        LOG.audit(_('snapshot workload: %s'), id, context=context)
        try:
            snapshot_type = 'none'
            if (full and full == '1'):
                snapshot_type = 'full'
            name = ''
            description = ''
            if (body and 'snapshot' in body):
                name = body['snapshot'].get('name', None)
                description = body['snapshot'].get('description', None)                
            new_snapshot = self.workload_api.workload_snapshot(context, id, snapshot_type, name, description)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidWorkloadMgr as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        
        return self.snapshot_view_builder.summary(req,dict(new_snapshot.iteritems()))
        #return {'snapshot': _translate_snapshot_detail_view(context, dict(new_snapshot.iteritems()))}
    
    @wsgi.serializers(xml=WorkloadsTemplate)
    def index(self, req):
        """Returns a summary list of workloads."""
        return self._get_workloads(req, is_detail=False)

    @wsgi.serializers(xml=WorkloadsTemplate)
    def detail(self, req):
        """Returns a detailed list of workloads."""
        return self._get_workloads(req, is_detail=True)

    def _get_workloads(self, req, is_detail):
        """Returns a list of workloadmgr, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        workloads_all = self.workload_api.workload_get_all(context)
        limited_list = common.limited(workloads_all, req)
        
        #TODO(giri): implement the search_opts to specify the filters
        workloads = []
        for workload in limited_list:
            if workload['deleted'] == False:
                workloads.append(workload)
        
        if is_detail:
            workloads = self._view_builder.detail_list(req, workloads)
        else:
            workloads = self._view_builder.summary_list(req, workloads)
        return workloads

    @wsgi.response(202)
    @wsgi.serializers(xml=WorkloadTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new workload."""
        LOG.debug(_('Creating new workload %s'), body)
        if not self.is_valid_body(body, 'workload'):
            raise exc.HTTPBadRequest()

        context = req.environ['workloadmgr.context']

        try:
            workload = body['workload']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)
        name = workload.get('name', None)
        description = workload.get('description', None)
        workload_type_id = workload.get('workload_type_id', None)
        jobschedule = workload.get('jobschedule', {})
        instances = workload.get('instances', {})
        metadata = workload.get('metadata', {})       

        LOG.audit(_("Creating workload"), locals(), context=context)

        try:
            new_workload = self.workload_api.workload_create(context, 
                                                             name, 
                                                             description,
                                                             workload_type_id, 
                                                             instances,
                                                             jobschedule,
                                                             metadata)
            new_workload_dict = self.workload_api.workload_show(context, new_workload.id)
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
 
        retval = self._view_builder.summary(req, new_workload_dict)
        return retval

    @wsgi.response(202)
    @wsgi.serializers(xml=WorkloadTemplate)
    @wsgi.deserializers(xml=UpdateDeserializer)
    def update(self, req, id, body):
        """Update workload."""
        LOG.debug(_('Updating workload %s'), id)
        if not self.is_valid_body(body, 'workload'):
            raise exc.HTTPBadRequest()

        context = req.environ['workloadmgr.context']
        try:
            self.workload_api.workload_modify(context, id, body)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

    def get_workflow(self, req, id):
        """Return workflow details of a given workload."""
        LOG.debug(_('get_workflow called for member %s'), id)
        context = req.environ['workloadmgr.context']

        try:
            workload_workflow = self.workload_api.workload_get_workflow(context, workload_id=id)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        return workload_workflow
    
    def pause(self, req, id):
        """pause a given workload."""
        LOG.debug(_('pause called for member %s'), id)
        context = req.environ['workloadmgr.context']

        try:
            self.workload_api.workload_pause(context, workload_id=id)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

    def resume(self, req, id):
        """resume a given workload."""
        LOG.debug(_('resume called for member %s'), id)
        context = req.environ['workloadmgr.context']

        try:
            self.workload_api.workload_resume(context, workload_id=id)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error)) 
    
    def get_topology(self, req, id):
        """Return topology of a given workload."""
        LOG.debug(_('get_topology called for member %s'), id)
        context = req.environ['workloadmgr.context']

        try:
            workload_topology = self.workload_api.workload_get_topology(context, workload_id=id)
        except exception.WorkloadMgrNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        return workload_topology    

def create_resource():
    return wsgi.Resource(WorkloadMgrsController())

