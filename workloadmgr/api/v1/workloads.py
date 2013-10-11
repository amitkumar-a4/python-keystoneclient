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



class WorkloadTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workload', selector='workload')
        make_workload(root)
        alias = Workloads.alias
        namespace = Workloads.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class WorkloadsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workloads')
        elem = xmlutil.SubTemplateElement(root, 'workload', selector='workloads')
        make_workload(elem)
        alias = Workloads.alias
        namespace = Workloads.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class WorkloadsController(wsgi.Controller):
    """The Workloads API controller"""

    _view_builder_class = workload_views.ViewBuilder

    def __init__(self):
        self.workload_api = workloadAPI.API()
        super(WorkloadsController, self).__init__()

    @wsgi.serializers(xml=WorkloadTemplate)
    def show(self, req, id):
        """Return data about the given workload."""
        LOG.debug(_('show called for member %s'), id)
        context = req.environ['workloadmgr.context']

        try:
            workload = self.workload_api.workload_show(context, workload_id=id)
        except exception.WorkloadNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        return self._view_builder.detail(req, workload)

    def delete(self, req, id):
        """Delete a workload."""
        LOG.debug(_('delete called for workload %s'), id)
        context = req.environ['workloadmgr.context']

        LOG.audit(_('Delete workload with id: %s'), id, context=context)

        try:
            self.workload_api.workload_delete(context, id)
        except exception.WorkloadNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidWorkload as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))

        return webob.Response(status_int=202)

    @wsgi.serializers(xml=WorkloadsTemplate)
    def index(self, req):
        """Returns a summary list of workload."""
        return self._get_workloads(req, is_detail=False)

    @wsgi.serializers(xml=WorkloadsTemplate)
    def detail(self, req):
        """Returns a detailed list of workload."""
        return self._get_workloads(req, is_detail=True)

    def _get_workloads(self, req, is_detail):
        """Returns a list of workloads, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        workloads = self.workload_api.workload_get_all(context)
        limited_list = common.limited(workloads, req)

        if is_detail:
            workloads = self._view_builder.detail_list(req, limited_list)
        else:
            workloads = self._view_builder.summary_list(req, limited_list)
        return workloads

def create_resource():
    return wsgi.Resource(WorkloadsController())

