# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model restores API responses as a python dictionary."""

    _collection_name = "restores"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, restores):
        """Show a list of restores without many details."""
        return self._list_view(self.summary, request, restores)

    def detail_list(self, request, restores):
        """Detailed view of a list of restores ."""
        return self._list_view(self.detail, request, restores)

    def summary(self, request, restore):
        """Generic, non-detailed view of a restore."""
        d = {}
        d['id'] = restore['id']
        d['status'] = restore['status']
        d['restore_type'] = restore['restore_type']
        d['snapshot_id'] = restore['snapshot_id']
        if 'workload_id' in restore:
            d['workload_id'] = restore['workload_id']
        if 'instances' in restore:
            d['instances'] = restore['instances']
        if 'networks' in restore:
            d['networks'] = restore['networks']
        if 'subnets' in restore:
            d['subnets'] = restore['subnets']
        if 'routers' in restore:
            d['routers'] = restore['routers']  
        if 'flavors' in restore:
            d['flavors'] = restore['flavors']
        if 'flavors' in restore:
            d['flavors'] = restore['flavors']             
        d['links'] = self._get_links(request, restore['id'])
        d['name'] = restore['display_name']
        d['description'] =  restore['display_description']
        d['host'] = restore['host']
                
        return {'restore': d}        


    def detail(self, request, restore):
        """Detailed view of a single restore."""
        d = {}
        d['id'] = restore['id']
        d['created_at'] = restore['created_at']
        d['updated_at'] = restore['created_at']
        d['finished_at'] = restore['finished_at']
        d['user_id'] = restore['user_id']
        d['project_id'] = restore['project_id']
        d['status'] = restore['status']
        d['restore_type'] = restore['restore_type']
        d['snapshot_id'] = restore['snapshot_id']
        if 'workload_id' in restore:
            d['workload_id'] = restore['workload_id']
        if 'instances' in restore:
            d['instances'] = restore['instances']
        if 'networks' in restore:
            d['networks'] = restore['networks']
        if 'subnets' in restore:
            d['subnets'] = restore['subnets']
        if 'routers' in restore:
            d['routers'] = restore['routers']  
        d['links'] = self._get_links(request, restore['id'])
        d['name'] = restore['display_name']
        d['description'] =  restore['display_description']
        d['host'] = restore['host']
        d['progress_percent'] =  restore['progress_percent']          
        d['progress_msg'] =  restore['progress_msg'] 
        d['warning_msg'] =  restore['warning_msg']
        d['error_msg'] =  restore['error_msg']                   
        return {'restore': d}        

    def _list_view(self, func, request, restores):
        """Provide a view for a list of restores."""
        restores_list = [func(request, restore)['restore'] for restore in restores]
        restores_links = self._get_collection_links(request,
                                                   restores,
                                                   self._collection_name)
        restores_dict = dict(restores=restores_list)

        if restores_links:
            restores_dict['restores_links'] = restores_links

        return restores_dict
