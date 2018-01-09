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
        if 'workload_id' in testbubble:
            d['workload_id'] = testbubble['workload_id']
        if 'instances' in testbubble:
            d['instances'] = testbubble['instances']
        if 'networks' in testbubble:
            d['networks'] = testbubble['networks']
        if 'subnets' in testbubble:
            d['subnets'] = testbubble['subnets']
        if 'routers' in testbubble:
            d['routers'] = testbubble['routers']
        if 'flavors' in testbubble:
            d['flavors'] = testbubble['flavors']
        d['links'] = self._get_links(request, testbubble['id'])
        d['name'] = testbubble['display_name']
        d['description'] = testbubble['display_description']
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
        if 'workload_id' in testbubble:
            d['workload_id'] = testbubble['workload_id']
        if 'instances' in testbubble:
            d['instances'] = testbubble['instances']
        if 'networks' in testbubble:
            d['networks'] = testbubble['networks']
        if 'subnets' in testbubble:
            d['subnets'] = testbubble['subnets']
        if 'routers' in testbubble:
            d['routers'] = testbubble['routers']
        if 'flavors' in testbubble:
            d['flavors'] = testbubble['flavors']
        d['links'] = self._get_links(request, testbubble['id'])
        d['name'] = testbubble['display_name']
        d['description'] = testbubble['display_description']
        d['progress_percent'] = testbubble['progress_percent']
        d['progress_msg'] = testbubble['progress_msg']
        d['warning_msg'] = testbubble['warning_msg']
        d['error_msg'] = testbubble['error_msg']

        return {'testbubble': d}

    def _list_view(self, func, request, testbubbles):
        """Provide a view for a list of testbubbles."""
        testbubbles_list = [func(request, testbubble)['testbubble']
                            for testbubble in testbubbles]
        testbubbles_links = self._get_collection_links(request,
                                                       testbubbles,
                                                       self._collection_name)
        testbubbles_dict = dict(testbubbles=testbubbles_list)

        if testbubbles_links:
            testbubbles_dict['testbubbles_links'] = testbubbles_links

        return testbubbles_dict
