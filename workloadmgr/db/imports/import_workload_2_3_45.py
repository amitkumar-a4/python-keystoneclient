# Copyright (c) 2016 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.db.imports import import_workload_2_3_44


LOG = logging.getLogger(__name__)

def import_settings(cntx, new_version, upgrade=True):
    return import_workload_2_3_44.import_settings(cntx, new_version, upgrade)

def import_workload(cntx, workload_ids, new_version, upgrade=True):
    """ Import workload and snapshot records from vault
        Versions Supported: 2.3.45
    """
    return import_workload_2_3_44.import_workload(cntx, workload_ids, new_version, upgrade)