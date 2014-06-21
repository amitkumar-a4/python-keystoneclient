import sys

class WorkloadMgrSystemTest(object):
    """
    Base class for all system tests
    """

    """
    describe what this test will do
    """
    _description = ""

    @property
    def description(self):
        """description of the test."""
        return self._description

    """
    Base class constructor
    """
    def __init__(self, testshell, description):
        self._testshell = testshell
        self._description = description

    """
    Setup the conditions for test to run
    """
    def prepare(self, *args, **kwargs):
        pass
     
    """
    run the test
    """
    def run(self, *args, **kwargs):
        pass

    """
    Verify that the test has run successfully
    """
    def verify(self, *args, **kwargs):
        pass

    """
    cleanup the test
    """
    def cleanup(self, *args, **kwargs):
        pass
