# Copyright (C) 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Handles all requests relating to transferring ownership of workloads.
"""

import datetime
import hashlib
import hmac
import json
import os
import time
import uuid
import functools

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from workloadmgr.db import base
from workloadmgr import exception
from workloadmgr.common.i18n import _, _LE, _LI, _LW
from workloadmgr.workloads import api as workload_api
from workloadmgr.vault import vault
from workloadmgr import auditlog
from workloadmgr import policy

workload_transfer_opts = [
    cfg.IntOpt('workload_transfer_salt_length', default=8,
               help='The number of characters in the salt.'),
    cfg.IntOpt('workload_transfer_key_length', default=16,
               help='The number of characters in the '
               'autogenerated auth key.'), ]

CONF = cfg.CONF
CONF.register_opts(workload_transfer_opts)

LOG = logging.getLogger(__name__)
AUDITLOG = auditlog.getAuditLogger()


def wrap_create_trust(func):
    def trust_create_wrapper(*args, **kwargs):
        args = (args[0].workload_api,) + (args[1:])
        return func(*args, **kwargs)

    return trust_create_wrapper

def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution

    This decorator requires the first 2 args of the wrapped function
    to be (self, context)
    """

    @functools.wraps(func)
    def wrapped(self, context, *args, **kwargs):
        check_policy(context, func.__name__)
        return func(self, context, *args, **kwargs)

    return wrapped


def check_policy(context, action):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }

    _action = 'workload:%s' % action
    policy.enforce(context, _action, target)

class API(base.Base):
    """API for interacting workload transfers."""

    def __init__(self, db_driver=None):
        self.workload_api = workload_api.API()
        super(API, self).__init__(db_driver)

    def _update_workload_ownership_on_media(self, context, workload_id):
        pass

    def _backup_target_for_workload(self, context, workload_id):

        workload_ref = self.db.workload_get(context, workload_id)
        backup_endpoint = None

        for meta in workload_ref['metadata']:
            if meta['key'] == 'backup_media_target':
                backup_endpoint = meta['value']
                break

        if backup_endpoint is None:
            raise exception.InvalidWorkload(
                reason=_("workload record does not contain backup_media_target metadata field"))

        backup_target = vault.get_backup_target(backup_endpoint)

        return backup_target

    @wrap_check_policy
    def get(self, context, transfer_id):
        try:
            transfer_rec = [trans_rec for trans_rec in self.get_all(context)
                            if trans_rec['id'] == transfer_id]
            return transfer_rec[0]
        except:
            raise exception.TransferNotFound(transfer_id=transfer_id)

    @wrap_check_policy
    def delete(self, context, transfer_id):
        """Make the RPC call to delete a workload transfer."""
        transfer_rec = self.get(context, transfer_id)

        workload_id = transfer_rec['workload_id']
        AUDITLOG.log(context, 'Transfer \'' + transfer_id + '\' Delete  Requested')
        workload_ref = self.db.workload_get(context, workload_id)
        if workload_ref['status'] != 'transfer-in-progress':
            LOG.error(_LE("Workload in unexpected state"))

        try:
            # read the workload manager and snapshots record from the nfs share
            # and change user ids and tenant id.
            # This might as well be no nop, but want to make sure transfer is
            # not aborted in the middle leaving user.id and project.id messup
            backup_target = self._backup_target_for_workload(context,
                                                             workload_id)
            backup_target._update_workload_ownership_on_media(context,
                                                              workload_id)

        except Exception as ex:
            LOG.exception(ex)

        self.db.workload_update(context, workload_ref.id,
                                {'status': 'available',
                                 'metadata': {'transfer_id': ""}})
        backup_target.transfers_delete(context, transfer_rec)
        self.workload_api.workload_resume(context, workload_ref.id)

    @wrap_check_policy
    def get_all(self, context, filters=None):
        filters = filters or {}
        transfers = vault.get_all_workload_transfers(context)

        return transfers

    def _get_random_string(self, length):
        """Get a random hex string of the specified length."""
        rndstr = ""

        # Note that the string returned by this function must contain only
        # characters that the recipient can enter on their keyboard. The
        # function ssh224().hexdigit() achieves this by generating a hash
        # which will only contain hexidecimal digits.
        while len(rndstr) < length:
            rndstr += hashlib.sha224(os.urandom(255)).hexdigest()

        return rndstr[0:length]

    def _get_crypt_hash(self, salt, auth_key):
        """Generate a random hash based on the salt and the auth key."""
        return hmac.new(str(salt),
                        str(auth_key),
                        hashlib.sha1).hexdigest()

    @wrap_check_policy
    def create(self, context, workload_id, display_name):
        """Creates an entry in the transfers table."""
        LOG.info(_LI("Generating transfer record for workload %s"), workload_id)
        workload_ref = self.db.workload_get(context, workload_id)

        AUDITLOG.log(context, 'Transfer for workload \'' + workload_id + '\' Create  Requested')
        if context.project_id != workload_ref.project_id:
            raise exception.InvalidWorkload(reason=_("workload does not belong to the tenant"))

        if workload_ref['status'] != "available":
            raise exception.InvalidState(reason=_("Workload is not in 'available' state"))

        # The salt is just a short random string.
        salt = self._get_random_string(CONF.workload_transfer_salt_length)
        auth_key = self._get_random_string(CONF.workload_transfer_key_length)
        crypt_hash = self._get_crypt_hash(salt, auth_key)

        # TODO: Transfer expiry needs to be implemented.
        transfer_rec = {
            'id': str(uuid.uuid4()),
            'status': "transfer-pending",
            'workload_id': workload_id,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'display_name': display_name,
            'salt': salt,
            'crypt_hash': crypt_hash,
            'expires_at': None,
            'created_at': str(datetime.datetime.now()),
        }

        #
        # 1. Mark workload as transfer-in-progress
        #
        try:

            backup_target = self._backup_target_for_workload(context, workload_id)
            transfer_rec_path = backup_target.get_workload_transfers_path(transfer_rec)
            backup_target.put_object(transfer_rec_path, json.dumps(transfer_rec))
        except Exception:
            LOG.error(_LE("Failed to create transfer record "
                          "for %s"), workload_id)
            raise

        self.db.workload_update(context, workload_id,
                                {'status': 'transfer-in-progress',
                                 'metadata': {'transfer_id': transfer_rec['id']}})
        self.workload_api.workload_pause(context, workload_id)

        return {'id': transfer_rec['id'],
                'workload_id': transfer_rec['workload_id'],
                'display_name': transfer_rec['display_name'],
                'auth_key': auth_key,
                'created_at': transfer_rec['created_at']}

    @wrap_create_trust
    @workload_api.create_trust
    @wrap_check_policy
    def _create_trust(self, context, transfer_id, auth_key):
        pass

    @wrap_check_policy
    def accept(self, context, transfer_id, auth_key):
        """Accept a workload that has been offered for transfer."""
        # We must use an elevated context to see the workload that is still
        # owned by the donor.
        self._create_trust(context, transfer_id, auth_key)
        transfer = self.get(context, transfer_id)

        AUDITLOG.log(context, 'Transfer \'' + transfer_id + '\' Accept  Requested')
        crypt_hash = self._get_crypt_hash(transfer['salt'], auth_key)
        if crypt_hash != transfer['crypt_hash']:
            msg = (_("Attempt to transfer %s with invalid auth key.") %
                   transfer_id)
            LOG.error(msg)
            raise exception.InvalidAuthKey(reason=msg)

        workload_id = transfer['workload_id']

        # if the workload id exists on this openstack, then the user is
        # attempting to transfer to a different tenant of the same
        # cloud. We don't support this usecase at this point
        try:
            workload_ref = self.db.workload_get(context, workload_id)
            raise exception.TransferNotAllowed(workload_id=workload_id)
        except exception.TransferNotAllowed:
            raise
        except:
            pass

        try:
            # read the workload manager and snapshots record from the nfs share
            # and change user ids and tenant id
            # Transfer ownership of the workload now, must use an elevated
            # context.
            backup_target = None
            for w in vault.get_workloads(context):
                if workload_id in w:
                    db_path = os.path.join(w, "workload_db")
                    with open(db_path, "r") as f:
                        wdb = json.load(f)
                    for m in wdb['metadata']:
                        if m['key'] == 'backup_media_target':
                            backup_target = vault.get_backup_target(m['value'])
                            break

            if backup_target is None:
                raise exception.WorkloadNotFound(workload_id=workload_id)

            backup_target._update_workload_ownership_on_media(context,
                                                              workload_id)

            # import workload now
            # this is point of no return. How do we make sure we either
            # succeed or fail but won't leave the database in
            # half backed state. (TODO)
            self.workload_api.import_workloads(context, [workload_id], False)
            LOG.info(_LI("Workload %s has been transferred."), workload_id)
        except Exception:
            raise

        try:
            workload_ref = self.db.workload_get(context, workload_id)
            transfer_rec_path = backup_target.get_workload_transfers_path(transfer)
            transfer['status'] = "transfer-completed"
            backup_target.put_object(transfer_rec_path, json.dumps(transfer))

            return {'id': transfer_id,
                    'display_name': transfer['display_name'],
                    'workload_id': workload_ref['id']}
        except Exception:
            LOG.error(_LE("Failed to create transfer record "
                          "for %s"), workload_id)
            raise

    @wrap_check_policy
    # complete is executed on the cloud that transfer is initiated
    def complete(self, context, transfer_id):
        AUDITLOG.log(context, 'Transfer \'' + transfer_id + '\' Complete  Requested')

        transfer = self.get(context, transfer_id)

        if transfer is None:
            raise exception.TransferNotFound(transfer_id=transfer_id)

        workload_id = transfer['workload_id']
        workload_ref = self.db.workload_get(context, workload_id)
        if workload_ref['status'] != 'transfer-in-progress':
            msg = _LE("Workload state is expected in 'transfer-in-progress'. "
                      "The current status is '%s'" % workload_ref['status'])
            LOG.error(msg)
            raise exception.InvalidState(reason=msg)

        # If the workload tenant id is not changed, we will not complete
        # the transfer
        backup_target = self._backup_target_for_workload(context, workload_id)

        wl_path = os.path.join(backup_target.mount_path, "workload_" + workload_id)
        wl_json = backup_target.get_object(os.path.join(wl_path, "workload_db"))
        wl_rec = json.loads(wl_json)
        wl_tenant_id = uuid.UUID(wl_rec.get('project_id', wl_rec.get('tenant_id', None)))
        if wl_tenant_id == uuid.UUID(context.project_id):
            msg = _LE("Workload is not transferred. "
                      "Please abort the transfer instead of complete")
            LOG.error(msg)
            raise exception.InvalidState(reason=msg)

        if transfer['status'] != "transfer-completed":
            msg = _LE("Workload is not transferred. "
                      "Please abort the transfer instead of complete")
            LOG.error(msg)
            raise exception.InvalidState(reason=msg)

        self.db.workload_update(context, workload_ref.id,
                                {'status': 'available',
                                 'metadata': {'transfer_id': ""}})

        self.workload_api.workload_reset(context, workload_id)
        workload_ref = self.db.workload_get(context, workload_id)
        # We should have a timeout
        count = 10
        while workload_ref.status == "resetting" and count:
            time.sleep(3)
            count -= 1
            workload_ref = self.db.workload_get(context, workload_id)

        # make sure we do some additional checks
        snapshots = self.db.snapshot_get_all(context, workload_id=workload_id)
        for snap in snapshots:
            self.db.snapshot_delete(context, snap.id)

        for vm in self.db.workload_vms_get(context, workload_id):
            self.db.workload_vms_delete(context, vm.vm_id, workload_id)
        self.db.workload_delete(context, workload_id)
        backup_target.transfers_delete(context, transfer)
