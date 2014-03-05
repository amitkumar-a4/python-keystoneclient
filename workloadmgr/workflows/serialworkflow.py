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


class SerialWorkflow(workflow.Workflow):
    """"
      Serial workflow
    """

    def __init__(self, name):
        super(Workflow, self).__init__(name)
        self._topology = []
        self._vms = []

    def topology(self):
        #
        #

    def details(self):

    def discover(self):

    def execute(self):
        result = engines.run(self._flow, engine_conf='parallel', backend={'connection':'mysql://root:project1@10.6.255.110/workloadmgr?charset=utf8'}, store=store)
