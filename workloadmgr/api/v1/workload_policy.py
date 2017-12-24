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

    def __validate_field_values(self, values):
        try:
            if 'interval' in values:
                message = "Invalid format for interval. It should be in hrs. For ex: '1 hr'"
                if int(str(values['interval']).strip(" ").split("hr")[0]) >= 1 is False:
                    raise Exception(message)

            if 'retention_policy_type' in values:
                retention_types = ['Number of Snapshots to Keep',
                                   'Number of days to retain Snapshots']
                message = "Invalid value for retention_policy_type. Please choose among: %s" % (
                    str(retention_types))
                if values['retention_policy_type'] not in retention_types:
                    raise Exception(message)

            if 'retention_policy_value' in values:
                message = "Invalid value for retention_policy_type. It should be an integer."
                if type(int(values['retention_policy_value'])) is not int:
                    raise Exception(message)

            if 'fullbackup_interval' in values:
                message = "Invalid value for fullbackup_interval. Enter Number of incremental snapshots to take Full Backup between 1 to 999, '-1' for 'NEVER' and '0' for 'ALWAYS'"
                policy_value = values['retention_policy_value']
                if (type(int(policy_value)) is not int) or (int(policy_value) < -1) or (int(policy_value) > 999):
                    raise Exception(message)

        except Exception as ex:
            raise exception.ErrorOccurred(reason=message)

    def policy_get(self, req, id):
        """Return data about the given WorkloadPolicy."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                policy = self.workload_api.policy_get(context, id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.detail(req, policy)
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def policy_get_all(self, req):
        """list all available WorkloadPolicies."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                policies = self.workload_api.policy_list(context)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.summary_list(req, policies)
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
                field_values = policy.get('field_values')
                self.__validate_field_values(field_values)
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)
            name = policy.get('display_name', None)
            description = policy.get('display_description', "No description")
            if name is None:
                msg = _("Please provide policy name.")
                raise exc.HTTPBadRequest(explanation=msg)
            policy = self.workload_api.policy_create(context,
                                                     name,
                                                     description,
                                                     metadata,
                                                     field_values
                                                     )
            return self._view_builder.summary(req, policy)
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
                field_values = policy.get('field_values', {})
                self.__validate_field_values(field_values)
                policy = self.workload_api.policy_update(context, id, policy)
                return self._view_builder.summary(req, policy)
            except exception.NotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def policy_assign(self, req, policy_id, body):
        """Apply policy on a given tenant."""
        try:
            context = req.environ['workloadmgr.context']
            if not self.is_valid_body(body, 'policy'):
                raise exc.HTTPBadRequest()
            try:
                policy = body['policy']
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)

            add_projects = policy.get('add_projects', [])
            remove_projects = policy.get('remove_projects', [])
            if (len(add_projects) == 0) and (len(remove_projects) == 0):
                msg = _("Please provide tenant_id's to assign/remove policy.")
                raise exc.HTTPBadRequest(explanation=msg)

            if (len(set(add_projects).intersection(set(remove_projects)))) > 0:
                msg = _(
                    "Cannot have same project id for assigning and removing policy.")
                raise exc.HTTPBadRequest(explanation=msg)
            policy, failed_ids = self.workload_api.policy_assign(
                context, policy_id, add_projects, remove_projects)
            policy = self._view_builder.detail(req, policy)
            return {'policy': policy['policy'], 'failed_ids': failed_ids}
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def get_assigned_policies(self, req, tenant_id):
        """list the policies which are assigned to given project"""
        try:
            context = req.environ['workloadmgr.context']
            try:
                policies = self.workload_api.get_assigned_policies(
                    context, tenant_id)
                return {'policies': policies}
            except exception.NotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def policy_field_create(self, req, body):
        """Create a new policy_field."""
        try:
            if not self.is_valid_body(body, 'policy_field'):
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']

            try:
                policy_field = body['policy_field']
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)
            name = policy_field.get('name', None)
            type = policy_field.get('type', None)

            try:
                policy_field = self.workload_api.policy_field_create(context,
                                                                     name,
                                                                     type
                                                                     )
                return {'policy_field': policy_field}
            except exception:
                raise
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def policy_field_list(self, req):
        """list all available WorkloadPolicyFields."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                field_list = self.workload_api.policy_field_list(context)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return {'policy_field_list': field_list}
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))


def create_resource(ext_mgr):
    return wsgi.Resource(WorkloadPolicyController(ext_mgr))
