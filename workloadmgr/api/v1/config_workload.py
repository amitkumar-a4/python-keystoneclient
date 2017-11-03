# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2017 TrilioData, Inc.
# All Rights Reserved.

"""The config workload api."""

from webob import exc
from dateutil.parser import parse
from datetime import datetime
import webob
from workloadmgr.api import wsgi
from workloadmgr import exception as wlm_exceptions
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr import workloads as workloadAPI
from workloadmgr.api.views import config_workload as config_workload_views
from workloadmgr.api.views import config_backup as config_backup_views

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
                    self.is_valid_body(body, 'config_data') is False:
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']

            jobschedule = body['jobschedule']
            config_data = body['config_data']

            # Validate database creds
            if config_data.get('databases', None) is not None:
                try:
                    for database, database_config in config_data.get(
                            'databases').iteritems():
                        # Validate existance of required keys and their values
                        for required_key in ['host', 'user', 'password']:
                            if required_key not in database_config:
                                raise wlm_exceptions.ErrorOccurred(
                                    reason="Database" "credentials should have host, user and password.")
                            if str(
                                    database_config[required_key]).lower() == 'none':
                                raise wlm_exceptions.ErrorOccurred(
                                    reason="Database " + required_key + " can not be None.")
                except Exception as ex:
                    raise ex

            if config_data.get('authorized_key', None) is not None:
                config_data['authorized_key'] = config_data['authorized_key']

            existing_jobschedule = None
            try:
                existing_config_workload = self.workload_api.get_config_workload(
                    context)
                existing_jobschedule = existing_config_workload['jobschedule']
            except wlm_exceptions.ConfigWorkloadNotFound:
                existing_config_workload = None

            if jobschedule.get('interval', None) is not None:
                interval = int(jobschedule.get('interval').split('hr')[0])
                if interval < 1:
                    message = "interval should be minimum 1 hr"
                    raise wlm_exceptions.ErrorOccurred(reason=message)

            if jobschedule.get('start_time', None) is not None:
                try:
                    parse(datetime.now().strftime("%m/%d/%Y") +
                          ' ' + jobschedule.get('start_time'))
                except Exception as ex:
                    message = "Time should be in 'HH:MM AM/PM' or 'HH:MM' format. For ex: '09:00 PM' or '23:45'"
                    raise wlm_exceptions.ErrorOccurred(reason=message)

            if existing_jobschedule is not None:
                jobdefaults = existing_jobschedule
            else:
                jobdefaults = {'start_time': '09:00 PM',
                               'interval': u'24hr',
                               'enabled': 'False',
                               'retention_policy_value': '30'}

            if 'start_time' not in jobschedule:
                jobschedule['start_time'] = jobdefaults['start_time']

            if 'interval' not in jobschedule:
                jobschedule['interval'] = jobdefaults['interval']

            if 'enabled' not in jobschedule:
                jobschedule['enabled'] = jobdefaults['enabled']

            if 'retention_policy_value' not in jobschedule:
                jobschedule['retention_policy_value'] = jobdefaults['retention_policy_value']

            try:
                config_workload = self.workload_api.config_workload(
                    context, jobschedule, config_data)
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
