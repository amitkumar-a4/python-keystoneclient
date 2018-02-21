# Copyright 2014 TrilioData Inc.

from tempest.api.volume import base as volume_base
from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config

CONF = config.CONF


class WorkloadmgrUnicodeTest(volume_base.BaseVolumeTest):

    @classmethod
    def resource_setup(cls):
        pass
