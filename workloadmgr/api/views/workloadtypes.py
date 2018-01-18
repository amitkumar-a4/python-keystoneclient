# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model workloadtypes API responses as a python dictionary."""

    _collection_name = "workloadtypes"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, workloadtypes):
        """Show a list of workloadtypes without many details."""
        return self._list_view(self.summary, request, workloadtypes)

    def detail_list(self, request, workloadtypes):
        """Detailed view of a list of workloadtypes ."""
        return self._list_view(self.detail, request, workloadtypes)

    def summary(self, request, workloadtype):
        """Generic, non-detailed view of a workloadtype."""
        d = {}
        d['id'] = workloadtype['id']
        d['status'] = workloadtype['status']
        d['links'] = self._get_links(request, workloadtype['id'])
        d['name'] = workloadtype['display_name']
        d['description'] = workloadtype['display_description']
        d['is_public'] = workloadtype['is_public']
        return {'workload_type': d}

    def detail(self, request, workloadtype):
        """Detailed view of a single workloadtype."""
        d = {}
        d['id'] = workloadtype['id']
        d['created_at'] = workloadtype['created_at']
        d['updated_at'] = workloadtype['created_at']
        d['user_id'] = workloadtype['user_id']
        d['project_id'] = workloadtype['project_id']
        d['status'] = workloadtype['status']
        d['links'] = self._get_links(request, workloadtype['id'])
        d['name'] = workloadtype['display_name']
        d['description'] = workloadtype['display_description']
        d['is_public'] = workloadtype['is_public']
        d['metadata'] = workloadtype['metadata']
        return {'workload_type': d}

    def _list_view(self, func, request, workloadtypes):
        """Provide a view for a list of workloadtypes."""
        workloadtypes_list = [func(request, workloadtype)[
            'workload_type'] for workloadtype in workloadtypes]
        workloadtypes_links = self._get_collection_links(request,
                                                         workloadtypes,
                                                         self._collection_name)
        workloadtypes_dict = dict(workload_types=workloadtypes_list)

        if workloadtypes_links:
            workloadtypes_dict['workloadtypes_links'] = workloadtypes_links

        return workloadtypes_dict
