from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test1:                                       \n'\
              '      Create Serial workload using VM1       \n'\
              '      Pause and Resume                       \n'\
              '      Delete the workload that is created    \n'\
              '                                               '


class test1(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test1, self).__init__(testshell, Description)
        self.workload = None
        self.snapshot = None
        self.restore = None

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test1, self).prepare(args, kwargs)

        # Make sure vm as specified in the argument vm1 exists
        # on the production
        workloads = self._testshell.cs.workloads.list()
        self.serialtype = None
        for type in self._testshell.cs.workload_types.list():
            if type.name == 'Serial':
                self.serialtype = type
                break

        if self.serialtype is None:
            raise Exception("Serial workloadtype not found")

        # We will use VM4
        self.vm = None
        for vm in self._testshell.novaclient.servers.list():
            if str(vm.name).lower() == "vm4":
                self.vm = vm
                break

        # May be I need to create a VM with in the test itself
        if self.vm is None:
            raise Exception("VM4 is not found in the vm inventory")

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # Create serial workload with the VM
        # Make sure that the workload is created
        instances = []
        instances.append({'instance-id': self.vm.id})
        self.workload = self._testshell.cs.workloads.create(
            "VM4", "Test VM4", self.serialtype.id, instances, {}, {})
        status = self.workload.status
        while True:
            status = self._testshell.cs.workloads.get(self.workload.id).status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        self.workload = self._testshell.cs.workloads.pause(self.workload.id)
        enabled = self._testshell.cs.workloads.get(
            self.workload.id).jobschedule.enabled
        if enabled:
            raise Exception("Jobschedule is still enabled")

        self.workload = self._testshell.cs.workloads.resume(self.workload.id)
        enabled = self._testshell.cs.workloads.get(
            self.workload.id).jobschedule.enabled
        if not enabled:
            raise Exception("Jobschedule is not enabled ")

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
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

    def verify(self, *args, **kwargs):
        if len(self.workload.instances) != 1:
            raise Exception("Number of instances in the workload is not 1")

        if self.workload.instances[0] != self.vm.id:
            raise Exception(
                "Instance id in the workload does not match with the id that is provided")

        if self.workload.name != "VM4":
            raise Exception("workload name is not 'VM4'")

        if self.workload.description != "Test VM4":
            raise Exception("workload name is not 'Test VM4'")

        self.verify_restore(self.restore.id)

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created
        if self.restore:
            self._testshell.cs.restores.delete(self.restore.id)

        if self.snapshot:
            self._testshell.cs.snapshots.delete(self.snapshot.id)

        if self.workload:
            wid = self.workload.id
            self._testshell.cs.workloads.delete(self.workload.id)

        for wload in self._testshell.cs.workloads.list():
            if wload.id == wid:
                raise Exception("Workload exists after delete")
