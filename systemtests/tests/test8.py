
from systemtest import WorkloadMgrSystemTest

Description = 'Test8:                                       \n'\
              '      Create new workload type               \n'\
              '      Create a new workload of this new type \n'\
              '      Delete workload                        \n'\
              '      Delete workload type that is created     '

class test1(WorkloadMgrSystemTest):

    def __init__(self, client, description):
        super(test1, self).__init__(client, description)

    """
    Setup the conditions for test to run
    """
    def prepare(self, *args, **kwargs):
     
    """
    run the test
    """
    def run(self, *args, **kwargs):
        # Create new workload type of various metadata components
        self.client()

        # Make sure the workload type has required elements

    """
    cleanup the test
    """
    def cleanup(self, *args, **kwargs):
        # delete the workload
        # delete the workloadtype that is created
