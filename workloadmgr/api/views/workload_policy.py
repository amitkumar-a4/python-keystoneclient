# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model WorkloadPolicy API responses as a python dictionary."""

    _collection_name = "policy"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, policy):
        """Show a list of policy without many details."""
        return self._list_view(self.summary, request, policy)

    def detail_list(self, request, policy):
        """Detailed view of a list of policy ."""
        return self._list_view(self.detail, request, policy)

    def summary(self, request, policy):
        """Generic, non-detailed view of a policy."""
        d = {}
        d['id'] = policy['id']
        d['created_at'] = policy['created_at']
        d['updated_at'] = policy['created_at']
        d['status'] = policy['status']
        d['name'] = policy['display_name']
        d['description'] = policy['display_description']
        d['metadata'] = policy['metadata']
        d['field_values'] = policy['field_values']
        return {'policy': d}

    def detail(self, request, policy):
        """Detailed view of a single policy."""
        d = {}
        d['id'] = policy['id']
        d['created_at'] = policy['created_at']
        d['updated_at'] = policy['created_at']
        d['user_id'] = policy['user_id']
        d['project_id'] = policy['project_id']
        d['status'] = policy['status']
        d['name'] = policy['display_name']
        d['description'] = policy['display_description']
        d['field_values'] = policy['field_values']
        d['metadata'] = policy['metadata']
        d['policy_assignments'] = policy['policy_assignments']
        return {'policy': d}

    def _list_view(self, func, request, policy_list):
        """Provide a view for a list of policy."""
        policy_list = [func(request, policy)['policy']
                       for policy in policy_list]

        if func.__name__ == 'detail':
            policy_list = sorted(policy_list,
                                 key=lambda policy: policy['created_at'])
        policy_list = dict(policy_list=policy_list)

        return policy_list
