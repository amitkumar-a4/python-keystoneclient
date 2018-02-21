# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2016 TrilioData, Inc.
# All Rights Reserved.

import json
import os

from oslo_config import cfg
from workloadmgr.openstack.common import log as logging
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr.db.imports import import_workload_2_0_205
from workloadmgr.vault import vault

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _adjust_values(cntx, new_version, values, upgrade):
    values['version'] = new_version
    if not upgrade:
        values['user_id'] = cntx.user_id
        values['project_id'] = cntx.project_id
    if 'metadata' in values:
        metadata = {}
        for meta in values['metadata']:
            metadata[meta['key']] = meta['value']
        values['metadata'] = metadata
    if 'host' in values:
        values['host'] = socket.gethostname()

    return values


def import_settings(cntx, new_version, upgrade=True):
    try:
        db = WorkloadMgrDB().db
        backup_target, path = vault.get_settings_backup_target()
        settings = json.loads(
            backup_target.get_object(
                os.path.join(
                    CONF.cloud_unique_id,
                    'settings_db')))
        for setting_values in settings:
            try:
                if 'key' in setting_values:
                    setting_values['name'] = setting_values['key']
                setting_values = _adjust_values(
                    cntx, new_version, setting_values, upgrade)
                db.setting_create(cntx, setting_values)
            except Exception as ex:
                LOG.exception(ex)
    except Exception as ex:
        LOG.exception(ex)

    return import_workload_2_0_205.import_settings(cntx, new_version)


def import_workload(cntx, workload_ids, new_version, upgrade=True):
    """ Import workload and snapshot records from vault
    Versions Supported: 2.0.205
    """
    return import_workload_2_0_205.import_workload(
        cntx, workload_ids, new_version, upgrade)
