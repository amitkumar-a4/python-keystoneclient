from systemtests.tests.systemtest import WorkloadMgrSystemTest

Description = 'Test13:                                       \n'\
              '      Create Hadoop workload                  \n'\
              '      Take a snapshot                         \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshot                         \n'\
              '      Delete workload that is created           '

class test13(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test13, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """
    def prepare(self, *args, **kwargs):
        # Cleanup swift first
        super(test13, self).prepare(args, kwargs)
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
