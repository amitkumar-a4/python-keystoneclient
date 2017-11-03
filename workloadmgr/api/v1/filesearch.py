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
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import strutils
from workloadmgr import utils
from workloadmgr import workloads as workloadAPI
from workloadmgr.api.views import search as search_views

LOG = logging.getLogger(__name__)


class FileSearchController(wsgi.Controller):
    """The file search API controller for the workload manager API."""

    _view_builder_class = search_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(FileSearchController, self).__init__()

    def show(self, req, search_id):
        try:
            context = req.environ['workloadmgr.context']
            search = self.workload_api.search_show(
                context, search_id=search_id)
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
            if 'file_search' not in body:
                raise exc.HTTPBadRequest(
                    explanation=unicode(
                        "Please provide "
                        "valid requests data"))
            file_search = body['file_search']
            if file_search.get('vm_id', None) is None:
                raise exc.HTTPBadRequest(
                    explanation=unicode(
                        "Please provide "
                        "vm_id for search"))
            if file_search.get('filepath', None) is None:
                raise exc.HTTPBadRequest(
                    explanation=unicode(
                        "Please provide "
                        "filepath for search"))
            if file_search.get('snapshot_ids', None) is None:
                file_search['snapshot_ids'] = ''
            if file_search.get('start', None) is None:
                file_search['start'] = 0
            if file_search.get('end', None) is None:
                file_search['end'] = 0
            if file_search.get('date_from', None) is None:
                file_search['date_from'] = ''
            if file_search.get('date_to', None) is None:
                file_search['date_to'] = ''
            file_search['start'] = int(file_search['start'])
            file_search['end'] = int(file_search['end'])
            search = self.workload_api.search(context, file_search)
            return self._view_builder.detail(req, search)
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))


def create_resource(ext_mgr):
    return wsgi.Resource(FileSearchController(ext_mgr))
