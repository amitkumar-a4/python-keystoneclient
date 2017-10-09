from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time


Description = 'Test32:                                       \n'\
              '      Create MongoDB workload with mongodb1 as one of the node in cluster  \n'\
              '      Take a snapshot                         \n'\
              '      Monitor the snapshot progress           \n'\
              '      Take incremental snapshots              \n'\
              '      Delete snapshot                         \n'\
              '      Delete workload that is created           '


class test32(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test32, self).__init__(testshell, Description)

        self.workload = None
        self.snapshot = None
        self.restore = None

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
        super(test32, self).prepare(args, kwargs)
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

        print "Performing snapshot operations"
        # perform snapshot operation
        self._testshell.cs.workloads.snapshot(
            self.workload.id,
            name="MongoDBSnapshot",
            description="First snapshot of MongoDB workload")

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

            print(
                "Waiting for snapshot %s to become available" %
                "Snapshot-" + str(i))
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
        if self.restore:
            self._testshell.cs.restores.delete(self.restore.id)

        for s in self._testshell.cs.snapshots.list():
            if s.workload_id == self.workload.id:
                self._testshell.cs.snapshots.delete(s.id)

        if len(self._testshell.cs.snapshots.list()):
            if s.workload_id == self.workload.id:
                raise Exception("Not al snapshot are cleaned up successfully")

        if self.workload:
            self._testshell.cs.workloads.delete(self.workload.id)

        for wload in self._testshell.cs.workloads.list():
            if wload.id == wid:
                raise Exception("Workload exists after delete")
