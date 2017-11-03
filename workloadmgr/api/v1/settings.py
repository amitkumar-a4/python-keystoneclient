# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""The settings api."""

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
from workloadmgr.common.workloadmgr_keystoneclient import KeystoneClient
from workloadmgr import settings as settings_module
LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class SettingsController(wsgi.Controller):
    """The settings API controller for the workload manager API."""

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(SettingsController, self).__init__()

    def create(self, req, body):
        """Create a new setting"""
        try:
            context = req.environ['workloadmgr.context']
            try:
                settings = body['settings']
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)

            created_settings = self.workload_api.settings_create(
                context, body['settings'])
            return {'settings': created_settings}
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def update(self, req, body):
        """Update settings"""
        try:
            context = req.environ['workloadmgr.context']

            try:
                settings = body['settings']
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)

            updated_settings = self.workload_api.settings_update(
                context, body['settings'])
            return {'settings': updated_settings}

        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def show(self, req, name):
        """Return data about the given setting."""
        try:
            context = req.environ['workloadmgr.context']
            keystone_client = KeystoneClient(context)
            get_hidden = False
            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                get_hidden = var.get('get_hidden', [''])[0]
                get_hidden = escape(get_hidden)
                if get_hidden.lower() == 'true':
                    get_hidden = True

            if name == 'user_email_address_' + context.user_id:
                user = keystone_client.get_user_to_get_email_address(context)
                user_obj = {}
                user_obj['email'] = user.email
                return {'setting': user_obj}

            try:
                setting = self.workload_api.setting_get(
                    context, name, get_hidden)
                if setting is None:
                    settings = settings_module.get_settings(context)
                    for setting_loop in settings:
                        if setting_loop == name:
                            setting = {
                                'name': setting_loop,
                                'value': settings[setting_loop],
                                'type': 'Default setting'}
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
            return {'setting': setting}
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

    def delete(self, req, name):
        """Delete a setting."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.setting_delete(context, name)
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
        """Returns a summary list of settings."""
        try:
            return self._get_settings(req, is_detail=False)
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

    def detail(self, req):
        """Returns a detailed list of settings."""
        try:
            return self._get_settings(req, is_detail=True)
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

    def _get_settings(self, req, is_detail):
        """Returns a list of settings"""
        context = req.environ['workloadmgr.context']
        get_hidden = False
        if ('QUERY_STRING' in req.environ):
            qs = parse_qs(req.environ['QUERY_STRING'])
            var = parse_qs(req.environ['QUERY_STRING'])
            get_hidden = var.get('get_hidden', [''])[0]
            get_hidden = escape(get_hidden)
            if get_hidden.lower() == 'true':
                get_hidden = True
        settings = self.workload_api.settings_get(context, get_hidden)
        return {'settings': settings}


def create_resource(ext_mgr):
    return wsgi.Resource(SettingsController(ext_mgr))
