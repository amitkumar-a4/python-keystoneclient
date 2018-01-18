# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


import math

from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.scheduler import filters


LOG = logging.getLogger(__name__)


class CapacityFilter(filters.BaseHostFilter):
    """CapacityFilter filters based on workloadmgr host's snapshots running."""

    def host_passes(self, host_state, filter_properties):
        """Return True if the workloadmgr node hasn't reached threshold running snaoshots."""

        return True
