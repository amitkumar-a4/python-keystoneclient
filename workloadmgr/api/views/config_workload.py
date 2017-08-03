# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common
import pickle


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model workload API responses as a python dictionary."""

    _collection_name = "config_workload"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, config_workloads):
        """Show a list of config_workloads without many details."""
        return self._list_view(self.summary, request, config_workloads)

    def detail_list(self, request, config_workloads, api=None):
        """Detailed view of a list of workloads ."""
        return self._list_view(self.detail, request, config_workloads)

    def summary(self, request, config_workload, api=None):
        """Generic, non-detailed view of a config_workloads."""
        joschedule = pickle.loads(config_workload.get('jobschedule'))
        return {
            'config_workload': {

                'id': config_workload.get('id'),
                'created_at': config_workload.get('created_at'),
                'updated_at': config_workload.get('updated_at'),
                'status': config_workload.get('status'),
                'jobschedule_enabled': joschedule.get('enabled'),
                'retention_policy': joschedule.get('retention_policy_value'),
                'scheduler_interval': joschedule.get('interval'),
                'start_time': joschedule.get('start_time'),
                'start_date': joschedule.get('start_date'),
                'end_date': joschedule.get('end_date')

            }
        }

    def detail(self, request, config_workload, api=None):
        """Detailed view of a single config_workloads."""
        joschedule = pickle.loads(config_workload.get('jobschedule'))
        return {
            'config_workload': {
                'id': config_workload.get('id'),
                'created_at': config_workload.get('created_at'),
                'updated_at': config_workload.get('updated_at'),
                'user_id': config_workload.get('user_id'),
                'project_id': config_workload.get('project_id'),
                'status': config_workload.get('status'),
                'jobschedule_enabled': joschedule.get('enabled'),
                'retention_policy': joschedule.get('retention_policy_value'),
                'scheduler_interval': joschedule.get('interval'),
                'start_time': joschedule.get('start_time'),
                'start_date': joschedule.get('start_date'),
                'end_date': joschedule.get('end_date'),
                'storage_backend': config_workload.get('storage_backend'),
                }
        }

    def _list_view(self, func, request, workloads):
        """Provide a view for a list of openstack workloads."""
        workloads_list = [func(request, workload)['workload'] for workload in workloads]
        workloads_dict = dict(config_workloads=workloads_list)

        return workloads_dict
