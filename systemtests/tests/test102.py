from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test102:                                      \n'\
              '      Create Serial workload                  \n'\
              '      Update the workload                     \n'\
              '      Delete workload that is created           '

vms = ["vm1", "vm2", "vm3", "vm4", "vm5"]


class test102(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test102, self).__init__(testshell, Description)
        self.snapshot = None
        self.workload = None

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test102, self).prepare(args, kwargs)
        # Make sure that VMs are not part of any workload
        workloads = self._testshell.cs.workloads.list()

        self.serialtype = None
        for type in self._testshell.cs.workload_types.list():
            if type.name == 'Serial':
                self.serialtype = type
                break

        if self.serialtype is None:
            raise Exception("Serial workloadtype not found")

        # We will use VM4
        self._vms = []
        for novavm in self._testshell.novaclient.servers.list():
            for vm in vms:
                if str(novavm.name).lower() == vm.lower():
                    self._vms.append(novavm)
                    break

        # May be I need to create a VM with in the test itself
        if len(self._vms) != len(vms):
            raise Exception("Not all VMs are present at production")

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # Make sure the workload type has required elements
        # Create serial workload with the VM
        # Make sure that the workload is created
        instances = []
        for vm in self._vms:
            instances.append({'instance-id': vm.id})

        if len(instances) != 5:
            raise Exception("There are less than 5 vms")

        jobschedule = {
            'start_date': 'Now',
            'end_date': "No End",
            'start_time': "12:00AM",
            'interval': '1 hr',
            'snapshots_to_keep': 10}

        self.workload = self._testshell.cs.workloads.create(
            "VMsWorkload",
            "Workload with 5 VMs",
            self.serialtype.id,
            instances,
            jobschedule,
            {})
        status = self.workload.status
        print "Waiting for workload status to be either available or error"
        while True:
            self.workload = self._testshell.cs.workloads.get(self.workload.id)
            status = self.workload.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        jobschedule = {
            'start_date': 'Now',
            'end_date': "No End",
            'start_time': "12:00AM",
            'interval': '2 hr',
            'snapshots_to_keep': 10}
        self._testshell.cs.workloads.update(
            self.workload.id,
            None,
            None,
            self.workload.workload_type_id,
            None,
            jobschedule,
            None)
        self.workload = self._testshell.cs.workloads.get(self.workload.id)

        for key, value in jobschedule.iteritems():
            if self.workload.jobschedule[key] != value:
                raise Exception(
                    "Workload update failed. Expected value for key '" +
                    key +
                    "' is '" +
                    value +
                    "'. Got '" +
                    self.workload.jobschedule[key] +
                    "'.")

    """
    verify the test
    """

    def verify(self, *args, **kwargs):
        if self.snapshot:
            self.snapshot = self._testshell.cs.snapshots.get(self.snapshot.id)

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # delete the snapshot
        # delete the workload
        if self.snapshot:
            self._testshell.cs.snapshots.delete(self.snapshot.id)

        if self.workload:
            self._testshell.cs.workloads.delete(self.workload.id)
