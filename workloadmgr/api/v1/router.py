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
from workloadmgr.api.v1 import settings
from workloadmgr.api.v1 import trusts
from workloadmgr.api.v1 import tasks
from workloadmgr.api.v1 import filesearch
from workloadmgr.api.v1 import workload_transfer as transfers
from workloadmgr.api.v1 import global_job_scheduler
from workloadmgr.api.v1 import openstack_config_backup
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
  
        ##################################################################################################
        self.resources['file_search'] = filesearch.create_resource(ext_mgr)
        #get status of file search
        mapper.connect("file_search",
                       "/{project_id}/search/{search_id}",
                       controller=self.resources['file_search'],
                       action='show',
                       conditions={"method": ['GET']})

        #post file search
        mapper.connect("file_search",
                       "/{project_id}/search",
                       controller=self.resources['file_search'],
                       action='search',
                       conditions={"method": ['POST']})

        ###################################################################################################
        self.resources['workload_types'] = workloadtypes.create_resource(ext_mgr)
        self.resources['tasks'] = tasks.create_resource(ext_mgr)
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

        #discover workload_type instances
        mapper.connect("workload_types_topology",
                       "/{project_id}/workload_types/{id}/topology",
                       controller=self.resources['workload_types'],
                       action='topology',
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

        #import workloads
        mapper.connect("workloads_import_list",
                       "/{project_id}/workloads/get_list/import_workloads",
                       controller=self.resources['workloads'],
                       action='get_import_workloads_list',
                       conditions={"method": ['GET']})
        
        #import workloads
        mapper.connect("workloads_import",
                       "/{project_id}/workloads/import_workloads",
                       controller=self.resources['workloads'],
                       action='import_workloads',
                       conditions={"method": ['POST']})  
        
        #workload settings
        mapper.connect("workloads_settings",
                       "/{project_id}/workloads/settings",
                       controller=self.resources['workloads'],
                       action='settings',
                       conditions={"method": ['POST']})

        #workload trusts
        mapper.connect("workloads_trusts",
                       "/{project_id}/workloads/trusts",
                       controller=self.resources['workloads'],
                       action='trusts',
                       conditions={"method": ['POST']})

        #workload license
        mapper.connect("workloads_license",
                       "/{project_id}/workloads/license",
                       controller=self.resources['workloads'],
                       action='license_create',
                       conditions={"method": ['POST']})

        #workload license
        mapper.connect("workloads_license_get",
                       "/{project_id}/workloads/metrics/license",
                       controller=self.resources['workloads'],
                       action='license_list',
                       conditions={"method": ['GET']})
       
        #Test email configuration
        mapper.connect("test_email",
                        "/{project_id}/workloads/email/test_email",
                        controller=self.resources['workloads'],
                        action='test_email',
                        conditions={"method": ['GET']})
 
        #get workloadmanager nodes
        mapper.connect("workloads_nodes",
                       "/{project_id}/workloads/metrics/nodes",
                       controller=self.resources['workloads'],
                       action='get_nodes',
                       conditions={"method": ['GET']})             
        
        #get contego service status
        mapper.connect("contego_status",
                       "/{project_id}/workloads/metrics/contego_status",
                       controller=self.resources['workloads'],
                       action='get_contego_status',
                       conditions={"method": ['GET']})
                       
        #remove workloadmanager node
        mapper.connect("workload_remove_node",
                       "/{project_id}/workloads/remove_node/{ip}",
                       controller=self.resources['workloads'],
                       action='remove_node',
                       conditions={"method": ['DELETE']})

        #remove workloadmanager node
        mapper.connect("workload_add_node",
                       "/{project_id}/workloads/add_node",
                       controller=self.resources['workloads'],
                       action='add_node',
                       conditions={"method": ['POST']})

        #get total storage used
        mapper.connect("workloads_storage_usage",
                       "/{project_id}/workloads/metrics/storage_usage",
                       controller=self.resources['workloads'],
                       action='get_storage_usage',
                       conditions={"method": ['GET']})  
        
        #get recent activities
        mapper.connect("workloads_recentactivities",
                       "/{project_id}/workloads/metrics/recentactivities",
                       controller=self.resources['workloads'],
                       action='get_recentactivities',
                       conditions={"method": ['GET']})
        
        #get recent activities
        mapper.connect("workloads_auditlog",
                       "/{project_id}/workloads/audit/auditlog",
                       controller=self.resources['workloads'],
                       action='get_auditlog',
                       conditions={"method": ['GET']})                    

        #get the specified workload
        mapper.connect("workloads_4",
                       "/{project_id}/workloads/{id}",
                       controller=self.resources['workloads'],
                       action='show',
                       conditions={"method": ['GET']})        
        #import workloads
        mapper.connect("workloads_import",
                       "/{project_id}/workloads/import_workloads",
                       controller=self.resources['workloads'],
                       action='import_workloads',
                       conditions={"method": ['POST']})         

        #reassign workloads
        mapper.connect("workloads_reassign",
                       "/{project_id}/workloads/reasign_workloads",
                       controller=self.resources['workloads'],
                       action='workloads_reassign',
                       conditions={"method": ['POST']})

        #list orphaned workloads
        mapper.connect("orphaned_workload_list",
                       "/{project_id}/workloads/{path_info:orphan_workloads}/",
                       controller=self.resources['workloads'],
                       action='get_orphaned_workloads_list',
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

        #reset workload
        mapper.connect("workloads_reset",
                       "/{project_id}/workloads/{id}/reset",
                       controller=self.resources['workloads'],
                       action='reset',
                       conditions={"method": ['POST']})         

        #discover workload instances
        mapper.connect("workloads_discover_instances",
                       "/{project_id}/workloads/{id}/discover_instances",
                       controller=self.resources['workloads'],
                       action='discover_instances',
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

        #cancel snapshot
        mapper.connect("cancel_snapshot",
                       "/{project_id}/snapshots/{id}/cancel",
                       controller=self.resources['snapshots'],
                       action='snapshot_cancel',
                       conditions={"method": ['GET']})

        #mount a snapshot
        mapper.connect("mount_snapshot_1",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}/mount",
                       controller=self.resources['snapshots'],
                       action='mount',
                       conditions={"method": ['POST']}) 
        
        mapper.connect("mount_snapshot_2",
                       "/{project_id}/snapshots/{id}/mount",
                       controller=self.resources['snapshots'],
                       action='mount',
                       conditions={"method": ['POST']})            
        
        #dismount a snapshot
        mapper.connect("dismount_snapshot1",
                       "/{project_id}/workloads/{workload_id}/snapshots/{id}/dismount",
                       controller=self.resources['snapshots'],
                       action='dismount',
                       conditions={"method": ['POST']}) 
        
        mapper.connect("dismount_snapshot2",
                       "/{project_id}/snapshots/{id}/dismount",
                       controller=self.resources['snapshots'],
                       action='dismount',
                       conditions={"method": ['POST']})                     

        #list mounted snapshots
        mapper.connect("mounted_snapshots_list",
                       "/{project_id}/workloads/{workload_id}/snapshots/mounted/list",
                       controller=self.resources['snapshots'],
                       action='mounted_list',
                       conditions={"method": ['GET']})

        #list mounted snapshots
        mapper.connect("mounted_snapshots_list",
                       "/{project_id}/snapshots/mounted/list",
                       controller=self.resources['snapshots'],
                       action='mounted_list',
                       conditions={"method": ['GET']})


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
        
        #cancel a restore
        mapper.connect("cancel_restore",
                       "/{project_id}/restores/{id}/cancel",
                       controller=self.resources['restores'],
                       action='restore_cancel',
                       conditions={"method": ['GET']})
                
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
        
        ###################################################################################################
        self.resources['settings'] = settings.create_resource(ext_mgr)
        
        #create settings
        mapper.connect("create_settings",
                       "/{project_id}/settings",
                       controller=self.resources['settings'],
                       action='create',
                       conditions={"method": ['POST']}) 
        
        #update settings
        mapper.connect("update_settings",
                       "/{project_id}/settings",
                       controller=self.resources['settings'],
                       action='update',
                       conditions={"method": ['PUT']})                   

        #get the list of settings
        mapper.connect("get_settings_list",
                       "/{project_id}/settings",
                       controller=self.resources['settings'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the specified setting
        mapper.connect("get_setting",
                       "/{project_id}/settings/{name}",
                       controller=self.resources['settings'],
                       action='show',
                       conditions={"method": ['GET']})
        
        #delete a setting
        mapper.connect("delete_setting",
                       "/{project_id}/settings/{name}",
                       controller=self.resources['settings'],
                       action='delete',
                       conditions={"method": ['DELETE']}) 

        ###################################################################################################
        self.resources['trusts'] = trusts.create_resource(ext_mgr)
        
        #create settings
        mapper.connect("create_trust",
                       "/{project_id}/trusts",
                       controller=self.resources['trusts'],
                       action='create',
                       conditions={"method": ['POST']}) 
        
        #get the list of settings
        mapper.connect("get_trusts_list",
                       "/{project_id}/trusts",
                       controller=self.resources['trusts'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the specified setting
        mapper.connect("get_trusts",
                       "/{project_id}/trusts/{name}",
                       controller=self.resources['trusts'],
                       action='show',
                       conditions={"method": ['GET']})
        
        #delete a setting
        mapper.connect("delete_trusts",
                       "/{project_id}/trusts/{name}",
                       controller=self.resources['trusts'],
                       action='delete',
                       conditions={"method": ['DELETE']}) 

        ###################################################################################################
        self.resources['global_job_scheduler'] = global_job_scheduler.create_resource(ext_mgr)

        #enable global job scheduler
        mapper.connect("enable_global_job_scheduler",
                       "/{project_id}/global_job_scheduler/enable",
                       controller=self.resources['global_job_scheduler'],
                       action='enable',
                       conditions={"method": ['POST']}) 

        #get global job scheduler status
        mapper.connect("get_global_job_scheduler_status",
                       "/{project_id}/global_job_scheduler",
                       controller=self.resources['global_job_scheduler'],
                       action='index',
                       conditions={"method": ['GET']}) 

        #disable global job scheduler
        mapper.connect("disable_global_job_scheduler",
                       "/{project_id}/global_job_scheduler/disable",
                       controller=self.resources['global_job_scheduler'],
                       action='disable',
                       conditions={"method": ['POST']}) 

        ###################################################################################################
        self.resources['transfers'] = transfers.create_resource(ext_mgr)
        
        #create settings
        mapper.connect("create_transfer",
                       "/{project_id}/transfers",
                       controller=self.resources['transfers'],
                       action='create',
                       conditions={"method": ['POST']}) 

        #create settings
        mapper.connect("accept_transfer",
                       "/{project_id}/transfers/{id}/accept",
                       controller=self.resources['transfers'],
                       action='accept',
                       conditions={"method": ['POST']}) 

        mapper.connect("complete_transfer",
                       "/{project_id}/transfers/{id}/complete",
                       controller=self.resources['transfers'],
                       action='complete',
                       conditions={"method": ['POST']}) 

        mapper.connect("abort_transfer",
                       "/{project_id}/transfers/{id}/abort",
                       controller=self.resources['transfers'],
                       action='abort',
                       conditions={"method": ['POST']}) 
        
        #get the list of settings
        mapper.connect("get_transfers_list",
                       "/{project_id}/transfers",
                       controller=self.resources['transfers'],
                       action='index',
                       conditions={"method": ['GET']}) 
        
        #get the specified setting
        mapper.connect("get_transfers",
                       "/{project_id}/transfers/{id}",
                       controller=self.resources['transfers'],
                       action='show',
                       conditions={"method": ['GET']})
        
        #delete a setting
        mapper.connect("delete_transfers",
                       "/{project_id}/transfers/{id}",
                       controller=self.resources['transfers'],
                       action='delete',
                       conditions={"method": ['DELETE']}) 

        ###################################################################################################
        #get the specified task
        mapper.connect("get_task",
                       "/{project_id}/task/{id}",
                       controller=self.resources['tasks'],
                       action='index',
                       conditions={"method": ['GET']})

        mapper.connect("get_tasks",
                       "/{project_id}/tasks",
                       controller=self.resources['tasks'],
                       action='get_tasks',
                       conditions={"method": ['GET']})

        ###################################################################################################
        #Openstack configuration backup
        self.resources['openstack_config_backup'] = openstack_config_backup.create_resource(ext_mgr)
        
        # reassign workloads
        mapper.connect("openstack_config_workload_update",
                       "/{project_id}/openstack_config",
                       controller=self.resources['openstack_config_backup'],
                       action='openstack_config_workload',
                       conditions={"method": ['PUT']})

        mapper.connect("openstack_config_workload_show",
                       "/{project_id}/openstack_config_show",
                       controller=self.resources['openstack_config_backup'],
                       action='openstack_config_workload_show',
                       conditions={"method": ['GET']})

        mapper.connect("openstack_config_snapshot",
                       "/{project_id}/openstack_config_snapshot",
                       controller=self.resources['openstack_config_backup'],
                       action='openstack_config_snapshot',
                       conditions={"method": ['POST']})

        mapper.connect("openstack_config_snapshot_show",
                       "/{project_id}/openstack_config_snapshot/{id}",
                       controller=self.resources['openstack_config_backup'],
                       action='openstack_config_snapshot_show',
                       conditions={"method": ['GET']})

        mapper.connect("openstack_config_snapshot_list",
                       "/{project_id}/openstack_config_snapshots",
                       controller=self.resources['openstack_config_backup'],
                       action='openstack_config_snapshot_list',
                       conditions={"method": ['GET']})

        mapper.connect("openstack_config_snapshot_delete",
                       "/{project_id}/openstack_config_snapshot/{id}",
                       controller=self.resources['openstack_config_backup'],
                       action='openstack_config_snapshot_delete',
                       conditions={"method": ['DELETE']})

