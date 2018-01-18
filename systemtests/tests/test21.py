from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test21:                                       \n'\
              '      Create Parallel workload                  \n'\
              '      Take a snapshot                         \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshot                         \n'\
              '      Delete workload that is created           '

vms = ["vm1", "vm2", "vm3", "vm4", "vm5"]


class test21(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test21, self).__init__(testshell, Description)
        self.restore = None
        self.snapshot = None
        self.workload = None

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test21, self).prepare(args, kwargs)
        # Make sure that VMs are not part of any workload
        workloads = self._testshell.cs.workloads.list()

        self.paralleltype = None
        for type in self._testshell.cs.workload_types.list():
            if type.name == 'Parallel':
                self.paralleltype = type
                break

        if self.paralleltype is None:
            raise Exception("Parallel workloadtype not found")

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
        # Create parallel workload with the VM
        # Make sure that the workload is created
        instances = []
        for vm in self._vms:
            instances.append({'instance-id': vm.id})

        if len(instances) != 5:
            raise Exception("There are less than 5 vms")

        self.workload = self._testshell.cs.workloads.create(
            "VMsWorkload", "Workload with 5 VMs", self.paralleltype.id, instances, {}, {})
        status = self.workload.status
        print "Waiting for workload status to be either available or error"
        while True:
            self.workload = self._testshell.cs.workloads.get(self.workload.id)
            status = self.workload.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        print "Performing snapshot operations"
        # perform snapshot operation
        self._testshell.cs.workloads.snapshot(
            self.workload.id,
            name="Snapshot1",
            description="First snapshot of the workload")

        snapshots = []
        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id:
                snapshots.append(s)

        if len(snapshots) != 1:
            raise Exception("Error: More than one snapshot")

        print "Waiting for snapshot to become available"
        while True:
            self.snapshot = self._testshell.cs.snapshots.get(snapshots[0].id)
            status = self.snapshot.status

            if status == 'error':
                print self.snapshot
                raise Exception("Error: Snapshot operation failed")
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        print "Performing restore operations"
        # perform snapshot operation
        self._testshell.cs.snapshots.restore(
            self.snapshot.id,
            name="Restore",
            description="First Restore of the workload")

        restores = []
        for r in self._testshell.cs.restores.list():
            if r.snapshot_id == self.snapshot.id:
                restores.append(r)

        if len(restores) != 1:
            raise Exception("Error: More than one restore")

        self.restore = None
        print "Waiting for restore to become available"
        while True:
            self.restore = self._testshell.cs.restores.get(restores[0].id)
            status = self.restore.status

            if status == 'error':
                print self.restore
                raise Exception("Error: Restore operation failed")
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

    """
    verify the test
    """

    def verify(self, *args, **kwargs):
        self.verify_snapshot(self.snapshot.id)
        self.verify_restore(self.restore.id)

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # delete the restore
        # delete the snapshot
        # delete the workload
        if self.restore:
            self._testshell.cs.restores.delete(self.restore.id)

        if self.snapshot:
            self._testshell.cs.snapshots.delete(self.snapshot.id)

        if self.workload:
            self._testshell.cs.workloads.delete(self.workload.id)
