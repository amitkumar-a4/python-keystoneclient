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
from workloadmgr import exception as wlm_exceptions
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
    def show(self, req, id, workload_id=None, snapshot_id=None):
        """Return data about the given Restore."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                restore = self.workload_api.restore_show(context, id)
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.detail(req, restore)
        except exc.HTTPNotFound as error:
            LOG.exception(error)
            raise error
        except exc.HTTPBadRequest as error:
            LOG.exception(error)
            raise error
        except exc.HTTPServerError as error:
            LOG.exception(error)
            raise error
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def delete(self, req, id, workload_id=None, snapshot_id=None):
        """Delete a restore."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.restore_delete(context, id)
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
            except wlm_exceptions.InvalidState as error:
                raise exc.HTTPBadRequest(explanation=unicode(error))
        except exc.HTTPNotFound as error:
            LOG.exception(error)
            raise error
        except exc.HTTPBadRequest as error:
            LOG.exception(error)
            raise error
        except exc.HTTPServerError as error:
            LOG.exception(error)
            raise error
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def restore_cancel(self, req, id):
        """Cancel a restore."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.restore_cancel(context, id)
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
            except wlm_exceptions.InvalidState as error:
                raise exc.HTTPBadRequest(explanation=unicode(error))
        except exc.HTTPNotFound as error:
            LOG.exception(error)
            raise error
        except exc.HTTPBadRequest as error:
            LOG.exception(error)
            raise error
        except exc.HTTPServerError as error:
            LOG.exception(error)
            raise error
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    @wsgi.serializers(xml=RestoresTemplate)
    def index(self, req, workload_id=None, snapshot_id=None):
        """Returns a summary list of restores."""
        try:
            return self._get_restores(req, snapshot_id, is_detail=False)
        except exc.HTTPNotFound as error:
            LOG.exception(error)
            raise error
        except exc.HTTPBadRequest as error:
            LOG.exception(error)
            raise error
        except exc.HTTPServerError as error:
            LOG.exception(error)
            raise error
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    @wsgi.serializers(xml=RestoresTemplate)
    def detail(self, req, workload_id=None, snapshot_id=None):
        """Returns a detailed list of restores."""
        try:
            return self._get_restores(req, snapshot_id, is_detail=True)
        except exc.HTTPNotFound as error:
            LOG.exception(error)
            raise error
        except exc.HTTPBadRequest as error:
            LOG.exception(error)
            raise error
        except exc.HTTPServerError as error:
            LOG.exception(error)
            raise error
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def _get_restores(self, req, snapshot_id, is_detail):
        """Returns a list of restores, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        try:
            if not snapshot_id:
                snapshot_id = req.GET.get('snapshot_id', None)
            if snapshot_id:

                # verify snapshot exists
                self.workload_api.snapshot_get(context, snapshot_id)

                restores_all = self.workload_api.restore_get_all(
                    context, snapshot_id)
            else:
                restores_all = self.workload_api.restore_get_all(context)

            limited_list = common.limited(restores_all, req)

            # TODO(giri): implement the search_opts to specify the filters
            restores = []
            for restore in limited_list:
                if (restore['deleted'] == False) and (
                        restore['restore_type'] != 'test'):
                    restores.append(restore)

            if is_detail:
                restores = self._view_builder.detail_list(req, restores)
            else:
                restores = self._view_builder.summary_list(req, restores)
            return restores
        except Exception as ex:
            LOG.exception(ex)
            raise ex


def create_resource(ext_mgr):
    return wsgi.Resource(RestoresController(ext_mgr))
