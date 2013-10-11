# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from pbr import version as pbr_version

WORKLOADMGR_VENDOR = "Triliodata Inc."
WORKLOADMGR_PRODUCT = "Workload Manager"
WORKLOADMGR_PACKAGE = None  # distro package version suffix

loaded = False
version_info = pbr_version.VersionInfo('workloadmgr')
version_string = version_info.version_string
