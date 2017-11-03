from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test132:                                       \n'\
              '      Create Serial workload                  \n'\
              '      Take a snapshot                         \n'\
              '      Take 5 more snapshots                   \n'\
              '      Restore a older snapshot while another snapshot operation is pending \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshots                        \n'\
              '      Delete workload that is created           '

vms = ["vm1", "vm2", "vm3", "vm4", "vm5"]


class test132(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test132, self).__init__(testshell, Description)
        self.restore = None
        self.snapshot = None
        self.workload = None

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test132, self).prepare(args, kwargs)
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

        self.workload = self._testshell.cs.workloads.create(
            "VMsWorkload", "Workload with 5 VMs", self.serialtype.id, instances, {}, {})
        status = self.workload.status
        print "Waiting for workload status to be either available or error"
        while True:
            self.workload = self._testshell.cs.workloads.get(self.workload.id)
            status = self.workload.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        print "Performing  full snapshot"
        # perform snapshot operation
        self._testshell.cs.workloads.snapshot(
            self.workload.id,
            name="Full snapshot",
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

        if self.snapshot.status != "available":
            raise Exception("The full snapshot operation failed")

        fullsnapshot = self.snapshot

        # Restore latest

        print("Restoring snapshot '%s'" % self.snapshot.name)
        # perform restore operation
        self._testshell.cs.snapshots.restore(
            self.snapshot.id,
            name="Restore",
            description="Restore from full snapshot")

        print "Performing incremental snapshot operations while restore in progress"
        for i in range(0, 10):
            # perform snapshot operation
            self._testshell.cs.workloads.snapshot(
                self.workload.id,
                name="Snapshot-" +
                str(i),
                description="Snapshot of worklaod" +
                self.workload.id)

            snapshots = []
            for s in self._testshell.cs.snapshots.list():
                if s.workload_id == self.workload.id and s.name == "Snapshot-" + \
                        str(i):
                    snapshots.append(s)

            if len(snapshots) != 1:
                raise Exception("Error: More snapshots than expected")

            snapshotname = "Snapshot-" + str(i)
            print("Waiting for snapshot %s to become available" % snapshotname)
            while True:
                self.snapshot = self._testshell.cs.snapshots.get(
                    snapshots[0].id)
                status = self.snapshot.status

                if status == 'error':
                    print self.snapshot
                    raise Exception("Error: Snapshot operation failed")
                if status == 'available' or status == 'error':
                    break
                time.sleep(5)
            print "Sleeping 30 seconds before next snapshot operation"
            time.sleep(30)

        restores = []
        for r in self._testshell.cs.restores.list():
            if r.snapshot_id == fullsnapshot.id:
                restores.append(r)

        if len(restores) != 1:
            raise Exception("Error: More than one restore")

        self.restore = None
        print "Waiting for restore to become available"
        while True:
            self.restore = self._testshell.cs.restores.get(restores[0].id)
            status = self.restore.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        if self.restore.status != 'available':
            raise Exception(
                "Restore from latest snapshot failed. Status %s" %
                self.restore.status)

    """
    verify the test
    """

    def verify(self, *args, **kwargs):
        ns = 0
        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id:
                ns += 1
        if ns != 5:
            raise Exception("Error: number of snapshots is not 5")

        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id:
                self.verify_snapshot(s.id)

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # delete the restore
        # delete the snapshot
        # delete the workload
        if self.restore:
            self._testshell.cs.restores.delete(self.restore.id)

        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id:
                self._testshell.cs.snapshots.delete(s.id)

        if len(self._testshell.cs.snapshots.list()):
            if s.workload_id == self.workload.id:
                raise Exception("Not all snapshot are deleted successfully")

        if self.workload:
            self._testshell.cs.workloads.delete(self.workload.id)
