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
    Config Backup Workflow.
    '''

    def __init__(self, name, store):
        self._name = name
        self._store = store
        cntx = amqp.RpcContext.from_dict(self._store['context'])

    def initflow(self):
        self._flow = lf.Flow('ConfigBackuplf')

        #Populate _store with target values
        self._store['compute'] = 'compute'
        self._store['controller'] = 'controller'
        self._store['database'] = 'database'
       
        self._flow.add(config_backup_tasks.UnorderedCopyConfigFiles(self._store['backup_id'],
                                 self._store['params']['compute_hosts'], 'compute',
                                 self._store['params']))

        if len(self._store['params']['controller_hosts'])>0:
            self._flow.add(config_backup_tasks.UnorderedCopyConfigFilesFromRemoteHost(self._store['backup_id'],
                                 self._store['params']['controller_hosts'], 'controller',
                                 self._store['params']))
        
        db_host = self._store['params']['compute_hosts'][0]
        self._flow.add(config_backup_tasks.CopyConfigFiles(name="BackupDatabase_" + db_host,
                                 rebind={'backup_id':'backup_id',
                                         'host': db_host,
                                         'target': 'database',
                                         'params':'params'
                                        } ))


        self._flow.add(config_backup_tasks.ApplyRetentionPolicy(name="RetentionPolicy_" + 
                                                 self._store['backup_id'],
                               rebind={'config_workload_id':'config_workload_id'}))


    def execute(self):
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection']},
                         store=self._store)


