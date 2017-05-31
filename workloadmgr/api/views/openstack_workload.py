# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common
import pickle


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model workload API responses as a python dictionary."""

    _collection_name = "openstack_workload"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, openstack_workloads):
        """Show a list of openstack_workloads without many details."""
        return self._list_view(self.summary, request, openstack_workloads)

    def detail_list(self, request, openstack_workloads, api=None):
        """Detailed view of a list of workloads ."""
        return self._list_view(self.detail, request, openstack_workloads)

    def summary(self, request, openstack_workload, api=None):
        """Generic, non-detailed view of a openstack_workloads."""
        joschedule = pickle.loads(openstack_workload.get('jobschedule'))
        return {
            'openstack_workload': {

                'id': openstack_workload.get('id'),
                'created_at': openstack_workload.get('created_at'),
                'updated_at': openstack_workload.get('updated_at'),
                'status': openstack_workload.get('status'),
                'jobschedule_enabled': joschedule.get('enabled'),
                'retention_policy': joschedule.get('retention_policy_value'),
                'scheduler_interval': joschedule.get('interval'),
                'start_time': joschedule.get('start_time'),
                'start_date': joschedule.get('start_date'),
                'end_date': joschedule.get('end_date')

            }
        }

    def detail(self, request, openstack_workload, api=None):
        """Detailed view of a single openstack_workloads."""
        joschedule = pickle.loads(openstack_workload.get('jobschedule'))
        return {
            'openstack_workload': {
                'id': openstack_workload.get('id'),
                'created_at': openstack_workload.get('created_at'),
                'updated_at': openstack_workload.get('updated_at'),
                'status': openstack_workload.get('status'),
                'jobschedule_enabled': joschedule.get('enabled'),
                'retention_policy': joschedule.get('retention_policy_value'),
                'scheduler_interval': joschedule.get('interval'),
                'start_time': joschedule.get('start_time'),
                'start_date': joschedule.get('start_date'),
                'end_date': joschedule.get('end_date'),
                'vault_storage_path': openstack_workload.get('vault_storage_path'),
                'storage_backend': openstack_workload.get('storage_backend'),
                }
        }

    def _list_view(self, func, request, workloads):
        """Provide a view for a list of openstack workloads."""
        workloads_list = [func(request, workload)['workload'] for workload in workloads]
        workloads_dict = dict(openstack_workloads=workloads_list)

        return workloads_dict
