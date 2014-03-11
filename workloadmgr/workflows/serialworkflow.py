# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

from taskflow import engines
from taskflow.utils import misc
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import graph_flow as gf
from taskflow import task
from taskflow import flow
from taskflow.utils import reflection
from taskflow import exceptions

from workloadmgr.openstack.common import log as logging


import vmtasks
import workflow


class SerialWorkflow(workflow.Workflow):
    """"
      Serial Workflow
    """

    def __init__(self, name, store):
        super(SerialWorkflow, self).__init__(name)
        self._store = store
        
    def initflow(self):
        self._flow = lf.Flow('SerialFlow')

    def topology(self):
        return dict(topology={})

    def details(self):
        # Details the flow details based on the
        # current topology, number of VMs etc
        def recurseflow(item):
            if isinstance(item, task.Task):
                return [{'name':str(item), 'type':'Task'}]

            flowdetails = {}
            flowdetails['name'] = str(item)
            flowdetails['type'] = item.__class__.__name__
            flowdetails['children'] = []
            for it in item:
                flowdetails['children'].append(recurseflow(it))

            return flowdetails

        workflow = recurseflow(self._flow)
        return dict(workflow=workflow)

    def discover(self):
        return dict(instances=[])
    
    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(self._store['context'], self._store['instances'], self._store['snapshot'])
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection': self._store['connection'] }, store=self._store)
    