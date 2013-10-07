# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
WSGI middleware for workloadmanager API.
"""

from workloadmanager.api import extensions
from workloadmanager.api import versions
import workloadmanager.api
from workloadmanager.openstack.common import log as logging
from workloadmanager.api.v1 import workloads
from workloadmanager.api.v1 import snapshots

LOG = logging.getLogger(__name__)


class APIRouter(workloadmanager.api.APIRouter):
    """
    Routes requests on the workloadmanager API to the appropriate controller
    and method.
    """
    ExtensionManager = extensions.ExtensionManager

    def _setup_routes(self, mapper, ext_mgr):
        self.resources['versions'] = versions.create_resource()
        mapper.connect("versions", "/",
                       controller=self.resources['versions'],
                       action='show')

        mapper.redirect("", "/")

        self.resources['workloads'] = workloads.create_resource()
        mapper.resource("workloads", "workloads",
                        controller=self.resources['workloads'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})

        self.resources['snapshots'] = snapshots.create_resource(ext_mgr)
        mapper.resource("snapshots", "snapshots",
                        controller=self.resources['snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})  
        
        mapper.connect("hydrate",
               "/{project_id}/snapshots/{id}",
               controller=self.resources['snapshots'],
               action='hydrate',
               conditions={"method": ['POST']})      