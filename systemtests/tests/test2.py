from systemtests.tests.systemtest import WorkloadMgrSystemTest
Description = 'Test2:                                       \n'\
              '      Create Parallel workload using VM1     \n'\
              '      Delete the workload that is created      '


class test2(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test2, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test2, self).prepare(args, kwargs)
        # Make sure vm as specified in the argument vm1 exists
        # on the production
        pass

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # Create parallel workload with the VM
        pass

        # Make sure that the workload is created

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created
        pass
