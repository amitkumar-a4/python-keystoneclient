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
from workloadmgr.api.v1 import restores
from workloadmgr.api.v1 import testbubbles

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
        mapper.resource("workloads", "workloads",
                        controller=self.resources['workloads'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
        #take a snapshot of the workload
        mapper.connect("workload_snapshot",
                       "/{project_id}/workloads/{id}",
                       controller=self.resources['workloads'],
                       action='snapshot',
                       conditions={"method": ['POST']})
        
        ###################################################################################################        
        self.resources['snapshots'] = snapshots.create_resource(ext_mgr)
        #detail list of snapshots
        mapper.resource("snapshots_1", "snapshots",
                        controller=self.resources['snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
               
        #get the list of workload snapshots
        mapper.connect("snapshots_2",
                       "/{project_id}/workloads/{workload_id}/snapshots",
                       controller=self.resources['snapshots'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the detail list of workload snapshots
        mapper.connect("snapshots_3",
                       "/{project_id}/workloads/{workload_id}/snapshots/detail",
                       controller=self.resources['snapshots'],
                       action='detail',
                       conditions={"method": ['GET']})  
        
        #get the specified snapshot
        mapper.connect("snapshot_4",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}",
                       controller=self.resources['snapshots'],
                       action='show',
                       conditions={"method": ['GET']}) 
        
        #restore a snapshot
        mapper.connect("restore_snapshot_1",
                       "/{project_id}/snapshots/{id}",
                       controller=self.resources['snapshots'],
                       action='restore',
                       conditions={"method": ['POST']}) 
        
        #restore a snapshot
        mapper.connect("restore_snapshot_2",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}",
                       controller=self.resources['snapshots'],
                       action='restore',
                       conditions={"method": ['POST']})     
        
        ###################################################################################################
        self.resources['restores'] = restores.create_resource(ext_mgr)
        #detail list of restores
        mapper.resource("restores_1", "restores",
                        controller=self.resources['restores'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
               
        #get the list of workload snapshot restores
        mapper.connect("restores_2",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/restores",
                       controller=self.resources['restores'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the detail list of workload snapshot restores
        mapper.connect("restores_3",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/restores/detail",
                       controller=self.resources['restores'],
                       action='detail',
                       conditions={"method": ['GET']})  
        
        #get the specified snapshot
        mapper.connect("restore_4",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/restores/{id}",
                       controller=self.resources['restores'],
                       action='show',
                       conditions={"method": ['GET']})
        
        #restore a snapshot
        mapper.connect("restore_5",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}/restores",
                       controller=self.resources['snapshots'],
                       action='restore',
                       conditions={"method": ['POST']})  
        
        ###################################################################################################
        self.resources['testbubbles'] = testbubbles.create_resource(ext_mgr)
        #detail list of testbubbles
        mapper.resource("testbubbles_1", "testbubbles",
                        controller=self.resources['testbubbles'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
               
        #get the list of workload snapshot testbubbles
        mapper.connect("testbubbles_2",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/testbubbles",
                       controller=self.resources['testbubbles'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the detail list of workload snapshot testbubbles
        mapper.connect("testbubbles_3",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/testbubbles/detail",
                       controller=self.resources['testbubbles'],
                       action='detail',
                       conditions={"method": ['GET']})  
        
        #get the specified snapshot
        mapper.connect("testbubble_4",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/testbubbles/{id}",
                       controller=self.resources['testbubbles'],
                       action='show',
                       conditions={"method": ['GET']})  
        
        #test restore a snapshot
        mapper.connect("testbubble_5",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}/testbubbles",
                       controller=self.resources['snapshots'],
                       action='test_restore',
                       conditions={"method": ['POST']}) 
        