# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model workload API responses as a python dictionary."""

    _collection_name = "search"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def detail(self, request, search):
        return {
            'file_search': {
                'created_at': search.get('created_at'),
                'updated_at': search.get('updated_at'),
                'id': search.get('id'),
                'deleted_at': search.get('deleted_at'),
                'status': search.get('status'),
                'error_msg': search.get('error_msg'),
                'filepath': search.get('filepath'),
                'json_resp': search.get('json_resp'),
                'vm_id': search.get('vm_id'),
            }
        }
