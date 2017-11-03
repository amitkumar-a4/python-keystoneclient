
from systemtests.tests.systemtest import WorkloadMgrSystemTest

Description = 'Test9:                                       \n'\
              '      Create new workload type               \n'\
              '      Create a new workload of this new type \n'\
              '      Delete workload                        \n'\
              '      Delete workload type that is created     '


class test9(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test9, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """

    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test9, self).prepare(args, kwargs)
        pass

    """
    run the test
    """

    def run(self, *args, **kwargs):
        # Create new workload type of various metadata components

        # Make sure the workload type has required elements
        pass

    """
    cleanup the test
    """

    def cleanup(self, *args, **kwargs):
        # delete the workload
        # delete the workloadtype that is created
        pass
