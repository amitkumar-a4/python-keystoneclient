# -*- coding: utf-8 -*-

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

from taskflow import exceptions
import pymongo
from pymongo import MongoClient


class MongoDBWorkflow(workflow.Workflow):
    """"
      MongoDB workflow
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
