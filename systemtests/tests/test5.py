
from systemtests.tests.systemtest import WorkloadMgrSystemTest

Description = 'Test5:                                       \n'\
              '      Create Cassandra workload using VM1    \n'\
              '      Delete the workload that is created      '


class test5(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test5, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test5, self).prepare(args, kwargs)

        # Make sure vm as specified in the argument vm1 exists
        # on the production
        pass

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # Create Cassandra workload with the VM

        # Make sure that the workload is created
        pass

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created
        pass
