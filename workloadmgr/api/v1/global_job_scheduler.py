# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""The global job scheduler api."""

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


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


class GlobalJobSchedulerController(wsgi.Controller):
    """The global job scheduler API controller for the workload manager API."""

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(GlobalJobSchedulerController, self).__init__()

    def enable(self, req):
        """Enable global job scheduler"""
        try:
            context = req.environ['workloadmgr.context']

            self.workload_api.workload_enable_global_job_scheduler(context)
            return {'global_job_scheduler': True}
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def disable(self, req):
        """Disable global job scheduler"""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.workload_disable_global_job_scheduler(
                    context)
                return {'global_job_scheduler': False}
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

    def index(self, req):
        """Return status of global job scheduler."""
        try:
            context = req.environ['workloadmgr.context']
            get_hidden = False
            try:
                enabled = self.workload_api.workload_get_global_job_scheduler(
                    context)
                return {'global_job_scheduler': enabled}
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
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


def create_resource(ext_mgr):
    return wsgi.Resource(GlobalJobSchedulerController(ext_mgr))
