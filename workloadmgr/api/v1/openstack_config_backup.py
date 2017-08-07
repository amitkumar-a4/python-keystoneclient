# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2017 TrilioData, Inc.
# All Rights Reserved.

"""The OpenStack configuration backup api."""

from webob import exc
import time
import pickle
import os
import yaml
import webob
from workloadmgr.api import wsgi
from workloadmgr import exception as wlm_exceptions
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr import workloads as workloadAPI
from workloadmgr.api import xmlutil
from workloadmgr.api.views import config_workload as config_workload_views
from workloadmgr.api.views import config_backup as config_backup_views
from workloadmgr.workloads import workload_utils

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS

class ConfigBackupController(wsgi.Controller):
    """The OpenStack config backup API controller for the workload manager API."""

    _view_builder_class = config_workload_views.ViewBuilder
    backup_view_builder = config_backup_views.ViewBuilder()
    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(ConfigBackupController, self).__init__()

    def config_workload(self, req, body):
        """Update config backup workload"""
        try:
            if not self.is_valid_body(body, 'jobschedule')or\
               self.is_valid_body(body, 'services_to_backup') is False:
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']

            jobschedule = body['jobschedule']
            services_to_backup = body['services_to_backup']

            #Validate database creds
            if services_to_backup.get('databases', None):
               try:
                   workload_utils.validate_database_creds(context, services_to_backup['databases'])
               except Exception as  ex:
                   raise ex

            #Validate trusted_host creds
            if services_to_backup.get('trusted_nodes', None):
               try:
                   workload_utils.validate_trusted_node_creds(context, services_to_backup['trusted_nodes'])
               except Exception as  ex:
                   raise ex

            try:
                existing_config_workload = self.workload_api.get_config_workload(context)
            except wlm_exceptions.ConfigWorkload:
                existing_config_workload = None

            existing_jobschedule = None

            #When user configuring for the first time
            if existing_config_workload is None:
                if services_to_backup.has_key('databases') is False or len(services_to_backup['databases'].keys()) == 0:
                    message = "Database credentials are required to configure config backup."
                    raise wlm_exceptions.ConfigWorkload(message=message)
            else:
                existing_jobschedule = existing_config_workload['jobschedule']

            if existing_jobschedule:
                jobdefaults = existing_jobschedule
            else:
                jobdefaults = {'start_time': '09:00 PM',
                               'interval': u'24hr',
                               'start_date': time.strftime("%m/%d/%Y"),
                               'end_date': 'No End',
                               'enabled': 'False',
                               'retention_policy_type': 'Number of Snapshots to Keep',
                               'retention_policy_value': '30'}

            if not 'start_time' in jobschedule:
                jobschedule['start_time'] = jobdefaults['start_time']

            if not 'interval' in jobschedule:
                jobschedule['interval'] = jobdefaults['interval']

            if not 'enabled' in jobschedule:
               jobschedule['enabled'] = jobdefaults['enabled']

            if not 'start_date' in jobschedule:
                jobschedule['start_date'] = jobdefaults['start_date']

            if not 'end_date' in jobschedule:
                jobschedule['end_date'] = jobdefaults['end_date']

            if not 'retention_policy_type' in jobschedule:
                jobschedule['retention_policy_type'] = jobdefaults['retention_policy_type']

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
        """Get Config backup workload object."""
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

    def config_backup(self, req, body=None):
        """Backup openstack configuration."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                config_workload = self.workload_api.get_config_workload(context)
            except wlm_exceptions.ConfigWorkload:
                message = "Configuration backup is not configured. First configure it."
                raise wlm_exceptions.ConfigWorkload(message=message)

            if (body and 'backup' in body):
                name = body['backup'].get('name', "")
                name = name.strip() or 'Config backup'
                description = body['backup'].get('description', "")
                description = description.strip() or 'no-description'

            backup = self.workload_api.config_backup(context, name, description)
            return self.backup_view_builder.summary(req, dict(backup.iteritems()))
        except wlm_exceptions.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def config_backup_list(self, req):
        """Returns a summary list of backups."""
        try:
            context = req.environ['workloadmgr.context']
            backups = self.workload_api.get_config_backups(context)
            return self.backup_view_builder.summary_list(req, backups)
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
    
    def get_config_backup(self, req, id):
        """Return data about the given Backup."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                backup = self.workload_api.get_config_backups(context, id)
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
            return self.backup_view_builder.detail(req, backup)
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

    def config_backup_delete(self, req, id):
        """Delete a backup."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.config_backup_delete(context, id)
                return webob.Response(status_int=202)
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
    return wsgi.Resource(ConfigBackupController(ext_mgr))
