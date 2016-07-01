# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from workloadmgr.db import base


class WorkloadMgrDB(base.Base):

    def __init__(self, host=None, db_driver=None):
        super(WorkloadMgrDB, self).__init__(db_driver)
