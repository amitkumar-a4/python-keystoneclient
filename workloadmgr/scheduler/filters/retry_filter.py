# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.scheduler import filters

LOG = logging.getLogger(__name__)


class RetryFilter(filters.BaseHostFilter):
    """Filter out nodes that have already been attempted for scheduling
    purposes
    """

    def host_passes(self, host_state, filter_properties):
        """Skip nodes that have already been attempted."""
        retry = filter_properties.get('retry', None)
        if not retry:
            # Re-scheduling is disabled
            LOG.info("Re-scheduling is disabled")
            return True

        hosts = retry.get('hosts', [])
        host = host_state.host

        passes = host not in hosts
        pass_msg = "passes" if passes else "fails"

        LOG.info(_("Host %(host)s %(pass_msg)s.  Previously tried hosts: "
                   "%(hosts)s") % locals())

        # Host passes if it's not in the list of previously attempted hosts:
        return passes
