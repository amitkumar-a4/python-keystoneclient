
from systemtests.tests.systemtest import WorkloadMgrSystemTest

Description = 'Test7:                                       \n'\
              '      Create new workload type               \n'\
              '      Delete workload type that is created     '

class test7(WorkloadMgrSystemTest):

    def __init__(self, workloadmgrclient, novaclient):
        super(test7, self).__init__(workloadmgrclient, novaclient, Description)

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
        pass

        # Make sure the workload type has required elements

    """
    cleanup the test
    """
    def cleanup(self, *args, **kwargs):
        #Delete the workloadtype that is created
        pass
        
