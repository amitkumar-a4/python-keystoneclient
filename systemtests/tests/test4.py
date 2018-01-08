
from systemtests.tests.systemtest import WorkloadMgrSystemTest

Description = 'Test4:                                       \n'\
              '      Create Hadoop workload using VM1       \n'\
              '      Delete the workload that is created      '


class test4(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test4, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test4, self).prepare(args, kwargs)
        # Make sure vm as specified in the argument vm1 exists
        # on the production
        pass

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # Create hadoop workload with the VM

        # Make sure that the workload is created
        pass

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # Delete the workload that is created
        pass
