# Copyright 2014 TrilioData Inc.

from tempest import config
from tempest.tests import base

CONF = config.CONF


class WorkloadmgrePlaceholderTest(base.TestCase):
    """Placeholder test for adding in-tree Workloadmgre tempest tests."""
    # TODO(smcginnis) Remove once real tests are added

    def test_placeholder(self):
        expected = 'This test is temporary and should be removed!'
        self.assertEqual(expected, expected)
