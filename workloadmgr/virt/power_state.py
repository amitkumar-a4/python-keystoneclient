# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Power state is the state we get by calling virt driver on a particular
domain. The hypervisor is always considered the authority on the status
of a particular VM, and the power_state in the DB should be viewed as a
snapshot of the VMs's state in the (recent) past. It can be periodically
updated, and should also be updated at the end of a task if the task is
supposed to affect power_state.
"""

# NOTE(maoy): These are *not* virDomainState values from libvirt.
# The hex value happens to match virDomainState for backward-compatibility
# reasons.
NOSTATE = 0x00
RUNNING = 0x01
PAUSED = 0x03
SHUTDOWN = 0x04  # the VM is powered off
CRASHED = 0x06
SUSPENDED = 0x07

# TODO(maoy): BUILDING state is only used in bare metal case and should
# eventually be removed/cleaned up. NOSTATE is probably enough.
BUILDING = 0x09

# TODO(justinsb): Power state really needs to be a proper class,
# so that we're not locked into the libvirt status codes and can put mapping
# logic here rather than spread throughout the code
_STATE_MAP = {
    NOSTATE: 'pending',
    RUNNING: 'running',
    PAUSED: 'paused',
    SHUTDOWN: 'shutdown',
    CRASHED: 'crashed',
    SUSPENDED: 'suspended',
    BUILDING: 'building',
}


def name(code):
    return _STATE_MAP[code]


def valid_states():
    return _STATE_MAP.keys()
