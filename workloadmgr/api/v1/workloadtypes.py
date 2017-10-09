# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""The workload_types api."""

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
from workloadmgr.api.views import workloadtypes as workload_types_views


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


def make_workload_types(elem):
    elem.set('id')
    elem.set('status')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')


class WorkloadTypeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement(
            'workload_types', selector='workload_types')
        make_workload_types(root)
        return xmlutil.MasterTemplate(root, 1)


class WorkloadTypesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workload_types')
        elem = xmlutil.SubTemplateElement(root, 'workload_types',
                                          selector='workload_types')
        make_workload_types(elem)
        return xmlutil.MasterTemplate(root, 1)


class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        workload_types = self._extract_workload_types(dom)
        return {'body': {'workload_types': workload_types}}

    def _extract_workload_types(self, node):
        workload_types = {}
        workload_types_node = self.find_first_child_named(
            node, 'workload_types')
        if workload_types_node.getAttribute('workload_types_id'):
            workload_types['workload_types_id'] = workload_types_node.getAttribute(
                'workload_types_id')
        return workload_types


class WorkloadTypesController(wsgi.Controller):
    """The workload_types API controller for the OpenStack API."""

    _view_builder_class = workload_types_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(WorkloadTypesController, self).__init__()

    @wsgi.serializers(xml=WorkloadTypeTemplate)
    def show(self, req, id):
        """Return data about the given WorkloadType."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                workload_type = self.workload_api.workload_type_show(
                    context, id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.detail(req, workload_type)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def delete(self, req, id):
        """Delete a workload_types."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.workload_type_delete(context, id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return webob.Response(status_int=202)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    @wsgi.serializers(xml=WorkloadTypesTemplate)
    def index(self, req):
        """Returns a summary list of workload_types."""
        try:
            return self._get_workload_types(req, is_detail=False)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    @wsgi.serializers(xml=WorkloadTypesTemplate)
    def detail(self, req):
        """Returns a detailed list of workload_types."""
        try:
            return self._get_workload_types(req, is_detail=True)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def _get_workload_types(self, req, is_detail):
        """Returns a list of workload_types, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        workload_types_all = self.workload_api.workload_type_get_all(context)
        limited_list = common.limited(workload_types_all, req)

        # TODO(giri): implement the search_opts to specify the filters
        workload_types = []
        for workload_type in limited_list:
            if (workload_type['deleted'] == False):
                workload_types.append(workload_type)

        if is_detail:
            workload_types = self._view_builder.detail_list(
                req, workload_types)
        else:
            workload_types = self._view_builder.summary_list(
                req, workload_types)
        return workload_types

    @wsgi.response(202)
    @wsgi.serializers(xml=WorkloadTypeTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new workload_type."""
        try:
            if not self.is_valid_body(body, 'workload_type'):
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']

            try:
                workload_type = body['workload_type']
                metadata = workload_type.get('metadata')
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)
            id = workload_type.get('id', None)
            name = workload_type.get('name', None)
            description = workload_type.get('description', None)
            is_public = workload_type.get('is_public', False)

            try:
                new_workload_type = self.workload_api.workload_type_create(context,
                                                                           id,
                                                                           name,
                                                                           description,
                                                                           is_public,
                                                                           metadata)
                new_workload_type_dict = self.workload_api.workload_type_show(
                    context, new_workload_type.id)
            except exception:
                pass

            retval = self._view_builder.summary(req, new_workload_type_dict)
            return retval
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def discover_instances(self, req, id, body):
        """discover_instances of a workload_type using the metadata"""
        try:
            context = req.environ['workloadmgr.context']
            try:
                metadata = body['metadata']
            except KeyError:
                msg = _("Incorrect request body format. Missing metadata")
                raise exc.HTTPBadRequest(explanation=msg)
            retval = None
            try:
                instances = self.workload_api.workload_type_discover_instances(
                    context, id, metadata)
            except exception:
                pass

            return instances
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def topology(self, req, id, body):
        """topology of a workload_type using the metadata"""
        try:
            context = req.environ['workloadmgr.context']
            try:
                metadata = body['metadata']
            except KeyError:
                msg = _("Incorrect request body format. Missing metadata")
                raise exc.HTTPBadRequest(explanation=msg)
            retval = None
            try:
                instances = self.workload_api.workload_type_topology(
                    context, id, metadata)
            except exception:
                pass

            return instances
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))


def create_resource(ext_mgr):
    return wsgi.Resource(WorkloadTypesController(ext_mgr))
