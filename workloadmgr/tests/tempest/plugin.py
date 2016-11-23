# Copyright 2014 TrilioData Inc.

import workloadmgr
import os

from workloadmgr.tests.tempest import config as project_config
from tempest import config
from tempest.test_discover import plugins


class CinderTempestPlugin(plugins.TempestPlugin):
    def load_tests(self):
        base_path = os.path.split(os.path.dirname(
            os.path.abspath(workloadmgr.__file__)))[0]
        test_dir = "workloadmgr/tests/tempest"
        full_test_dir = os.path.join(base_path, test_dir)
        return full_test_dir, base_path

    def register_opts(self, conf):
        config.register_opt_group(
            conf, project_config.service_available_group,
            project_config.ServiceAvailableGroup)

    def get_opt_lists(self):
        pass
