# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""The tasks api."""

from webob import exc
from cgi import parse_qs

from workloadmgr.api import wsgi
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
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
            context = req.environ['workloadmgr.context']
            if ('QUERY_STRING' in req.environ):
                parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                time_in_minutes = var.get('time_in_minutes', [None])[0]
                status = var.get('status', [None])[0]
                page = var.get('page', [None])[0]
                size = var.get('size', [None])[0]
            tasks = self.workload_api.tasks_get(
                context, status=status,
                page=page, size=size,
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
