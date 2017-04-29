# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""The search api"""

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
from workloadmgr.api.views import search as search_views

LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS

class FileSearchController(wsgi.Controller):
    """The file search API controller for the workload manager API."""

    _view_builder_class = search_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(FileSearchController, self).__init__()

    def index(self, req, id):
        try:
            context = req.environ['workloadmgr.context']
            search = self.workload_api.search_show(context, search_id=id)
            return self._view_builder.detail(req, search)
        except exception.FileSearchNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def search(self, req, body):
        try:
            context = req.environ['workloadmgr.context']
            search = self.workload_api.search(context)
            return search
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

def create_resource(ext_mgr):
    return wsgi.Resource(FileSearchController(ext_mgr))
