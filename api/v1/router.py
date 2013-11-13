# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
WSGI middleware for OpenStack workloadmgr API.
"""

from workloadmgr.api import extensions
from workloadmgr.api import versions
import workloadmgr.api
from workloadmgr.openstack.common import log as logging
from workloadmgr.api.v1 import workloads
from workloadmgr.api.v1 import snapshots

LOG = logging.getLogger(__name__)


class APIRouter(workloadmgr.api.APIRouter):
    """
    Routes requests on the OpenStack API to the appropriate controller
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
        mapper.resource("workload", "workloads",
                        controller=self.resources['workloads'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
        mapper.connect("snapshot",
                       "/{project_id}/workloads/{id}",
                       controller=self.resources['workloads'],
                       action='snapshot',
                       conditions={"method": ['POST']})

        self.resources['snapshots'] = snapshots.create_resource(ext_mgr)
        mapper.resource("snapshot", "snapshots",
                        controller=self.resources['snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})  
        
        mapper.connect("restore",
               "/{project_id}/snapshots/{id}",
               controller=self.resources['snapshots'],
               action='restore',
               conditions={"method": ['POST']})      