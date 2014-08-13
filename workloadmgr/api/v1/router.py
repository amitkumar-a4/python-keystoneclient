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
from workloadmgr.api.v1 import workloadtypes

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
        ###################################################################################################
        self.resources['workload_types'] = workloadtypes.create_resource(ext_mgr)
        #detail list of workload_types
        mapper.resource("workload_types_1", "workload_types",
                        controller=self.resources['workload_types'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
               
        #get the list of workload_types
        mapper.connect("workload_types_2",
                       "/{project_id}/workload_types",
                       controller=self.resources['workload_types'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the detail list of workload_types
        mapper.connect("workload_types_3",
                       "/{project_id}/workload_types/detail",
                       controller=self.resources['workload_types'],
                       action='detail',
                       conditions={"method": ['GET']})  
        
        #get the specified workload_type
        mapper.connect("workload_types_4",
                       "/{project_id}/workload_types/{id}",
                       controller=self.resources['workload_types'],
                       action='show',
                       conditions={"method": ['GET']})  
        
        #delete a workload_type
        mapper.connect("delete_workload_types",
                       "/{project_id}/workload_types/{id}",
                       controller=self.resources['workload_types'],
                       action='delete',
                       conditions={"method": ['DELETE']})    
        
        #discover workload_type instances
        mapper.connect("workload_types_discover_instances",
                       "/{project_id}/workload_types/{id}/discover_instances",
                       controller=self.resources['workload_types'],
                       action='discover_instances',
                       conditions={"method": ['POST']})
                
        ###################################################################################################
        self.resources['workloads'] = workloads.create_resource()
        #detail list of workloads
        mapper.resource("workloads_1", "workloads",
                        controller=self.resources['workloads'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        
        #get the list of workloads
        mapper.connect("workloads_2",
                       "/{project_id}/workloads",
                       controller=self.resources['workloads'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the detail list of workloads
        mapper.connect("workloads_3",
                       "/{project_id}/workloads/detail",
                       controller=self.resources['workloads'],
                       action='detail',
                       conditions={"method": ['GET']})  
        
        #get the specified workload
        mapper.connect("workloads_4",
                       "/{project_id}/workloads/{id}",
                       controller=self.resources['workloads'],
                       action='show',
                       conditions={"method": ['GET']})        
        
        #take a snapshot of the workload
        mapper.connect("workload_snapshot",
                       "/{project_id}/workloads/{id}",
                       controller=self.resources['workloads'],
                       action='snapshot',
                       conditions={"method": ['POST']})
        
        #pause and resume workload
        mapper.connect("workloads_pause",
                       "/{project_id}/workloads/{id}/pause",
                       controller=self.resources['workloads'],
                       action='pause',
                       conditions={"method": ['POST']})
        
        mapper.connect("workloads_resume",
                       "/{project_id}/workloads/{id}/resume",
                       controller=self.resources['workloads'],
                       action='resume',
                       conditions={"method": ['POST']})
                   
        mapper.connect("workloads_update",
                       "/{project_id}/workloads/{id}",
                       controller=self.resources['workloads'],
                       action='update',
                       conditions={"method": ['PUT']})
        
        #get the workflow of a workload
        mapper.connect("workloads_workflow",
                       "/{project_id}/workloads/{id}/workflow",
                       controller=self.resources['workloads'],
                       action='get_workflow',
                       conditions={"method": ['GET']})   
        
        #get the topology of a workload
        mapper.connect("workloads_topology",
                       "/{project_id}/workloads/{id}/topology",
                       controller=self.resources['workloads'],
                       action='get_topology',
                       conditions={"method": ['GET']})
        
        #unlock workload
        mapper.connect("workloads_unlock",
                       "/{project_id}/workloads/{id}/unlock",
                       controller=self.resources['workloads'],
                       action='unlock',
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

        #delete a snapshot
        mapper.connect("delete_snapshot",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}",
                       controller=self.resources['snapshots'],
                       action='delete',
                       conditions={"method": ['DELETE']})     
                
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
        
        #get the specified restore
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
        
        #delete a restore
        mapper.connect("delete_restore",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/restores/{id}",
                       controller=self.resources['restores'],
                       action='delete',
                       conditions={"method": ['DELETE']})         
        
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
        
        #get the specified testbubble
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
        
        #delete a testbubble
        mapper.connect("delete_testbubble",
                       "/{project_id}/workloads/{workload_id}/snapshots/{snapshot_id}/testbubbles/{id}",
                       controller=self.resources['testbubbles'],
                       action='delete',
                       conditions={"method": ['DELETE']})         
        
