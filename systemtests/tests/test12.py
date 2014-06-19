from systemtest import WorkloadMgrSystemTest

Description = 'Test12:                                       \n'\
              '      Create MongoDB workload                 \n'\
              '      Take a snapshot                         \n'\
              '      Monitor the snapshot progress           \n'\
              '      Delete snapshot                         \n'\
              '      Delete workload that is created           '

class test12(WorkloadMgrSystemTest):

    def __init__(self, client, description):
        super(test12, self).__init__(client, description)

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
