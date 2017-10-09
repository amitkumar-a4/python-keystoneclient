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
from workloadmgr import utils

import vmtasks
import workflow


LOG = logging.getLogger(__name__)


def get_vms(cntx, restore_id):
    db = vmtasks.WorkloadMgrDB().db
    restore = db.restore_get(cntx, restore_id)
    snapshot = db.snapshot_get(cntx, restore.snapshot_id)

    restore_options = pickle.loads(str(restore.pickle))
    snapshot_vms = db.snapshot_vms_get(cntx, snapshot.id)

    snapshots_vms_to_be_restored = []
    for snapshot_vm in snapshot_vms:
        instance_options = utils.get_instance_restore_options(
            restore_options, snapshot_vm.vm_id, restore_options['type'])
        if not instance_options:
            snapshots_vms_to_be_restored.append(snapshot_vm)
        elif instance_options.get('include', True) == True:
            snapshots_vms_to_be_restored.append(snapshot_vm)

    snapshot_vms = snapshots_vms_to_be_restored

    vms_without_power_sequence = []
    for snapshot_vm in snapshot_vms:
        vm = {'vm_id': snapshot_vm.vm_id,
              'vm_name': snapshot_vm.vm_name,
              'keyname': db.get_metadata_value(snapshot_vm.metadata,
                                               'key_name'),
              'keydata': db.get_metadata_value(snapshot_vm.metadata,
                                               'key_data'),
              'hypervisor_hostname': 'None',
              'hypervisor_type': 'QEMU'}
        instance_options = utils.get_instance_restore_options(
            restore_options, snapshot_vm.vm_id, restore_options['type'])
        if instance_options and \
           'power' in instance_options and \
           instance_options['power'] and \
           'sequence' in instance_options['power'] and \
           instance_options['power']['sequence']:
            pass
        else:
            vms_without_power_sequence.append(vm)

    vms_with_power_sequence = []
    sequence = 0
    while (len(vms_with_power_sequence) +
           len(vms_without_power_sequence)) < len(snapshot_vms):
        for snapshot_vm in snapshot_vms:
            vm = {'vm_id': snapshot_vm.vm_id,
                  'vm_name': snapshot_vm.vm_name,
                  'keyname': db.get_metadata_value(snapshot_vm.metadata,
                                                   'key_name'),
                  'keydata': db.get_metadata_value(snapshot_vm.metadata,
                                                   'key_data'),
                  'hypervisor_hostname': 'None',
                  'hypervisor_type': 'QEMU'}

            instance_options = utils.get_instance_restore_options(
                restore_options, snapshot_vm.vm_id, restore_options['type'])
            if instance_options and \
               'power' in instance_options and \
               instance_options['power'] and \
               'sequence' in instance_options['power'] and \
               instance_options['power']['sequence']:
                if sequence == int(instance_options['power']['sequence']):
                    vms_with_power_sequence.append(vm)
        sequence = sequence + 1

    vms = vms_with_power_sequence + vms_without_power_sequence
    return vms


class InplaceRestoreWorkflow(object):
    """
      Inplace Restore Workflow
    """

    def __init__(self, name, store):
        self._name = name
        self._store = store
        cntx = amqp.RpcContext.from_dict(self._store['context'])
        self._store['instances'] = get_vms(cntx, self._store['restore']['id'])
        for index, item in enumerate(self._store['instances']):
            self._store['instance_' + str(index)] = item
            self._store['restored_instance_' + str(index)] = item

    def initflow(self, pre_poweron=None, post_poweron=None):
        self._flow = lf.Flow('InplaceRestoreFlow')

        # Check if any pre restore conditions
        self._flow.add(vmtasks.UnorderedPreRestore(self._store['instances']))

        # linear poweroff VMs
        self._flow.add(vmtasks.LinearPowerOffVMs(self._store['instances']))

        # unordered inplace restore VMs
        self._flow.add(vmtasks.LinearRestoreVMsData(self._store['instances']))

        if pre_poweron:
            self._flow.add(pre_poweron)

        # linear poweron VMs
        self._flow.add(vmtasks.LinearPowerOnVMs(self._store['instances']))

        if post_poweron:
            self._flow.add(post_poweron)

    def execute(self):
        result = engines.run(
            self._flow,
            engine_conf='parallel',
            backend={
                'connection': self._store['connection']},
            store=self._store)
        restore = pickle.loads(
            self._store['restore']['pickle'].encode(
                'ascii', 'ignore'))
        if 'type' in restore and restore['type'] == "vmware":
            compute_service = nova.API(production=True)
            search_opts = {}
            search_opts['deep_discover'] = '1'
            cntx = amqp.RpcContext.from_dict(self._store['context'])
            compute_service.get_servers(cntx, search_opts=search_opts)
