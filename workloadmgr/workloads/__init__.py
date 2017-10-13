# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

import workloadmgr.flags
import workloadmgr.openstack.common.importutils

API = workloadmgr.openstack.common.importutils.import_class(
    workloadmgr.flags.FLAGS.workloads_api_class)
