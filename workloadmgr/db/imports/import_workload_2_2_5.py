# Copyright (c) 2016 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.openstack.common import log as logging
from workloadmgr.db.imports import import_workload_2_2_4


LOG = logging.getLogger(__name__)

def import_settings(cntx, new_version, upgrade=True):
    return import_workload_2_2_4.import_settings(cntx, new_version, upgrade)

<<<<<<< HEAD
def import_workload(cntx, workload_url, new_version, backup_endpoint, upgrade=True):
    """ Import workload and snapshot records from vault
        Versions Supported: 2.2.5
    """
    return import_workload_2_2_4.import_workload(cntx, workload_url, new_version, backup_endpoint, upgrade)
=======
def import_workload(cntx, workload_ids, new_version, upgrade=True):
    """ Import workload and snapshot records from vault
        Versions Supported: 2.2.5
    """
    return import_workload_2_2_4.import_workload(cntx, workload_ids, new_version, upgrade)
>>>>>>> upstream/master
