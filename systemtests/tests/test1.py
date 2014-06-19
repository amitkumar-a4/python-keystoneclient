from systemtest import WorkloadMgrSystemTest

Description = 'Test1:                                       \n'\
              '      Create Serial workload using VM1       \n'\
              '      Delete the workload that is created      '

class test1(WorkloadMgrSystemTest):

    def __init__(self, client, description):
        super(test1, self).__init__(client, description)

    """
    Setup the conditions for test to run
    """
    def prepare(self, *args, **kwargs):
        # Make sure vm as specified in the argument vm1 exists 
        # on the production
        pass
     
    """
    run the test
    """
    def run(self, *args, **kwargs):
        # Create serial workload with the VM
        #self.client()
        pass
        # Make sure that the workload is created

    """
    cleanup the test
    """
    def cleanup(self, *args, **kwargs):
        #Delete the workload that is created
        pass
        
