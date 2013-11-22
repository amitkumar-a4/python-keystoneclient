# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.
"""
:mod:`vmwareapi` -- WorkloadMgr support for VMware ESX/ESXi Server through VMware API.
"""

from workloadmgr.virt.vmwareapi import driver

VMwareESXDriver = driver.VMwareESXDriver
VMwareVCDriver = driver.VMwareVCDriver
