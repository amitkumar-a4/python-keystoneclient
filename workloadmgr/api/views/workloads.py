# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model workload API responses as a python dictionary."""

    _collection_name = "workloads"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, workloads):
        """Show a list of workloads without many details."""
        return self._list_view(self.summary, request, workloads)

    def detail_list(self, request, workloads, api=None):
        """Detailed view of a list of workloads ."""
        return self._list_view(self.detail, request, workloads, api)

    def summary(self, request, workload, api=None):
        """Generic, non-detailed view of a workload."""
        return {
            'workload': {
                'project_id': workload.get('project_id'),
                'user_id': workload.get('user_id'),
                'created_at': workload.get('created_at'),
                'id': workload['id'],
                'name': workload['display_name'],
                'snapshots_info': '',
                'description': workload['display_description'],
                'workload_type_id': workload['workload_type_id'],
                'status': workload['status'],
                'created_at': workload.get('created_at'),
                'updated_at': workload.get('updated_at'),
                #'storage_usage': workload['storage_usage'],
                #'instances': workload['instances'],
                'links': self._get_links(request, workload['id']),
            },
        }

    def restore_summary(self, request, restore, api=None):
        """Generic, non-detailed view of a restore."""
        return {
            'restore': {
                'workload_id': restore['workload_id'],
                'instance_id': restore['instance_id'],
            },
        }

    def detail(self, request, workload, api=None):
        """Detailed view of a single workload."""
        context = request.environ['workloadmgr.context']
        if api is not None:
            workload = api.workload_show(context, workload_id=workload.id)
        return {
            'workload': {
                'created_at': workload.get('created_at'),
                'updated_at': workload.get('updated_at'),
                'id': workload.get('id'),
                'user_id': workload.get('user_id'),
                'project_id': workload.get('project_id'),
                'availability_zone': workload.get('availability_zone'),
                'workload_type_id': workload.get('workload_type_id'),
                'name': workload.get('display_name'),
                'description': workload.get('display_description'),
                'interval': workload.get('hours'),
                'storage_usage': workload.get('storage_usage'),
                'instances': workload.get('instances'),
                'metadata': workload.get('metadata'),
                'jobschedule': workload.get('jobschedule'),
                'status': workload.get('status'),
                'error_msg': workload.get('error_msg'),
                'links': self._get_links(request, workload['id'])
            }
        }

    def _list_view(self, func, request, workloads, api=None):
        """Provide a view for a list of workloads."""
        workloads_list = [func(request, workload, api)['workload']
                          for workload in workloads]
        workloads_links = self._get_collection_links(request,
                                                     workloads,
                                                     self._collection_name)
        workloads_dict = dict(workloads=workloads_list)

        if workloads_links:
            workloads_dict['workloads_links'] = workloads_links

        return workloads_dict
