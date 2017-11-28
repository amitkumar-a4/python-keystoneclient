# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.
"""
Common Auth Middleware.

"""
import os

try:
   from oslo_config import cfg
except ImportError:
   from oslo.config import cfg

import webob.dec
import webob.exc

from workloadmgr.api import wsgi
from workloadmgr.common import context
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr import wsgi as base_wsgi

use_forwarded_for_opt = cfg.BoolOpt(
    'use_forwarded_for',
    default=False,
    help='Treat X-Forwarded-For as the canonical remote address. '
         'Only enable this if you have a sanitizing proxy.')

FLAGS = flags.FLAGS
FLAGS.register_opt(use_forwarded_for_opt)
LOG = logging.getLogger(__name__)


def pipeline_factory(loader, global_conf, **local_conf):
    """A paste pipeline replica that keys off of auth_strategy."""
    pipeline = local_conf[FLAGS.auth_strategy]
    if not FLAGS.api_rate_limit:
        limit_name = FLAGS.auth_strategy + '_nolimit'
        pipeline = local_conf.get(limit_name, pipeline)
    pipeline = pipeline.split()
    filters = [loader.get_filter(n) for n in pipeline[:-1]]
    app = loader.get_app(pipeline[-1])
    filters.reverse()
    for filter in filters:
        app = filter(app)
    return app


class InjectContext(base_wsgi.Middleware):
    """Add a 'workloadmgr.context' to WSGI environ."""

    def __init__(self, context, *args, **kwargs):
        self.context = context
        super(InjectContext, self).__init__(*args, **kwargs)

    @webob.dec.wsgify(RequestClass=base_wsgi.Request)
    def __call__(self, req):
        req.environ['workloadmgr.context'] = self.context
        return self.application


class WorkloadMgrKeystoneContext(base_wsgi.Middleware):
    """Make a request context from keystone headers"""

    @webob.dec.wsgify(RequestClass=base_wsgi.Request)
    def __call__(self, req):

        user_id = req.headers.get('X_USER')
        user_id = req.headers.get('X_USER_ID', user_id)
        if user_id is None:
            LOG.debug("Neither X_USER_ID nor X_USER found in request")
            return webob.exc.HTTPUnauthorized()

        user_name = req.headers.get('X-User-Name')
        project_name = req.headers.get('X-Project-Name', None)
        project_name = tenant_name = req.headers.get('X-Tenant', project_name)

        # This is the new header since Keystone went to ID/Name
        project_id = req.headers.get('X_TENANT_ID', None)
        project_id = req.headers.get('X_PROJECT_ID', project_id)
        if project_id is None:
            LOG.debug("Neither X_TENANT_ID nor X_USER found in request")
            return webob.exc.HTTPUnauthorized()

        project_domain_id = req.headers.get('X-Project-Domain-Id', None)
        project_domain_name = req.headers.get('X-Project-Domain-Name', None)

        user_domain_id = req.headers.get('X-User-Domain-Id', None)
        user_domain_name = req.headers.get('X-User-Domain-Name', None)

        domain_name = req.headers.get('X-Domain-Name', None)
        domain_id = req.headers.get('X-Domain-Id', None)

        # get the roles
        roles = [r.strip() for r in req.headers.get('X_ROLE', '').split(',')]

        # Get the auth token
        auth_token = req.headers.get('X_AUTH_TOKEN',
                                     req.headers.get('X_STORAGE_TOKEN'))

        # Build a context, including the auth_token...
        remote_address = req.remote_addr
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)

        ctx = context.RequestContext(user_id=user_id,
                                     username=user_name,
                                     project_id=project_id,
                                     tenant_id=project_id,
                                     tenant=project_name,
                                     user_domain_id=user_domain_id,
                                     project_domain_id=project_domain_id,
                                     user_domain_name=user_domain_name,
                                     project_domain_name=project_domain_name,
                                     domain_name=domain_name,
                                     domain_id=domain_id,
                                     roles=roles,
                                     auth_token=auth_token,
                                     remote_address=remote_address)

        req.environ['workloadmgr.context'] = ctx
        return self.application


class NoAuthMiddleware(base_wsgi.Middleware):
    """Return a fake token if one isn't specified."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if 'X-Auth-Token' not in req.headers:
            user_id = req.headers.get('X-Auth-User', 'admin')
            project_id = req.headers.get('X-Auth-Project-Id', 'admin')
            os_url = os.path.join(req.url, project_id)
            res = webob.Response()
            # NOTE(vish): This is expecting and returning Auth(1.1), whereas
            #             keystone uses 2.0 auth.  We should probably allow
            #             2.0 auth here as well.
            res.headers['X-Auth-Token'] = '%s:%s' % (user_id, project_id)
            res.headers['X-Server-Management-Url'] = os_url
            res.content_type = 'text/plain'
            res.status = '204'
            return res

        token = req.headers['X-Auth-Token']
        user_id, _sep, project_id = token.partition(':')
        project_id = project_id or user_id
        remote_address = getattr(req, 'remote_address', '127.0.0.1')
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)
        ctx = context.RequestContext(user_id,
                                     project_id,
                                     is_admin=True,
                                     remote_address=remote_address)

        req.environ['workloadmgr.context'] = ctx
        return self.application
