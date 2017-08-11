# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2017 TrilioData, Inc.
# All Rights Reserved.

"""The config workload api."""

from webob import exc
import webob
from workloadmgr.api import wsgi
from workloadmgr import exception as wlm_exceptions
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr import workloads as workloadAPI
from workloadmgr.api.views import config_workload as config_workload_views
from workloadmgr.api.views import config_backup as config_backup_views
from workloadmgr.workloads import workload_utils

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class ConfigWorkloadController(wsgi.Controller):
    """The config workload API controller for the workload manager API."""

    _view_builder_class = config_workload_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(ConfigWorkloadController, self).__init__()

    def config_workload(self, req, body):
        """Update config workload"""
        try:
            if not self.is_valid_body(body, 'jobschedule') or \
                            self.is_valid_body(body, 'services_to_backup') is False:
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']

            jobschedule = body['jobschedule']
            services_to_backup = body['services_to_backup']

            # Validate database creds
            if services_to_backup.get('databases', None):
                try:
                    workload_utils.validate_database_creds(context, services_to_backup['databases'])
                except Exception as  ex:
                    raise ex

            # Validate trusted_host creds
            if services_to_backup.get('trusted_nodes', None):
                try:
                    workload_utils.validate_trusted_nodes(context, services_to_backup['trusted_nodes'])
                except Exception as  ex:
                    raise ex

            try:
                existing_config_workload = self.workload_api.get_config_workload(context)
            except wlm_exceptions.ConfigWorkloadNotFound:
                existing_config_workload = None

            existing_jobschedule = None

            # When user configuring for the first time
            if existing_config_workload is None:
                if services_to_backup.has_key('databases') is False or len(services_to_backup['databases'].keys()) == 0:
                    message = "Database credentials are required to configure config backup."
                    raise wlm_exceptions.ErrorOccurred(message=message)
            else:
                existing_jobschedule = existing_config_workload['jobschedule']

            if existing_jobschedule:
                jobdefaults = existing_jobschedule
            else:
                jobdefaults = {'start_time': '09:00 PM',
                               'interval': u'24hr',
                               'enabled': 'False',
                               'retention_policy_value': '30'}

            if not 'start_time' in jobschedule:
                jobschedule['start_time'] = jobdefaults['start_time']

            if not 'interval' in jobschedule:
                jobschedule['interval'] = jobdefaults['interval']

            if not 'enabled' in jobschedule:
                jobschedule['enabled'] = jobdefaults['enabled']

            if not 'retention_policy_value' in jobschedule:
                jobschedule['retention_policy_value'] = jobdefaults['retention_policy_value']

            try:
                config_workload = self.workload_api.config_workload(context,
                                                                    jobschedule, services_to_backup)
            except Exception as error:
                raise exc.HTTPServerError(explanation=unicode(error))

            retval = self._view_builder.summary(req, config_workload)
            return retval
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def get_config_workload(self, req):
        """Get Config workload object."""
        try:
            context = req.environ['workloadmgr.context']
            config_workload = self.workload_api.get_config_workload(context)
            return config_workload
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

def create_resource(ext_mgr):
    return wsgi.Resource(ConfigWorkloadController(ext_mgr))
