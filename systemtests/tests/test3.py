from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test3:                                                                     \n'\
              '      Create MongoDB workload with mongodb1 as one of the node in cluster  \n'\
              '      Delete the workload that is created                                    '


class test3(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test3, self).__init__(testshell, Description)
        self.workload = None
        self.metadata = {'DBPort': '27019',
                         'DBUser': '',
                         'DBHost': 'mongodb1',
                         'RunAsRoot': 'True',
                         'DBPassword': '',
                         'HostPassword': 'project1',
                         'HostSSHPort': '22',
                         'HostUsername': 'ubuntu'}
        self.instances = []

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test3, self).prepare(args, kwargs)
        # Make sure vm as specified in the argument vm1 exists
        # on the production
        workloads = self._testshell.cs.workloads.list()
        self.mongodbtype = None
        for type in self._testshell.cs.workload_types.list():
            if type.name.lower() == 'MongoDB'.lower():
                self.mongodbtype = type
                break

        if self.mongodbtype is None:
            raise Exception("MongoDB workloadtype not found")

        # We will use VM4
        self.mongodb = None
        for vm in self._testshell.novaclient.servers.list():
            if str(vm.name).lower() == "mongodb1":
                self.mongodb = vm
                break

        # May be I need to create a VM with in the test itself
        if self.mongodb is None:
            raise Exception("mongodb1 is not found in the vm inventory")

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # Create mongodb workload with the monogodb1
        # Make sure that the workload is created
        self.instances = []

        mongonodes = self._testshell.cs.workload_types.discover_instances(
            self.mongodbtype.id, metadata=self.metadata)['instances']
        for inst in mongonodes:
            self.instances.append({'instance-id': inst['vm_id']})

        self.workload = self._testshell.cs.workloads.create(
            "MongoDB",
            "MongoDB Workload",
            self.mongodbtype.id,
            self.instances,
            {},
            self.metadata)
        status = self.workload.status
        while True:
            status = self._testshell.cs.workloads.get(self.workload.id).status
            if status == 'available' or status == 'error':
                break
            time.sleep(5)

    def verify(self, *args, **kwargs):
        if len(self.workload.instances) != len(self.instances):
            raise Exception("Number of instances in the workload is not 1")

        instids = []
        for i in self.instances:
            instids.append(i['instance-id'])

        if set(self.workload.instances) != set(instids):
            raise Exception(
                "Instance ids in the workload does not match with the ids that were provided")

        if self.workload.name != "MongoDB":
            raise Exception("workload name is not 'MongoDB'")

        if self.workload.description != "MongoDB Workload":
            raise Exception("workload name is not 'MongoDB Workload'")

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created
        wid = self.workload.id
        self._testshell.cs.workloads.delete(self.workload.id)

        for wload in self._testshell.cs.workloads.list():
            if wload.id == wid:
                raise Exception("Workload exists after delete")
