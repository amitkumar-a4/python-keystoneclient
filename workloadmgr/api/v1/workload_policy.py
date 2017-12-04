# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

"""The workload_policy api."""

import webob
from webob import exc

from workloadmgr.api import wsgi
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr import workloads as workloadAPI
from workloadmgr.api.views import workload_policy as workload_policy_views

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class WorkloadPolicyController(wsgi.Controller):
    """The workload_policy API controller for the OpenStack API."""

    _view_builder_class = workload_policy_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(WorkloadPolicyController, self).__init__()

    def policy_get(self, req, id):
        """Return data about the given WorkloadPolicy."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                policy = self.workload_api.policy_get(context, id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.detail(req, policy)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def policy_get_all(self, req):
        """Return data about the given WorkloadPolicy."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                policies = self.workload_api.policy_list(context)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.summary_list(req, policies)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def policy_delete(self, req, id):
        """Delete a workload_policy."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.policy_delete(context, id)
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

    def policy_create(self, req, body):
        """Create a new workload_policy."""
        try:
            if not self.is_valid_body(body, 'workload_policy'):
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']

            try:
                policy = body['workload_policy']
                metadata = policy.get('metadata')
                field_values = policy.get('field_vales')
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)
            name = policy.get('display_name', None)
            description = policy.get('display_description', "No description")
            if str(name).lower() is "none":
                msg = _("Please provide policy name.")
                raise exc.HTTPBadRequest(explanation=msg)
            policy = self.workload_api.policy_create(context,
                                                       name,
                                                       description,
                                                       metadata,
                                                       field_values
                                                       )
            return self._view_builder.summary(req, policy)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def policy_update(self, req, id, body):
        """Update workload policy."""
        try:
            if not self.is_valid_body(body, 'policy'):
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']
            try:
                try:
                    policy = body['policy']
                except KeyError:
                    msg = _("Incorrect request body format")
                    raise exc.HTTPBadRequest(explanation=msg)
                policy = self.workload_api.policy_update(context, id, policy)
                return self._view_builder.summary(req, policy)
            except exception.WorkloadNotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
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
    return wsgi.Resource(WorkloadPolicyController(ext_mgr))
