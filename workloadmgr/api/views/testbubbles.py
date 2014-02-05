# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model testbubbles API responses as a python dictionary."""

    _collection_name = "testbubbles"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, testbubbles):
        """Show a list of testbubbles without many details."""
        return self._list_view(self.summary, request, testbubbles)

    def detail_list(self, request, testbubbles):
        """Detailed view of a list of testbubbles ."""
        return self._list_view(self.detail, request, testbubbles)

    def summary(self, request, testbubble):
        """Generic, non-detailed view of a testbubble."""
        d = {}
        d['id'] = testbubble['id']
        d['status'] = testbubble['status']
        d['snapshot_id'] = testbubble['snapshot_id']
        if 'instances' in testbubble:
            instances = []
            for vm in testbubble['instances']:
                instances.append({'id':vm['vm_id'],
                                  'name':vm['vm_name'],
                                  'status':vm['status']
                                  }) 
            d['instances'] = instances
        d['links'] = self._get_links(request, testbubble['id'])
        return {'testbubble': d}        


    def detail(self, request, testbubble):
        """Detailed view of a single testbubble."""
        d = {}
        d['id'] = testbubble['id']
        d['created_at'] = testbubble['created_at']
        d['updated_at'] = testbubble['created_at']
        d['user_id'] = testbubble['user_id']
        d['project_id'] = testbubble['project_id']
        d['status'] = testbubble['status']
        d['snapshot_id'] = testbubble['snapshot_id']
        if 'instances' in testbubble:
            instances = []
            for vm in testbubble['instances']:
                instances.append({'id':vm['vm_id'],
                                  'name':vm['vm_name'],
                                  'status':vm['status']
                                  }) 
            d['instances'] = instances
        d['links'] = self._get_links(request, testbubble['id'])
        return {'testbubble': d}        

    def _list_view(self, func, request, testbubbles):
        """Provide a view for a list of testbubbles."""
        testbubbles_list = [func(request, testbubble)['testbubble'] for testbubble in testbubbles]
        testbubbles_links = self._get_collection_links(request,
                                                   testbubbles,
                                                   self._collection_name)
        testbubbles_dict = dict(testbubbles=testbubbles_list)

        if testbubbles_links:
            testbubbles_dict['testbubbles_links'] = testbubbles_links

        return testbubbles_dict
