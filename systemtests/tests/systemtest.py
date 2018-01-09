import sys
import time
from subprocess import call
import os


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
        # Clean up all swift objects
        os.system('bash -c "swift list vast_snapshots > /tmp/swift.out"')
        with open("/tmp/swift.out") as f:
            content = f.readlines()

        for l in content:
            os.system("swift delete vast_snapshots " + l)

    """
    run the test
    """

    def run(self, *args, **kwargs):
        pass

    """
    Verify snapshot objects
    """

    def verify_snapshot(self, snapshot_id):
        snapshot = self._testshell.cs.snapshots.get(snapshot_id)

        # Make sure none of the VMs are in paused state. They
        # all should be active

    """
    Verify restore
    """

    def verify_restore(self, restore_id):
        restore = self._testshell.cs.restores.get(restore_id)

        # Verify vms
        for inst in restore.instances:
            server = self._testshell.novaclient.servers.get(inst['id'])
            if server is None:
                raise Exception("Server with %s is not found" % inst['id'])

        # TODO verify networks

        # TODO: verify subnets

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
