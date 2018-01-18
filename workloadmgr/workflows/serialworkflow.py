# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Trilio Data, Inc. All Rights Reserved.
#

import contextlib
import os
import random
import sys
import time

import datetime
import paramiko
import uuid
import cPickle as pickle

from taskflow import engines
from taskflow.utils import misc
from taskflow.listeners import printing
from taskflow.patterns import unordered_flow as uf
from taskflow.patterns import linear_flow as lf
from taskflow.patterns import graph_flow as gf
from taskflow import task
from taskflow import flow

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.compute import nova
import workloadmgr.context as context
from workloadmgr.openstack.common.rpc import amqp
from workloadmgr import exception

import vmtasks
import workflow


LOG = logging.getLogger(__name__)


def get_vms(cntx, workload_id):
    db = vmtasks.WorkloadMgrDB().db

    compute_service = nova.API(production=True)
    instances = compute_service.get_servers(cntx, admin=False)

    keypairs = {}

    vms = []
    workload = db.workload_get(cntx, workload_id)
    for vm in db.workload_vms_get(cntx, workload_id):
        vm_instance = None
        for instance in instances:
            if vm.vm_id == instance.id:
                vm_instance = instance
                break
        if vm_instance is None:
            if workload.source_platform == "vmware":
                raise exception.ErrorOccurred(
                    _("Unable to find Virtual Machine '%s' in vCenter inventory") %
                    vm.vm_name)
            else:
                raise exception.ErrorOccurred(
                    _("Unable to find Virtual Machine '%s' in nova inventory") %
                    vm.vm_name)

        vm_hypervisor = None

        vm = {
            'vm_id': vm_instance.id,
            'vm_name': vm_instance.name,
            'vm_metadata': vm_instance.metadata,
            'vm_flavor_id': vm_instance.flavor['id'],
            'hostname': vm_instance.name,
            'vm_power_state': getattr(vm_instance, 'OS-EXT-STS:power_state') or
            getattr(vm_instance, 'status'),
            'hypervisor_hostname': None,
            'hypervisor_type': "QEMU",
            'availability_zone': vm_instance.__dict__.get('OS-EXT-AZ:availability_zone', None)
        }

        if hasattr(
                vm_instance,
                'key_name') and vm_instance.key_name and vm_instance.key_name not in keypairs:
            try:
                keypair = compute_service.get_keypair_by_name(
                    cntx, vm_instance.key_name)
                if keypair:
                    keypairs[vm_instance.key_name] = \
                        pickle.dumps(keypair._info, 0)
            except BaseException:
                pass

        if hasattr(
                vm_instance,
                'key_name') and vm_instance.key_name and vm_instance.key_name in keypairs:
            vm['vm_metadata']['key_name'] = vm_instance.key_name
            vm['vm_metadata']['key_data'] = keypairs[vm_instance.key_name]

        vms.append(vm)
    return vms


"""
SerialWorkflow Requires the following inputs in store:

    'connection': FLAGS.sql_connection,     # taskflow persistence connection
    'context': context_dict,                # context dictionary
    'snapshot': snapshot,                   # snapshot dictionary
"""


class SerialWorkflow(workflow.Workflow):
    """
      Serial Workflow
    """

    def __init__(self, name, store):
        super(SerialWorkflow, self).__init__(name)
        self._store = store

    def initflow(self, composite=False):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        self._store['instances'] = get_vms(cntx, self._store['workload_id'])
        for index, item in enumerate(self._store['instances']):
            item['pause_at_snapshot'] = self._store['pause_at_snapshot']
            self._store['instance_' + item['vm_id']] = item

        _snapshotvms = lf.Flow(self.name + "#SnapshotVMs")

        _snapshotvms.add(vmtasks.LinearFreezeVMs(self._store['instances']))

        # This is a linear pausing of VMs.
        _snapshotvms.add(vmtasks.LinearPauseVMs(self._store['instances']))

        # linear snapshot of VMs.
        _snapshotvms.add(vmtasks.LinearSnapshotVMs(self._store['instances']))

        # Unpause in reverse order
        _snapshotvms.add(
            vmtasks.LinearUnPauseVMs(
                reversed(
                    self._store['instances'])))

        _snapshotvms.add(vmtasks.LinearThawVMs(self._store['instances']))

        super(SerialWorkflow, self).initflow(_snapshotvms, composite=composite)

    def discover(self):
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        instances = get_vms(cntx, self._store['workload_id'])
        for instance in instances:
            del instance['hypervisor_hostname']
            del instance['hypervisor_type']
        return dict(instances=instances)

    def execute(self):
        vmtasks.CreateVMSnapshotDBEntries(
            self._store['context'],
            self._store['instances'],
            self._store['snapshot'])
        result = engines.run(
            self._flow,
            engine_conf='parallel',
            backend={
                'connection': self._store['connection']},
            store=self._store)
