# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model snapshots API responses as a python dictionary."""

    _collection_name = "snapshots"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, snapshots):
        """Show a list of snapshots without many details."""
        return self._list_view(self.summary, request, snapshots)

    def detail_list(self, request, snapshots):
        """Detailed view of a list of snapshots ."""
        return self._list_view(self.detail, request, snapshots)

    def summary(self, request, snapshot):
        """Generic, non-detailed view of a snapshot."""
        return {
            'snapshot': {
                'id': snapshot['id'],
                'links': self._get_links(request,
                                         snapshot['id']),
            },
        }

    def restore_summary(self, request, restore):
        """Generic, non-detailed view of a restore."""
        return {
            'restore': {
                'snapshot_id': restore['snapshot_id'],
            },
        }

    def detail(self, request, snapshot):
        """Detailed view of a single snapshot."""
        return {
            'snapshot': {
                'created_at': snapshot.get('created_at'),
                'updated_at': snapshot.get('updated_at'),
                'id': snapshot.get('id'),
                'user_id': snapshot.get('user_id'),
                'project_id': snapshot.get('project_id'),
                'status': snapshot.get('status'),
                #'links': self._get_links(request, snapshot['id'],
                'name':  snapshot['id'],
                'snapshot_type': snapshot.get('snapshot_type'),
                'workload_id': snapshot.get('workload_id'),
            }
        }

    def _list_view(self, func, request, snapshots):
        """Provide a view for a list of snapshots."""
        snapshots_list = [func(request, snapshot)['snapshot'] for snapshot in snapshots]
        snapshots_links = self._get_collection_links(request,
                                                   snapshots,
                                                   self._collection_name)
        snapshots_dict = dict(snapshots=snapshots_list)

        if snapshots_links:
            snapshots_dict['snapshots_links'] = snapshots_links

        return snapshots_dict
