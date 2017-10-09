# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""The trust api."""

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


class TrustController(wsgi.Controller):
    """The trust API controller for the workload manager API."""

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(TrustController, self).__init__()

    def create(self, req, body):
        """Create a new trust"""
        try:
            context = req.environ['workloadmgr.context']

            role_name = body['trusts']['role_name']
            created_trust = self.workload_api.trust_create(context, role_name)
            return {'trust': created_trust}
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def delete(self, req, name):
        """Delete a trust."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.trust_delete(context, name)
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
        """Returns a summary list of trust."""
        try:
            return self._get_trust(req)
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

    def show(self, req, name):
        """Return data about the given setting."""
        try:
            context = req.environ['workloadmgr.context']
            get_hidden = False
            try:
                trust = self.workload_api.trust_get(context, name)
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
            return {'trust': trust}
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

    def _get_trust(self, req):
        """Returns a list of trust"""
        context = req.environ['workloadmgr.context']
        trust = self.workload_api.trust_list(context)
        return {'trust': trust}


def create_resource(ext_mgr):
    return wsgi.Resource(TrustController(ext_mgr))
