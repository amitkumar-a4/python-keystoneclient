from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test13:                                       \n'\
              '      Create Serial workload                  \n'\
              '      Take a snapshot                         \n'\
              '      Take 5 more snapshots                   \n'\
              '      Restore the lastest snapshot            \n'\
              '      Restore two times from same snapshot    \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshots                        \n'\
              '      Delete workload that is created         \n'

#vms = ["vm1", "vm2", "vm3", "vm4", "vm5"]
vms = ["vm1", "vm2"]


class test13(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test13, self).__init__(testshell, Description)
        self.restore = None
        self.snapshot = None
        self.workload = None

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test13, self).prepare(args, kwargs)
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

        if len(instances) != len(vms):
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

        print "Performing incremental snapshot operations"
        for i in range(0, 5):
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

        # Restore latest
        latest_snapshot = None
        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id and s.name == "Snapshot-4":
                latest_snapshot = s

        if latest_snapshot is None:
            raise Exception("Cannot find latest snapshot")

        print("Restoring snapshot '%s'" % latest_snapshot.name)
        # perform restore operation
        self._testshell.cs.snapshots.restore(
            latest_snapshot.id,
            name="Restore",
            description="Restore from latest snapshot")

        restores = []
        for r in self._testshell.cs.restores.list():
            if r.snapshot_id == latest_snapshot.id:
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

        self.restore = self._testshell.cs.restores.delete(restores[0].id)
        if len(self._testshell.cs.restores.list()):
            raise Exception("Cannot delete latest restore successfully")

        self.restore = None

        # Restore last but one snapshot
        latest_snapshot = None
        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id and s.name == "Snapshot-3":
                latest_snapshot = s

        if latest_snapshot is None:
            raise Exception("Cannot find latest snapshot")

        print("Restoring snapshot '%s'" % latest_snapshot.name)
        # perform restore operation
        self._testshell.cs.snapshots.restore(
            latest_snapshot.id,
            name="Restore",
            description="Restore from latest snapshot")

        restores = []
        for r in self._testshell.cs.restores.list():
            if r.snapshot_id == latest_snapshot.id:
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

        self.restore = self._testshell.cs.restores.delete(restores[0].id)
        if len(self._testshell.cs.restores.list()):
            raise Exception("Cannot delete latest restore successfully")

        print("Restoring two times from snapshot '%s'" % latest_snapshot.name)
        # perform restore operation
        self._testshell.cs.snapshots.restore(
            latest_snapshot.id,
            name="Restore",
            description="Restore from latest snapshot")
        self._testshell.cs.snapshots.restore(
            latest_snapshot.id,
            name="Restore",
            description="Another from latest snapshot")

        restores = []
        for r in self._testshell.cs.restores.list():
            if r.snapshot_id == latest_snapshot.id:
                restores.append(r)

        if len(restores) != 2:
            raise Exception("Error: More than one restore")

        self.restore = None
        print "Waiting for restores to become available"
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

        while True:
            self.restore = self._testshell.cs.restores.get(restores[1].id)
            status = self.restore.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        if self.restore.status != 'available':
            raise Exception(
                "Restore from latest snapshot failed. Status %s" %
                self.restore.status)

        self.restore = self._testshell.cs.restores.delete(restores[0].id)
        self.restore = self._testshell.cs.restores.delete(restores[1].id)
        if len(self._testshell.cs.restores.list()):
            raise Exception("Cannot delete latest restore successfully")

    """
    verify the test
    """

    def verify(self, *args, **kwargs):
        ns = 0
        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id:
                ns += 1
        if ns != 6:
            raise Exception("Error: number of snapshots is not 6")

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
                import pdb
                pdb.set_trace()
                raise Exception("Not al snapshot are cleaned up successfully")

        if self.workload:
            self._testshell.cs.workloads.delete(self.workload.id)
