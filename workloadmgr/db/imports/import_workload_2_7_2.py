# Copyright (c) 2016 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.db.imports import import_workload_2_7_1


LOG = logging.getLogger(__name__)


def import_settings(cntx, new_version, upgrade=True):
    return import_workload_2_7_1.import_settings(cntx, new_version, upgrade)


def import_workload(cntx, workload_ids, new_version, upgrade=True):
    """ Import workload and snapshot records from vault
        Versions Supported: 2.7.2
    """
    return import_workload_2_7_1.import_workload(
        cntx, workload_ids, new_version, upgrade)
