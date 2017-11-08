# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
Handles all requests relating to volumes + cinder.
"""

import copy
import sys
from functools import wraps

from oslo_config import cfg

from cinderclient import exceptions as cinder_exception
from cinderclient import service_catalog
from cinderclient.v2 import client as cinder_client

from workloadmgr.db import base
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB
from workloadmgr import exception
from workloadmgr.common import context as wlm_context
from workloadmgr.openstack.common import log as logging

from workloadmgr.common import clients

cinder_opts = [
    cfg.StrOpt('cinder_catalog_info',
               default='volume:cinder:publicURL',
               help='Info to match when looking for cinder in the service '
                    'catalog. Format is : separated values of the form: '
                    '<service_type>:<service_name>:<endpoint_type>'),
    cfg.StrOpt('cinder_production_endpoint_template',
               default='http://localhost:8776/v1/%(project_id)s',  # None,
               help='Override service catalog lookup with template for cinder '
                    'endpoint e.g. http://localhost:8776/v1/%(project_id)s'),
    cfg.StrOpt('os_region_name',
               default=None,
               help='region name of this node'),
    cfg.IntOpt('cinder_http_retries',
               default=3,
               help='Number of cinderclient retries on failed http calls'),
    cfg.BoolOpt('cinder_api_insecure',
                default=True,
                help='Allow to perform insecure SSL requests to cinder'),
    cfg.BoolOpt('cinder_cross_az_attach',
                default=True,
                help='Allow attach between instance and volume in different '
                'availability zones.'),
]

CONF = cfg.CONF
CONF.register_opts(cinder_opts)

LOG = logging.getLogger(__name__)


def _get_trusts(user_id, tenant_id):

    db = WorkloadMgrDB().db
    context = wlm_context.RequestContext(
        user_id=user_id,
        project_id=tenant_id)

    settings = db.setting_get_all_by_project(
        context, context.project_id)

    trust = [t for t in settings if t.type == "trust_id" and
             t.project_id == context.project_id and
             t.user_id == context.user_id]
    return trust


def cinderclient(context, refresh_token=False):

    # FIXME: the cinderclient ServiceCatalog object is mis-named.
    #        It actually contains the entire access blob.
    # Only needed parts of the service catalog are passed in, see
    # nova/context.py.
    compat_catalog = {
        # TODO(gbasava): Check this...   'access': {'serviceCatalog':
        # context.service_catalog or []}
        'access': []
    }
    sc = service_catalog.ServiceCatalog(compat_catalog)
    if CONF.cinder_production_endpoint_template:
        url = CONF.cinder_production_endpoint_template % context.to_dict()
    else:
        info = CONF.cinder_catalog_info
        service_type, service_name, endpoint_type = info.split(':')
        # extract the region if set in configuration
        if CONF.os_region_name:
            attr = 'region'
            filter_value = CONF.os_region_name
        else:
            attr = None
            filter_value = None
        url = sc.url_for(attr=attr,
                         filter_value=filter_value,
                         service_type=service_type,
                         service_name=service_name,
                         endpoint_type=endpoint_type)

    LOG.debug(_('Cinderclient connection created using URL: %s') % url)

    trust = _get_trusts(context.user_id, context.tenant_id)

    if hasattr(context, 'user_domain_id'):
        if context.user_domain_id is None:
            user_domain_id = 'default'
        else:
            user_domain_id = context.user_domain_id
    elif hasattr(context, 'user_domain'):
        if context.user_domain is None:
            user_domain_id = 'default'
        else:
            user_domain_id = context.user_domain
    else:
        user_domain_id = 'default'

    # pick the first trust. Usually it should not be more than one trust
    if len(trust):
        trust_id = trust[0].value

        if refresh_token:
            context = wlm_context.RequestContext(
                username=CONF.keystone_authtoken.admin_user,
                password=CONF.keystone_authtoken.admin_password,
                trust_id=trust_id,
                tenant_id=context.project_id,
                trustor_user_id=context.user_id,
                user_domain_id=CONF.triliovault_user_domain_id,
                is_admin=False)
        else:
            context = wlm_context.RequestContext(
                trustor_user_id=context.user_id,
                project_id=context.project_id,
                auth_token=context.auth_token,
                trust_id=trust_id,
                user_domain_id=user_domain_id,
                is_admin=False)

        clients.initialise()
        client_plugin = clients.Clients(context)
        cinderclient = client_plugin.client("cinder")
        cinderclient.client_plugin = cinderclient
    else:
        cinderclient = cinder_client.Client(context.user_id,
                                            context.auth_token,
                                            project_id=context.project_id,
                                            auth_url=url,
                                            domain_name=user_domain_id,
                                            insecure=CONF.cinder_api_insecure,
                                            retries=CONF.cinder_http_retries)
        # noauth extracts user_id:project_id from auth_token
        cinderclient.client.auth_token = context.auth_token or '%s:%s' % (
            context.user_id, context.project_id)
        cinderclient.client.management_url = url
        if "v1" in url.split('/'):
            cinderclient.volume_api_version = 1
        else:
            cinderclient.volume_api_version = 2
    return cinderclient


def _untranslate_volume_summary_view(context, vol):
    """Maps keys for volumes summary view."""
    d = {}
    d['id'] = vol.id
    d['status'] = vol.status
    d['size'] = vol.size
    d['availability_zone'] = vol.availability_zone
    d['created_at'] = vol.created_at

    d['attach_time'] = ""
    d['mountpoint'] = ""

    if vol.attachments:
        att = vol.attachments[0]
        d['attach_status'] = 'attached'
        d['instance_uuid'] = att['server_id']
        d['mountpoint'] = att['device']
    else:
        d['attach_status'] = 'detached'

    if hasattr(vol, 'display_name'):
        d['display_name'] = vol.display_name
    else:
        d['display_name'] = vol.name

    if hasattr(vol, 'display_description'):
        d['display_description'] = vol.display_description
    else:
        d['display_description'] = vol.description

    # TODO(jdg): Information may be lost in this translation
    d['volume_type_id'] = vol.volume_type
    d['snapshot_id'] = vol.snapshot_id

    d['volume_metadata'] = []
    for key, value in vol.metadata.items():
        item = {}
        item['key'] = key
        item['value'] = value
        d['volume_metadata'].append(item)

    if hasattr(vol, 'volume_image_metadata'):
        d['volume_image_metadata'] = copy.deepcopy(vol.volume_image_metadata)

    return d


def _untranslate_snapshot_summary_view(context, snapshot):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = snapshot.id
    d['status'] = snapshot.status
    d['progress'] = snapshot.progress
    d['size'] = snapshot.size
    d['created_at'] = snapshot.created_at

    if hasattr(snapshot, 'display_name'):
        d['display_name'] = snapshot.display_name
    else:
        d['display_name'] = snapshot.name

    if hasattr(snapshot, 'display_description'):
        d['display_description'] = snapshot.display_description
    else:
        d['display_description'] = snapshot.description

    d['volume_id'] = snapshot.volume_id
    d['project_id'] = snapshot.project_id
    d['volume_size'] = snapshot.size

    return d


def _translate_volume_exception(volume_id, exc_value):
    if isinstance(exc_value, cinder_exception.NotFound):
        return exception.VolumeNotFound(volume_id=volume_id)
    elif isinstance(exc_value, cinder_exception.BadRequest):
        return exception.InvalidInput(reason=exc_value.message)
    return exc_value


def _reraise_translated_volume_exception(volume_id=None):
    """Transform the exception for the volume but keep its traceback
    intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_volume_exception(volume_id, exc_value)
    raise new_exc, None, exc_trace


def exception_handler(ignore_exception=False, refresh_token=True):
    def exception_handler_decorator(func):
        @wraps(func)
        def func_wrapper(*args, **argv):
            try:
                try:
                    client = cinderclient(args[1])
                    argv.update({'client': client})
                    return func(*args, **argv)
                except cinder_exception.Unauthorized as unauth_ex:
                    if refresh_token is True:
                        argv.pop('client')
                        client = cinderclient(args[1],
                                              refresh_token=True)
                        argv.update({'client': client})
                        return func(*args, **argv)
            except Exception as ex:
                if ignore_exception is False:
                    LOG.exception(ex)
                    _reraise_translated_volume_exception(None)

        return func_wrapper
    return exception_handler_decorator


class API(base.Base):
    """API for interacting with the volume manager."""

    @exception_handler()
    def get_types(self, context, **kwargs):
        client = kwargs['client']
        types = client.volume_types.list()
        return types

    @exception_handler()
    def get(self, context, volume_id, no_translate=False, **kwargs):
        client = kwargs['client']
        item = client.volumes.get(volume_id)
        if no_translate:
            return item
        else:
            return _untranslate_volume_summary_view(context, item)

        # self._reraise_translated_volume_exception(volume_id)

    @exception_handler()
    def get_all(self, context, search_opts={}):
        client = search_opts['client']
        search_opts.pop('client')
        items = client.volumes.list(detailed=True)
        rval = []

        for item in items:
            rval.append(_untranslate_volume_summary_view(context, item))

        return rval

    def check_attach(self, context, volume, instance=None):
        # TODO(vish): abstract status checking?
        if volume['status'] != "available":
            msg = _("status must be available")
            raise exception.InvalidVolume(reason=msg)
        if volume['attach_status'] == "attached":
            msg = _("already attached")
            raise exception.InvalidVolume(reason=msg)
        if instance and not CONF.cinder_cross_az_attach:
            if instance['availability_zone'] != volume['availability_zone']:
                msg = _("Instance and volume not in same availability_zone")
                raise exception.InvalidVolume(reason=msg)

    def check_detach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] == "available":
            msg = _("already detached")
            raise exception.InvalidVolume(reason=msg)

    @exception_handler()
    def reserve_volume(self, context, volume, **kwargs):
        client = kwargs['client']
        client.volumes.reserve(volume['id'])

    @exception_handler()
    def unreserve_volume(self, context, volume, **kwargs):
        client = kwargs['client']
        client.volumes.unreserve(volume['id'])

    @exception_handler()
    def begin_detaching(self, context, volume, **kwargs):
        client = kwargs['client']
        client.volumes.begin_detaching(volume['id'])

    @exception_handler()
    def roll_detaching(self, context, volume, **kwargs):
        client = kwargs['client']
        client.volumes.roll_detaching(volume['id'])

    @exception_handler()
    def attach(self, context, volume, instance_uuid, mountpoint, **kwargs):
        client = kwargs['client']
        client.volumes.attach(volume['id'], instance_uuid,
                              mountpoint)

    @exception_handler()
    def detach(self, context, volume, **kwargs):
        client = kwargs['client']
        client.volumes.detach(volume['id'])

    @exception_handler()
    def set_bootable(self, context, volume, **kwargs):
        client = kwargs['client']
        client.volumes._action('os-set_bootable',
                               volume['id'],
                               {'bootable': True})

    @exception_handler()
    def initialize_connection(self, context, volume, connector, **kwargs):
        client = kwargs['client']
        return client.\
            volumes.initialize_connection(volume['id'], connector)

    @exception_handler()
    def terminate_connection(self, context, volume, connector, **kwargs):
        client = kwargs['client']
        return client.\
            volumes.terminate_connection(volume['id'], connector)

    @exception_handler()
    def create(self, context, size, name, description, snapshot=None,
               image_id=None, volume_type=None, metadata=None,
               availability_zone=None, **kwargs):

        if snapshot is not None:
            snapshot_id = snapshot['id']
        else:
            snapshot_id = None

        client = kwargs['client']
        createargs = dict(snapshot_id=snapshot_id,
                          volume_type=volume_type,
                          user_id=context.user_id,
                          project_id=context.project_id,
                          availability_zone=availability_zone,
                          metadata=metadata,
                          imageRef=image_id)

        createargs['name'] = name
        createargs['description'] = description

        item = client.volumes.create(size, **createargs)
        return _untranslate_volume_summary_view(context, item)

    @exception_handler()
    def delete(self, context, volume, **kwargs):
        client = kwargs['client']
        client.volumes.delete(volume['id'])

    def update(self, context, volume, fields):
        raise NotImplementedError()

    @exception_handler()
    def get_snapshot(self, context, snapshot_id, **kwargs):
        client = kwargs['client']
        item = client.volume_snapshots.get(snapshot_id)
        return _untranslate_snapshot_summary_view(context, item)

    @exception_handler()
    def get_all_snapshots(self, context, **kwargs):
        client = kwargs['client']
        items = client.volume_snapshots.list(detailed=True)
        rvals = []

        for item in items:
            rvals.append(_untranslate_snapshot_summary_view(context, item))

        return rvals

    @exception_handler()
    def create_snapshot(self, context, volume, name, description, **kwargs):
        client = kwargs['client']
        item = client.volume_snapshots.create(volume['id'], False,
                                              name, description)
        return _untranslate_snapshot_summary_view(context, item)

    @exception_handler()
    def create_snapshot_force(self, context, volume, name,
                              description, **kwargs):
        client = kwargs['client']
        item = client.volume_snapshots.create(volume['id'], True,
                                              name, description)

        return _untranslate_snapshot_summary_view(context, item)

    @exception_handler()
    def delete_snapshot(self, context, snapshot, **kwargs):
        client = kwargs['client']
        client.volume_snapshots.delete(snapshot['id'])

    def get_volume_metadata(self, context, volume):
        raise NotImplementedError()

    def delete_volume_metadata(self, context, volume, key):
        raise NotImplementedError()

    def update_volume_metadata(self, context, volume, metadata, delete=False):
        raise NotImplementedError()

    def get_volume_metadata_value(self, volume, key):
        raise NotImplementedError()
