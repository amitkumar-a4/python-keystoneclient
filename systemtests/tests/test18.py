from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test18:                                           \n'\
              '      Create workload type                       \n'\
              '      Workload metadata changes                  \n'\
              '      Delete the workloadtype that is created    \n'\
              '                                               '


class test18(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test18, self).__init__(testshell, Description)
        self._workloadtype = None

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test18, self).prepare(args, kwargs)

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

        self._metadata = {
            'key1': 'string',
            'key2': 'boolean',
            'key3': 'password',
            'key4': 'boolean'}
        self._name = "Workload1"
        self._description = "Test Workload"
        self._workloadtype = self._testshell.cs.workload_types.create(
            metadata=self._metadata, name=self._name, description=self._description)
        status = self._workloadtype.status
        while True:
            self._workloadtype = self._testshell.cs.workload_types.get(
                self._workloadtype.id)
            status = self._workloadtype.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

        self._metadata = {
            'key1': 'key1',
            'key2': 'False',
            'key3': 'key3',
            'key4': 'True'}
        self.workload = self._testshell.cs.workloads.create(
            self._name,
            self._description,
            self._workloadtype.id,
            instances,
            {},
            self._metadata)
        status = self.workload.status
        while True:
            self.workload = self._testshell.cs.workloads.get(self.workload.id)
            status = self.workload.status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

    def verify(self, *args, **kwargs):
        if self._name != self.workload.name:
            raise Exception("workload type name is not same")

        if self.workload.description != self._description:
            raise Exception("Workload type description did not match")

        if self.workload.metadata['key1'] != 'key1':
            raise Exception("Workload type key1 did not match")

        if self.workload.metadata['key2'] != 'False':
            raise Exception("Workload type key2 did not match")

        if self.workload.metadata['key3'] != 'key3':
            raise Exception("Workload type key3 did not match")

        if self.workload.metadata['key4'] != 'True':
            raise Exception("Workload type key4 did not match")

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created

        if self.workload:
            wid = self.workload.id
            self._testshell.cs.workloads.delete(self.workload.id)

        if self._workloadtype:
            wid = self._workloadtype.id
            self._testshell.cs.workload_types.delete(self._workloadtype.id)

        for wload in self._testshell.cs.workloads.list():
            if wload.id == self.workload.id:
                raise Exception("Workload exists after delete")

        for wload in self._testshell.cs.workload_types.list():
            if wload.id == self._workloadtype.id:
                raise Exception("Workload exists after delete")
