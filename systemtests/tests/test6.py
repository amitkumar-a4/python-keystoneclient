from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time
import json


Description = 'Test6:                                       \n'\
              '      Create Composite workload using VM1    \n'\
              '      Delete the workload that is created      '

"""
Format of workload graph:
    {u'flow': u'serial',
     u'children': [
           {u'flow': u'serial',
            u'children': [
                  {
                      u'type': u'workload',
                      u'data': {u'name': u'vm1', u'workload_type_id': u'2e319536-f1e4-4a7c-886f-60947af30116', u'description': u'', u'id': u'16cf8857-f2d8-4411-93c3-bdca1673bf80'}
                  }
              ]
            },
            {u'flow': u'serial',
             u'children': [
                 {
                     u'type': u'workload',
                     u'data': {u'name': u'vm2', u'workload_type_id': u'2e319536-f1e4-4a7c-886f-60947af30116', u'description': u'', u'id': u'9f91bc36-2e52-49ca-99f0-9c645f88725b'
}
                 }
              ]
            }
     ]
   }
"""

vms = ["vm1", "vm2", "mysql", "mongodb1", "mongodb2", "mongodb3", "mongodb4"]


class test6(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test6, self).__init__(testshell, Description)
        self.workload1 = None
        self.workload2 = None
        self.composite = None
        self.snapshot = None
        self.restore = None
        self.compositetype = None
        self.vms = []

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test6, self).prepare(args, kwargs)

        # Make sure vm as specified in the argument vm1 exists
        # on the production
        workloads = self._testshell.cs.workloads.list()
        self.serialtype = None
        for type in self._testshell.cs.workload_types.list():
            if type.name == 'Serial':
                self.serialtype = type
            if type.name == 'Composite':
                self.compositetype = type

        if self.serialtype is None:
            raise Exception("Serial workloadtype not found")

        if self.compositetype is None:
            raise Exception("Composite workloadtype not found")

        # We will use VM4
        self.vms = []
        for testvm in vms:
            found = False
            for vm in self._testshell.novaclient.servers.list():
                if str(vm.name).lower() == testvm:
                    self.vms.append(vm)
                    found = True
                    break
            if not found:
                raise Exception(
                    "TestVM '" +
                    testvm +
                    "' not found on the production openstack")

        # May be I need to create a VM with in the test itself
        if len(self.vms) != len(vms):
            raise Exception(
                "Some of the test vms on the production are not found")

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # create workload with vm1
        instances = []
        for vm in self.vms:
            if (vm.name).lower() == "vm1".lower():
                instances.append({'instance-id': vm.id})

        if len(instances) != 1:
            raise Exception("There are less than 1 vms")

        jobschedule = {
            'start_date': 'Now',
            'end_date': "No End",
            'start_time': "12:00AM",
            'interval': '1 hr',
            'snapshots_to_keep': 10}
        self.workload1 = self._testshell.cs.workloads.create(
            "VM1Workload",
            "Workload with 1 VM",
            self.serialtype.id,
            instances,
            jobschedule,
            {})
        status = self.workload1.status
        print "Waiting for workload status to be either available or error"
        while True:
            self.workload1 = self._testshell.cs.workloads.get(
                self.workload1.id)
            status = self.workload1.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        # Make sure the job is enabled on this one
        if self.workload1.jobschedule['enabled'] != True:
            raise Exception("Jobscheduler is not enabled on VM1Workload")

        # Create workload with vm2
        instances = []
        for vm in self.vms:
            if (vm.name).lower() == "vm2".lower():
                instances.append({'instance-id': vm.id})

        if len(instances) != 1:
            raise Exception("There are less than 1 vms")

        jobschedule = {
            'start_date': 'Now',
            'end_date': "No End",
            'start_time': "12:00AM",
            'interval': '1 hr',
            'snapshots_to_keep': 10}
        self.workload2 = self._testshell.cs.workloads.create(
            "VM2Workload",
            "Workload with 1 VM",
            self.serialtype.id,
            instances,
            jobschedule,
            {})
        status = self.workload2.status
        print "Waiting for workload status to be either available or error"
        while True:
            self.workload2 = self._testshell.cs.workloads.get(
                self.workload2.id)
            status = self.workload2.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        # Make sure the job is enabled on this one
        if self.workload2.jobschedule['enabled'] != True:
            raise Exception("Jobscheduler is not enabled on VM1Workload")

        # Create Composite workload with the VM
        wl1 = {'flow': 'serial',
               'children': [
                   {
                       'type': 'workload',
                       'data': {
                           'name': self.workload1.name,
                           'workload_type_id': self.workload1.workload_type_id,
                           'description': self.workload1.description,
                           'id': self.workload1.id
                       }
                   }
               ]
               }
        wl2 = {'flow': 'serial',
               'children': [
                   {
                       'type': 'workload',
                       'data': {
                           'name': self.workload2.name,
                           'workload_type_id': self.workload2.workload_type_id,
                           'description': self.workload2.description,
                           'id': self.workload2.id
                       }
                   }
               ]
               }

        wlgraph = {'flow': 'serial', 'children': [wl1, wl2]}
        metadata = {}
        metadata['workloadgraph'] = json.dumps(wlgraph)
        jobschedule = {
            'start_date': 'Now',
            'end_date': "No End",
            'start_time': "12:00AM",
            'interval': '1 hr',
            'snapshots_to_keep': 10}
        self.composite = self._testshell.cs.workloads.create(
            "Composite",
            "CompositeWorkload with 2 workloads",
            self.compositetype.id,
            [],
            jobschedule,
            metadata)
        status = self.composite.status
        print "Waiting for composite workload status to be either available or error"
        while True:
            self.composite = self._testshell.cs.workloads.get(
                self.composite.id)
            status = self.composite.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        if self.composite.jobschedule['enabled'] != True:
            raise Exception(
                "Jobscheduler is not enabled on Composite workload")

        self.workload1 = self._testshell.cs.workloads.get(self.workload1.id)
        self.workload2 = self._testshell.cs.workloads.get(self.workload2.id)

        try:
            self._testshell.cs.workloads.snapshot(self.workload1.id)
            raise Exception("Snapshot on member workload, workload1 succeeded")
        except BaseException:
            pass

        try:
            self.workload2 = self._testshell.cs.workloads.snapshot(
                self.workload2.id)
            raise Exception("Snapshot on member workload, workload2 succeeded")
        except BaseException:
            pass

        try:
            self._testshell.cs.workloads.delete(self.workload1.id)
            raise Exception(
                "Member workload1 is deleted even when it is part of composite workload")
        except BaseException:
            pass

        try:
            self.workload2 = self._testshell.cs.workloads.delete(
                self.workload2.id)
            raise Exception(
                "Member workload2 is deleted even when it is part of composite workload")
        except BaseException:
            pass

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created
        if self.composite:
            self._testshell.cs.workloads.delete(self.composite.id)
        for workload in self._testshell.cs.workloads.list():
            self._testshell.cs.workloads.delete(workload.id)
