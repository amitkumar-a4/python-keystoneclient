from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time
import time
import threading
import datetime
from threading import Thread


class WorkloadTest(Thread):

    def on_thread_finished(self, thread, data):
        pass

    def __init__(self, name, description, vms, workloadtype, _parent=None):
        self._parent = _parent
        self._testshell = _parent._testshell
        self._vms = vms
        self._workloadtype = workloadtype
        self._name = name
        self._description = description
        super(WorkloadTest, self).__init__()

    def run(self):
        # Create serial workload with the VM
        # Make sure that the workload is created
        instances = []
        for vm in self._vms:
            instances.append({'instance-id': vm.id})

        if len(instances) != len(self._vms):
            raise Exception("There are less than %s vms", str(len(self._vms)))

        self.workload = self._testshell.cs.workloads.create(
            self._name, self._description, self._workloadtype.id, instances, {}, {})
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

        # Restore VMs with different names
        latest_snapshot = None
        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id and s.name == "Snapshot-4":
                latest_snapshot = s

        if latest_snapshot is None:
            raise Exception("Cannot find latest snapshot")

        changedvms = []
        for inst in self._testshell.cs.snapshots.get(
                latest_snapshot.id).instances:
            changedvm = {}
            vm = self._testshell.novaclient.servers.get(inst['id'])
            changedvm['id'] = vm.id
            changedvm['name'] = vm.name + "restored"
            changedvms.append(changedvm)

        print("Restoring '%s' snapshot" % latest_snapshot.name)
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
        try:
            if self._testshell.cs.restores.get(restores[0].id):
                raise Exception("Cannot delete latest restore successfully")
        except BaseException:
            pass

        latest_snapshot = None
        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id and s.name == "Snapshot-3":
                latest_snapshot = s

        if latest_snapshot is None:
            raise Exception("Cannot find latest snapshot")

        print("Restoring '%s' snapshot" % latest_snapshot.name)
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
        try:
            if self._testshell.cs.restores.get(restores[0].id):
                raise Exception("Cannot delete second restore successfully")
        except BaseException:
            pass

        self.restore = None
        self.verify()
        self.cleanup()

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

        # for s in self._testshell.cs.snapshots.list():
            # if s.workload_id == self.workload.id:
            # self.verify_snapshot(s.id)

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

        if self.workload:
            self._testshell.cs.workloads.delete(self.workload.id)


Description = 'Test15:                                       \n'\
              '      Create four workloads                   \n'\
              '          Two serial and two parallel         \n'\
              '          Serial1: VM1, VM2                   \n'\
              '          Serial2: VM3, VM4                   \n'\
              '          Parallel1: VM5, VM6                 \n'\
              '          Parallel2: VM7, VM8                 \n'\
              '      Create Serial and parallel workloads    \n'\
              '      Take a snapshot                         \n'\
              '      Take 5 more snapshots                   \n'\
              '      Try various restore options             \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshots                        \n'\
              '      Delete workload that is created           '

vms = ["vm1", "vm2", "vm3", "vm4", "vm5", "vm6", "vm7", "vm8"]
#vms = ["vm1", "vm2"]


class test15(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test15, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test15, self).prepare(args, kwargs)
        # Make sure that VMs are not part of any workload
        workloads = self._testshell.cs.workloads.list()

        self.serialtype = None
        self.paralleltype = None
        for type in self._testshell.cs.workload_types.list():
            if type.name == 'Serial':
                self.serialtype = type

            if type.name == 'Parallel':
                self.paralleltype = type

        if self.serialtype is None:
            raise Exception("Serial workloadtype not found")

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
        threads = []
        for i in range(0, 4):
            thread = WorkloadTest("WorkloadTest-" + str(i),
                                  "Workload test",
                                  self._vms[i * 2:i * 2 + 2],
                                  self.serialtype,
                                  _parent=self)
            threads.append(thread)

        # Start all threads
        [x.start() for x in threads]

        # Wait for all of them to finish
        [x.join() for x in threads]

    """
    verify the test
    """

    def verify(self, *args, **kwargs):
        pass

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        pass
