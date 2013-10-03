# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

import workloadmanager.flags
import workloadmanager.openstack.common.importutils

API = workloadmanager.openstack.common.importutils.import_class(
        workloadmanager.flags.FLAGS.workloads_api_class)
