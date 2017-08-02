# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2017 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common

LOG = logging.getLogger(__name__)

class ViewBuilder(common.ViewBuilder):
    """Model config backup API responses as a python dictionary."""

    _collection_name = "config_backups"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, backups):
        """Show a list of backups without many details."""
        return self._list_view(self.summary, request, backups)

    def detail_list(self, request, backups):
        """Detailed view of a list of backups ."""
        return self._list_view(self.detail, request, backups)

    def summary(self, request, config_backup):
        """Generic, non-detailed view of a backup."""
        return {
            'config_backup': {
                'id': config_backup.get('id'),
                'created_at': config_backup.get('created_at'),
                'status': config_backup.get('status'),
                'name': config_backup.get('display_name'),
                'size': config_backup.get('size'),
                'description': config_backup.get('display_description'),
                'config_workload_id': config_backup.get('config_workload_id'),
            }}
      

    def detail(self, request, config_backup):
        """Detailed view of a single backup."""
        return {
            'config_backup': {
                'id': config_backup.get('id'),
                'created_at': config_backup.get('created_at'),
                'updated_at': config_backup.get('updated_at'),
                'finished_at': config_backup.get('finished_at'),
                'user_id': config_backup.get('user_id'),
                'project_id': config_backup.get('project_id'),
                'status': config_backup.get('status'),
                'name': config_backup.get('display_name'),
                'description': config_backup.get('display_description'),
                'config_workload_id': config_backup.get('config_workload_id'),
                'host': config_backup.get('host'),
                'size': config_backup.get('size'),
                'progress_msg': config_backup.get('progress_msg'),
                'warning_msg': config_backup.get('warning_msg'),
                'error_msg': config_backup.get('error_msg'),
                'time_taken': config_backup.get('time_taken'),
                'vault_storage_path': config_backup.get('vault_storage_path'),
                'metadata': config_backup.get('metadata')
            }}

    def _list_view(self, func, request, backups):
        """Provide a view for a list of backups."""
        backups_list = [func(request, backup)['config_backup'] for backup in backups]

        backups_list = sorted(backups_list,
                                key=lambda backup: backup['created_at'])
        backups_dict = dict(backups=backups_list)

        return backups_dict

