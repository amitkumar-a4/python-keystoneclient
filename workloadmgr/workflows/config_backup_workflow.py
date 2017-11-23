# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

from taskflow import engines
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import unordered_flow as uf
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.rpc import amqp
import config_backup_tasks

LOG = logging.getLogger(__name__)


class ConfigBackupWorkflow(object):
    """Config Backup Workflow."""

    def __init__(self, name, store):
        self._name = name
        self._store = store
        self._config_backup = None
        self._postbackup = None
        self._flow = None
        cntx = amqp.RpcContext.from_dict(self._store['context'])

    def initflow(self):
        try:
            # Populate _store with target values
            self._store['compute'] = 'compute'
            self._store['controller'] = 'controller'
            self._store['database'] = 'database'

            db_host = self._store['params']['compute_hosts'][0]

            # Config backup workflow to backup Compute, Controler and Database
            self._config_backup = lf.Flow(self._name + "#ConfigBackup")

            # Add task to backup compute nodes
            self._config_backup.add(
                config_backup_tasks.UnorderedCopyConfigFiles(
                    self._store['backup_id'],
                    self._store['params']['compute_hosts'],
                    'compute',
                    self._store['params']))
            LOG.info("Compute node backup task added: backup_id: %s, compute_hosts: %s" % (
                self._store['backup_id'], str(self._store['params']['compute_hosts'])))

            # Add task to backup controller nodes
            if len(self._store['params']['controller_hosts']) > 0:
                self._config_backup.add(
                    config_backup_tasks.UnorderedCopyConfigFilesFromRemoteHost(
                        self._store['backup_id'],
                        self._store['params']['controller_hosts'],
                        'controller',
                        self._store['params']))
                LOG.info(
                    "Controller node backup task added: backup_id: %s, controller_hosts: %s" %
                    (self._store['backup_id'], str(
                        self._store['params']['controller_hosts'])))
            else:
                LOG.warning("No controoller nodes to backup.")

            # Add task to backup Database
            self._config_backup.add(
                config_backup_tasks.CopyConfigFiles(
                    name="BackupDatabase_" + db_host,
                    rebind={
                        'backup_id': 'backup_id',
                        'host': db_host,
                        'target': 'database',
                        'params': 'params'}))
            LOG.info("Database backup task added: backup_id: %s, host: %s"
                     % (self._store['backup_id'], db_host))

            self._postbackup = lf.Flow(self._name + "#PostBackup")

            # Add task for retention policy
            self._postbackup.add(
                config_backup_tasks.ApplyRetentionPolicy(
                    name="RetentionPolicy_" +
                    self._store['backup_id']))

            self._flow = lf.Flow('ConfigBackuplf')
            self._flow.add(self._config_backup, self._postbackup)
        except Exception as ex:
            LOG.exception(ex)

    def execute(self):
        result = engines.run(
            self._flow,
            engine_conf='parallel',
            backend={
                'connection': self._store['connection']},
            store=self._store)