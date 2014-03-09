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

def InitFlow(store):
    pass

class CassandraWorkflow(workflow.Workflow):
    """"
      Cassandra Workflow
    """

    def __init__(self, name, store):
        super(CassandraWorkflow, self).__init__(name)
        self._store = store
        self._flow = InitFlow(self._store)

    def topology(self):
        pass

    def details(self):
        pass

    def discover(self):
        pass

