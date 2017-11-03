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
        d = {}
        d['id'] = snapshot['id']
        d['created_at'] = snapshot['created_at']
        d['status'] = snapshot['status']
        d['snapshot_type'] = snapshot['snapshot_type']
        d['workload_id'] = snapshot['workload_id']
        if 'instances' in snapshot:
            instances = []
            for vm in snapshot['instances']:
                instance = {'id': vm['id'],
                            'name': vm['name'],
                            'status': vm['status'],
                            'metadata': vm['metadata'],
                            }
                if 'flavor' in vm:
                    instance['flavor'] = vm['flavor']
                if 'nics' in vm:
                    instance['nics'] = vm['nics']
                if 'vdisks' in vm:
                    instance['vdisks'] = vm['vdisks']
                instances.append(instance)
            d['instances'] = instances
        #d['links'] = self._get_links(request, snapshot['id'])
        d['name'] = snapshot['display_name']
        d['description'] = snapshot['display_description']
        d['host'] = snapshot['host']
        return {'snapshot': d}

    def detail(self, request, snapshot):
        """Detailed view of a single snapshot."""
        d = {}
        d['id'] = snapshot['id']
        d['created_at'] = snapshot['created_at']
        d['updated_at'] = snapshot['updated_at']
        d['finished_at'] = snapshot['finished_at']
        d['user_id'] = snapshot['user_id']
        d['project_id'] = snapshot['project_id']
        d['status'] = snapshot['status']
        d['snapshot_type'] = snapshot['snapshot_type']
        d['workload_id'] = snapshot['workload_id']
        if 'instances' in snapshot:
            instances = []
            for vm in snapshot['instances']:
                instance = {'id': vm['id'],
                            'name': vm['name'],
                            'status': vm['status'],
                            'metadata': vm['metadata'],
                            }
                if 'flavor' in vm:
                    instance['flavor'] = vm['flavor']
                if 'security_group' in vm:
                    instance['security_group'] = vm['security_group']
                if 'nics' in vm:
                    instance['nics'] = vm['nics']
                if 'vdisks' in vm:
                    instance['vdisks'] = vm['vdisks']
                instances.append(instance)

            d['instances'] = instances
        #d['links'] = self._get_links(request, snapshot['id'])
        d['name'] = snapshot['display_name']
        d['description'] = snapshot['display_description']
        d['host'] = snapshot['host']
        d['size'] = snapshot['size']
        d['restore_size'] = snapshot['restore_size']
        d['uploaded_size'] = min(snapshot['uploaded_size'], snapshot['size'])
        d['progress_percent'] = snapshot['progress_percent']
        d['progress_msg'] = snapshot['progress_msg']
        d['warning_msg'] = snapshot['warning_msg']
        d['error_msg'] = snapshot['error_msg']
        d['time_taken'] = snapshot['time_taken']
        d['pinned'] = snapshot['pinned']
        d['metadata'] = snapshot['metadata']
        d['restores_info'] = ''
        if hasattr(snapshot, 'instances'):
            d['instances'] = snapshot.instances
        return {'snapshot': d}

    def _list_view(self, func, request, snapshots):
        """Provide a view for a list of snapshots."""
        snapshots_list = [func(request, snapshot)['snapshot']
                          for snapshot in snapshots]
        # snapshots_links = self._get_collection_links(request,
        #                                           snapshots,
        #                                           self._collection_name)
        snapshots_list = sorted(snapshots_list,
                                key=lambda snapshot: snapshot['created_at'])
        snapshots_dict = dict(snapshots=snapshots_list)

        # if snapshots_links:
        #    snapshots_dict['snapshots_links'] = snapshots_links

        return snapshots_dict

    def task(self, request, task_id):
        return {
            'task': {
                'id': task_id,
            },
        }
