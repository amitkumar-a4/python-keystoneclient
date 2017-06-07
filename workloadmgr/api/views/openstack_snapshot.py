# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2017 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common

LOG = logging.getLogger(__name__)

class ViewBuilder(common.ViewBuilder):
    """Model openstack_snapshots API responses as a python dictionary."""

    _collection_name = "openstack_snapshots"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, snapshots):
        """Show a list of snapshots without many details."""
        return self._list_view(self.summary, request, snapshots)

    def detail_list(self, request, snapshots):
        """Detailed view of a list of snapshots ."""
        return self._list_view(self.detail, request, snapshots)

    def summary(self, request, openstack_snapshot):
        """Generic, non-detailed view of a snapshot."""
        return {
            'openstack_snapshot': {
                'id': openstack_snapshot.get('id'),
                'created_at': openstack_snapshot.get('created_at'),
                'status': openstack_snapshot.get('status'),
                'name': openstack_snapshot.get('display_name'),
                'description': openstack_snapshot.get('display_description'),
                'openstack_workload_id': openstack_snapshot.get('openstack_workload_id'),
                'services_to_backup': openstack_snapshot.get('services_to_backup'),
            }}
      

    def detail(self, request, openstack_snapshot):
        """Detailed view of a single snapshot."""
        return {
            'openstack_snapshot': {
                'id': openstack_snapshot.get('id'),
                'created_at': openstack_snapshot.get('created_at'),
                'updated_at': openstack_snapshot.get('updated_at'),
                'finished_at': openstack_snapshot.get('finished_at'),
                'status': openstack_snapshot.get('status'),
                'name': openstack_snapshot.get('display_name'),
                'description': openstack_snapshot.get('display_description'),
                'openstack_workload_id': openstack_snapshot.get('openstack_workload_id'),
                'services_to_backup': openstack_snapshot.get('services_to_backup'),
                'host': openstack_snapshot.get('host'),
                'size': openstack_snapshot.get('size'),
                'progress_msg': openstack_snapshot.get('progress_msg'),
                'warning_msg': openstack_snapshot.get('warning_msg'),
                'error_msg': openstack_snapshot.get('error_msg'),
                'upload_summary': openstack_snapshot.get('upload_summary'),
                'time_taken': openstack_snapshot.get('time_taken'),
                'vault_storage_path': openstack_snapshot.get('vault_storage_path'),
                'services_to_backup': openstack_snapshot.get('services_to_backup')
            }}

    def _list_view(self, func, request, snapshots):
        """Provide a view for a list of snapshots."""
        snapshots_list = [func(request, snapshot)['openstack_snapshot'] for snapshot in snapshots]

        snapshots_list = sorted(snapshots_list,
                                key=lambda snapshot: snapshot['created_at'])
        snapshots_dict = dict(snapshots=snapshots_list)

        return snapshots_dict

