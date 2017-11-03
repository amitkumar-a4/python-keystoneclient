# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2017 TrilioData, Inc.
# All Rights Reserved.

"""The OpenStack configuration backup api."""

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


class ConfigBackupController(wsgi.Controller):
    """The OpenStack config backup API controller for the workload manager API."""

    backup_view_builder = config_backup_views.ViewBuilder()

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(ConfigBackupController, self).__init__()

    def config_backup(self, req, body=None):
        """Backup openstack configuration."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                config_workload = self.workload_api.get_config_workload(
                    context)
            except wlm_exceptions.ConfigWorkloadNotFound:
                message = "Configuration backup is not configured. First configure it."
                raise wlm_exceptions.ErrorOccurred(reason=message)

            if (body and 'backup' in body):
                name = body['backup'].get('name', "")
                name = name.strip() or 'Config backup'
                description = body['backup'].get('description', "")
                description = description.strip() or 'no-description'

            backup = self.workload_api.config_backup(
                context, name, description)
            return self.backup_view_builder.summary(
                req, dict(backup.iteritems()))
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
