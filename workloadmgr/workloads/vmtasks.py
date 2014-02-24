# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
This file includes library of tasks that can be used to implement application
specific flows

"""

import contextlib
import logging
import os
import random
import sys
import time

logging.basicConfig(level=logging.ERROR)

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)

from taskflow import engines
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow import task
from taskflow.utils import reflection

@contextlib.contextmanager
def show_time(name):
    start = time.time()
    yield
    end = time.time()
    print(" -- %s took %0.3f seconds" % (name, end - start))

class PauseVM(task.Task):

   def execute(self, instance_id):
       # Pause the VM
       print "PauseVM: " + instance_id

   def revert(self, *args, **kwargs):
       # Resume VM
       print "Reverting PauseVM: " + kwargs["instance_id"]

class ResumeVM(task.Task):

   def execute(self, instance_id):
       # Resume the VM
       print "ResumeVM: " + instance_id

class SnapshotVM(task.Task):

   def execute(self, instance_id):
       # Snapshot the VM
       print "SnapshotVM: " + instance_id

   def revert(self, *args, **kwargs):
       # Delete snapshot
       print "Reverting SnapshotVM: " + kwargs["instance_id"]

class UploadSnapshot(task.Task):

   def execute(self, instance_id):
       # Upload snapshot data to swift endpoint
       print "UploadSnapshot VM: " + instance_id

class BlockCommit(task.Task):

   def execute(self, instance_id):
       # Upload snapshot data to swift endpoint
       print "BlockCommit VM: " + instance_id

# Assume there is no ordering dependency between instances
# pause each VM in parallel.
def UnorderedPauseVMs(instances):
   flow = uf.Flow("pausevmsuf")
   for index,item in enumerate(instances):
      flow.add(PauseVM("PauseVM_" + item, rebind=["instanceid_" + str(index)]))

   return flow

# Assume there is dependency between instances
# pause each VM in the order that appears in the array.
def LinearPauseVMs(instances):
   flow = lf.Flow("pausevmslf")
   for index,item in enumerate(instances):
      flow.add(PauseVM("PauseVM_" + item, rebind=["instanceid_" + str(index)]))

   return flow

# Assume there is no ordering dependency between instances
# snapshot each VM in parallel.
def UnorderedSnapshotVMs(instances):
   flow = uf.Flow("snapshotvmuf")
   for index,item in enumerate(instances):
      flow.add(SnapshotVM("SnapshotVM_" + item, rebind=["instanceid_" + str(index)]))

   return flow

# Assume there is dependency between instances
# snapshot each VM in the order that appears in the array.
def LinearSnapshotVMs(instances):
   flow = lf.Flow("snapshotvmlf")
   for index,item in enumerate(instances):
      flow.add(SnapshotVM("SnapshotVM_" + item, rebind=["instanceid_" + str(index)]))

   return flow

# Assume there is no ordering dependency between instances
# resume each VM in parallel. Usually there should not be any
# order in which vms should be resumed.
def UnorderedResumeVMs(instances):
   flow = uf.Flow("resumevmsuf")
   for index,item in enumerate(instances):
      flow.add(ResumeVM("ResumeVM_" + item, rebind=["instanceid_" + str(index)]))

   return flow

def UnorderedUploadSnapshots(instances):
   flow = uf.Flow("resumevmsuf")
   for index,item in enumerate(instances):
      flow.add(UploadSnapshot("UploadSnapshot_" + item, rebind=["instanceid_" + str(index)]))

   return flow

def UnorderedBlockCommit(instances):
   flow = uf.Flow("resumevmsuf")
   for index,item in enumerate(instances):
      flow.add(BlockCommit("BlockCommit_" + item, rebind=["instanceid_" + str(index)]))

   return flow
