# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.db.imports import import_workload_2_0_190


LOG = logging.getLogger(__name__)

def import_settings(cntx, new_version):
    return import_workload_2_0_190.import_settings(cntx, new_version)

def import_workload(cntx, workload_url, new_version, upgrade=True):
    """ Import workload and snapshot records from vault 
    Versions Supported: 2.0.191
    """
    return import_workload_2_0_190.import_workload(cntx, workload_url, new_version, upgrade)
