# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from oslo_log import log as logging

from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model transfer API responses as a python dictionary."""

    _collection_name = "os-workload-transfer"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, transfers, origin_transfer_count):
        """Show a list of transfers without many details."""
        return self._list_view(self.summary, request, transfers,
                               origin_transfer_count)

    def detail_list(self, request, transfers, origin_transfer_count):
        """Detailed view of a list of transfers ."""
        return self._list_view(self.detail, request, transfers,
                               origin_transfer_count)

    def summary(self, request, transfer):
        """Generic, non-detailed view of a transfer."""
        return {
            'transfer': {
                'id': transfer['id'],
                'workload_id': transfer.get('workload_id'),
                'name': transfer['display_name'],
                'links': self._get_links(request,
                                         transfer['id']),
            },
        }

    def detail(self, request, transfer):
        """Detailed view of a single transfer."""
        return {
            'transfer': {
                'id': transfer.get('id'),
                'created_at': transfer.get('created_at'),
                'name': transfer.get('display_name'),
                'workload_id': transfer.get('workload_id'),
                'links': self._get_links(request, transfer['id'])
            }
        }

    def create(self, request, transfer):
        """Detailed view of a single transfer when created."""
        return {
            'transfer': {
                'id': transfer.get('id'),
                'created_at': transfer.get('created_at'),
                'name': transfer.get('display_name'),
                'workload_id': transfer.get('workload_id'),
                'auth_key': transfer.get('auth_key'),
                'links': self._get_links(request, transfer['id'])
            }
        }

    def _list_view(self, func, request, transfers, origin_transfer_count):
        """Provide a view for a list of transfers."""
        transfers_list = [func(request, transfer)['transfer'] for transfer in
                          transfers]
        transfers_links = self._get_collection_links(request,
                                                     transfers,
                                                     self._collection_name)
        transfers_dict = dict(transfers=transfers_list)

        if transfers_links:
            transfers_dict['transfers_links'] = transfers_links

        return transfers_dict
