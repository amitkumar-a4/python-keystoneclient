# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""The tasks api."""

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
from workloadmgr.api.views import tasks as task_views


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


class TasksController(wsgi.Controller):
    """The tasks API controller for the workload manager API."""

    _view_builder_class = task_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(TasksController, self).__init__()

    def index(self, req, id):
        try:
            context = req.environ['workloadmgr.context']
            task = self.workload_api.task_show(context, task_id=id)
            return self._view_builder.detail(req, task)
        except exception.TaskNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def get_tasks(self, req):
        try:
            var = None
            context = req.environ['workloadmgr.context']
            if ('QUERY_STRING' in req.environ):
                var = parse_qs(req.environ['QUERY_STRING'])

            # function to get values from query string if it's available
            # else it will assign None
            def get_value(value): return var.get(
                value, [None])[0] if var else None

            time_in_minutes = get_value(value='time_in_minutes')
            status = get_value(value='status')
            page = get_value(value='page')
            size = get_value(value='size')
            tasks = self.workload_api.tasks_get(
                context,
                status=status,
                page=page,
                size=size,
                time_in_minutes=time_in_minutes)
            return self._view_builder.detail_list(req, tasks)
        except exception.TaskNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))


def create_resource(ext_mgr):
    return wsgi.Resource(TasksController(ext_mgr))
