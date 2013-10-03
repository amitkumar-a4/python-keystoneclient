# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from pbr import version as pbr_version

WORKLOADMANAGER_VENDOR = "Triliodata Inc."
WORKLOADMANAGER_PRODUCT = "Workload Manager"
WORKLOADMANAGER_PACKAGE = None  # distro package version suffix

loaded = False
version_info = pbr_version.VersionInfo('workloadmanager')
version_string = version_info.version_string
