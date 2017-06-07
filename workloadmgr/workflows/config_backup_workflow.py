# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

from taskflow import engines
from taskflow.patterns import linear_flow as lf

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.rpc import amqp
import config_backup_tasks

LOG = logging.getLogger(__name__)

class ConfigBackupWorkflow(object):
    '''
    Config Backup Restore
    '''

    def __init__(self, name, store):
        self._name = name
        self._store = store
        cntx = amqp.RpcContext.from_dict(self._store['context'])

    def initflow(self):
        self._flow = lf.Flow('ConfigBackuplf')
        
        self._flow.add(config_backup_tasks.CopyConfigFiles(name="ConfigBackup" +
                                          self._store['openstack_snapshot_id'],
                       rebind={'openstack_snapshot_id':'openstack_snapshot_id',
                                'params':'params'}))

        self._flow.add(config_backup_tasks.ApplyRetentionPolicy(name="RetentionPolicy" + 
                                                 self._store['openstack_snapshot_id'],
                               rebind={'openstack_workload_id':'openstack_workload_id'}))


    def execute(self):
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection']},
                         store=self._store)


