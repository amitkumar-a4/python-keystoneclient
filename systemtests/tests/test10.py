from systemtests.tests.systemtest import WorkloadMgrSystemTest

Description = 'Test10:                                       \n'\
              '      Create Serial workload                  \n'\
              '      Take a snapshot                         \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshot                         \n'\
              '      Delete workload that is created           '

class test10(WorkloadMgrSystemTest):

    def __init__(self, workloadmgrclient, novaclient):
        super(test10, self).__init__(workloadmgrclient, novaclient, Description)

    """
    Setup the conditions for test to run
    """
    def prepare(self, *args, **kwargs):
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
