# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.db.imports import import_workload_1_0_179


LOG = logging.getLogger(__name__)

def import_settings(cntx, new_version):
    return import_workload_1_0_179.import_settings(cntx, new_version)

def import_workload(cntx, workload_url, new_version, upgrade=True):
    """ Import workload and snapshot records from vault 
    Versions Supported: 1.0.180
    """
    return import_workload_1_0_179.import_workload(cntx, workload_url, new_version, upgrade)