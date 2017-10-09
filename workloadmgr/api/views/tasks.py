# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model workload API responses as a python dictionary."""

    _collection_name = "tasks"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def detail_list(self, request, tasks):
        return self._list_view(self.detail, request, tasks)

    def detail(self, request, task):
        msg = {}
        for message in task['status_messages']:
            msg[message.id] = message.status_message
        return {
            'task': {
                'created_at': task.get('created_at'),
                'updated_at': task.get('updated_at'),
                'id': task.get('id'),
                'display_name': task.get('display_name'),
                'display_description': task.get('display_description'),
                'finished_at': task.get('finished_at'),
                'status': task.get('status'),
                'status_messages': msg,
            }

        }

    def _list_view(self, func, request, tasks):
        tasks_list = [func(request, task)['task'] for task in tasks]
        tasks_dict = dict(tasks=tasks_list)

        return tasks_dict
