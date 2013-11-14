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
        #detail list of workloads
        mapper.resource("workload", "workloads",
                        controller=self.resources['workloads'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
        #take a snapshot of the workload
        mapper.connect("snapshot",
                       "/{project_id}/workloads/{id}",
                       controller=self.resources['workloads'],
                       action='snapshot',
                       conditions={"method": ['POST']})
        
        
        self.resources['snapshots'] = snapshots.create_resource(ext_mgr)
        #detail list of snapshots
        mapper.resource("snapshots1", "snapshots",
                        controller=self.resources['snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
               
        #get the list of workload snapshots
        mapper.connect("snapshots2",
                       "/{project_id}/workloads/{workload_id}/snapshots",
                       controller=self.resources['snapshots'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the detail list of workload snapshots
        mapper.connect("snapshot3",
                       "/{project_id}/workloads/{workload_id}/snapshots/detail",
                       controller=self.resources['snapshots'],
                       action='detail',
                       conditions={"method": ['GET']})  
        
        #get the specified snapshot
        mapper.connect("snapshot",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}",
                       controller=self.resources['snapshots'],
                       action='show',
                       conditions={"method": ['GET']}) 
        
        #restore a snapshot
        mapper.connect("restore",
                       "/{project_id}/snapshots/{id}",
                       controller=self.resources['snapshots'],
                       action='restore',
                       conditions={"method": ['POST']}) 
        
        #restore a snapshot
        mapper.connect("restore2",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}",
                       controller=self.resources['snapshots'],
                       action='restore',
                       conditions={"method": ['POST']})     