from systemtests.tests.systemtest import WorkloadMgrSystemTest


Description = 'Test3:                                          \n'\
              '      Create MongoDB workload using parameters  \n'\
              '      Delete the workload that is created         '

class test3(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test3, self).__init__(testshell, Description)

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
        # Create MongoDB workload with the VM

        # Make sure that the workload is created
        pass

    """
    cleanup the test
    """
    def cleanup(self, *args, **kwargs):
        #Delete the workload that is created
        pass
        
