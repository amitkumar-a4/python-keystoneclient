# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmanager.openstack.common import log as logging
from workloadmanager.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model workloadmanager API responses as a python dictionary."""

    _collection_name = "workloads"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, workloads):
        """Show a list of workloads without many details."""
        return self._list_view(self.summary, request, workloads)

    def detail_list(self, request, workloads):
        """Detailed view of a list of workloads ."""
        return self._list_view(self.detail, request, workloads)

    def summary(self, request, workload):
        """Generic, non-detailed view of a workload."""
        return {
            'workload': {
                'id': workload['id'],
                'name': workload['display_name'],
                'links': self._get_links(request,
                                         workload['id']),
            },
        }

    def detail(self, request, workload):
        """Detailed view of a single workload."""
        return {
            'workload': {
                'created_at': workload.get('created_at'),
                'updated_at': workload.get('updated_at'),
                'id': workload.get('id'),
                'user_id': workload.get('user_id'),
                'project_id': workload.get('project_id'),
                'host': workload.get('host'),
                'availability_zone': workload.get('availability_zone'),
                'vault_service': workload.get('vault_service'),
                'name': workload.get('display_name'),
                'description': workload.get('display_description'),
                'interval': workload.get('hours'),
                'status': workload.get('status'),
                'links': self._get_links(request, workload['id'])
            }
        }

    def _list_view(self, func, request, workloads):
        """Provide a view for a list of workloads."""
        workloads_list = [func(request, workload)['workload'] for workload in workloads]
        workloads_links = self._get_collection_links(request,
                                                   workloads,
                                                   self._collection_name)
        workloads_dict = dict(workloads=workloads_list)

        if workloads_links:
            workloads_dict['workloads_links'] = workloads_links

        return workloads_dict
