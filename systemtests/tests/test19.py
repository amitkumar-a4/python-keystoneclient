from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test1:                                           \n'\
              '      Create workload type                       \n'\
              '      Delete the workloadtype that is created    \n'\
              '                                               '


class test1(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test1, self).__init__(testshell, Description)
        self.workloadtype = None

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

        self.metadata = {
            'key1': 'string',
            'key2': 'boolean',
            'key3': 'password',
            'key4': 'boolean'}
        self.name = "WorkloadType1"
        self.description = "Test Workload type"
        self.workloadtype = self._testshell.cs.workloadtypes.create(
            metadata=metadata, name=name, description=description)
        status = self.workloadtype.status

        while True:
            self.workloadtype = self._testshell.cs.workloadtypes.get(
                self.workloadtype.id)
            status = self.workloadtype.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

    def verify(self, *args, **kwargs):
        if self.name != self.workloadtype.name:
            raise Exception("workload type name is not same")

        if self.workloadtype.description != self.description:
            raise Exception("Workload type description did not match")

        if self.workloadtype.metadata['key1'] != 'string':
            raise Exception("Workload type key1 did not match")

        if self.workloadtype.metadata['key2'] != 'boolean':
            raise Exception("Workload type key2 did not match")

        if self.workloadtype.metadata['key3'] != 'password':
            raise Exception("Workload type key3 did not match")

        if self.workloadtype.metadata['key4'] != 'boolean':
            raise Exception("Workload type key4 did not match")

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created

        if self.workloadtype:
            wid = self.workloadtype.id
            self._testshell.cs.workloadtypes.delete(self.workloadtype.id)

        for wload in self._testshell.cs.workloadtypes.list():
            if wload.id == wid:
                raise Exception("Workload exists after delete")
