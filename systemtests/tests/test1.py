from systemtests.tests.systemtest import WorkloadMgrSystemTest
import time

Description = 'Test1:                                       \n'\
              '      Create Serial workload using VM1       \n'\
              '      Delete the workload that is created      '

class test1(WorkloadMgrSystemTest):

    def __init__(self, testshell):
        super(test1, self).__init__(testshell, Description)

    """
    Setup the conditions for test to run
    """
    def prepare(self, *args, **kwargs):
        # Make sure vm as specified in the argument vm1 exists 
        # on the production
        workloads = self._testshell.cs.workloads.list()
        self.serialtype = None
        for type in self._testshell.cs.workload_types.list():
            if type.name == 'Serial':
               self.serialtype = type
               break
     
        if self.serialtype == None:
           raise Exception("Serial workloadtype not found")
 
        # We will use VM4
        self.vm = None
        for vm in self._testshell.novaclient.servers.list():
           if str(vm.name).lower() == "vm4":
              self.vm = vm
              break

        # May be I need to create a VM with in the test itself
        if self.vm == None:
           raise Exception("VM4 is not found in the vm inventory")
 

    """
    run the test
    """
    def run(self, *args, **kwargs):
        # Create serial workload with the VM
        # Make sure that the workload is created
        instances = []
        instances.append({'instance-id':self.vm.id})
        self.workload = self._testshell.cs.workloads.create("VM4", "Test VM4", self.serialtype.id, instances, {}, {})
        status = self.workload.status
        while 1:
           status = self._testshell.cs.workloads.get(self.workload.id).status
           if status == 'available' or status == 'error':
              break
           time.sleep(5)

    def verify(self, *args, **kwargs):
        if len(self.workload.instances) != 1:
           raise Exception("Number of instances in the workload is not 1")

        if self.workload.instances[0] != self.vm.id:
           raise Exception("Instance id in the workload does not match with the id that is provided")
     
        if self.workload.name != "VM4":
           raise Exception("workload name is not 'VM4'")

        if self.workload.description != "Test VM4":
           raise Exception("workload name is not 'Test VM4'")

    """
    cleanup the test
    """
    def cleanup(self, *args, **kwargs):
        #Delete the workload that is created
        wid = self.workload.id
        self._testshell.cs.workloads.delete(self.workload.id)

        for wload in self._testshell.cs.workloads.list():
            if wload.id == wid:
               raise Exception("Workload exists after delete")
       
