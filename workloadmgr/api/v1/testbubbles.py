# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The testbubbles api."""

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
from workloadmgr.api.views import testbubbles as testbubble_views


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


def make_testbubble(elem):
    elem.set('id')
    elem.set('status')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')


class TestbubbleTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('testbubble', selector='testbubble')
        make_testbubble(root)
        return xmlutil.MasterTemplate(root, 1)


class TestbubblesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('testbubbles')
        elem = xmlutil.SubTemplateElement(root, 'testbubble',
                                          selector='testbubbles')
        make_testbubble(elem)
        return xmlutil.MasterTemplate(root, 1)


class TestbubbleDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        testbubble = self._extract_testbubble(dom)
        return {'body': {'testbubble': testbubble}}

    def _extract_testbubble(self, node):
        testbubble = {}
        testbubble_node = self.find_first_child_named(node, 'testbubble')
        if testbubble_node.getAttribute('testbubble_id'):
            testbubble['testbubble_id'] = testbubble_node.getAttribute(
                'testbubble_id')
        return testbubble


class TestbubblesController(wsgi.Controller):
    """The testbubbles API controller for the OpenStack API."""

    _view_builder_class = testbubble_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(TestbubblesController, self).__init__()

    @wsgi.serializers(xml=TestbubbleTemplate)
    def show(self, req, id, workload_id=None, snapshot_id=None):
        """Return data about the given Testbubble."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                testbubble = self.workload_api.restore_show(context, id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.detail(req, testbubble)
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
        """Delete a testbubble."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.restore_delete(context, id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return webob.Response(status_int=202)
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

    @wsgi.serializers(xml=TestbubblesTemplate)
    def index(self, req, workload_id=None, snapshot_id=None):
        """Returns a summary list of testbubbles."""
        try:
            return self._get_testbubbles(req, snapshot_id, is_detail=False)
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

    @wsgi.serializers(xml=TestbubblesTemplate)
    def detail(self, req, workload_id=None, snapshot_id=None):
        """Returns a detailed list of testbubbles."""
        try:
            return self._get_testbubbles(req, snapshot_id, is_detail=True)
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

    def _get_testbubbles(self, req, snapshot_id, is_detail):
        """Returns a list of testbubbles, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        if not snapshot_id:
            snapshot_id = req.GET.get('snapshot_id', None)
        if snapshot_id:
            testbubbles_all = self.workload_api.restore_get_all(
                context, snapshot_id)
        else:
            testbubbles_all = self.workload_api.restore_get_all(context)

        limited_list = common.limited(testbubbles_all, req)

        # TODO(giri): implement the search_opts to specify the filters
        testbubbles = []
        for testbubble in limited_list:
            if (testbubble['deleted'] == False) and (
                    testbubble['restore_type'] == 'test'):
                testbubbles.append(testbubble)

        if is_detail:
            testbubbles = self._view_builder.detail_list(req, testbubbles)
        else:
            testbubbles = self._view_builder.summary_list(req, testbubbles)
        return testbubbles


def create_resource(ext_mgr):
    return wsgi.Resource(TestbubblesController(ext_mgr))
