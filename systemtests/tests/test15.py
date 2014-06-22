from systemtests.tests.systemtest import WorkloadMgrSystemTest

Description = 'Test15:                                       \n'\
              '      Create Composite workload               \n'\
              '      Take a snapshot                         \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshot                         \n'\
              '      Delete workload that is created           '

class test15(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test15, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """
    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test15, self).prepare(args, kwargs)
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
