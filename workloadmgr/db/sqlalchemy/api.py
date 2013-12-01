# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Implementation of SQLAlchemy backend."""

import datetime
import uuid
import warnings

import sqlalchemy
import sqlalchemy.orm as sa_orm
import sqlalchemy.sql as sa_sql

from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.expression import literal_column
from sqlalchemy.sql import func

from workloadmgr.common import sqlalchemyutils
from workloadmgr import db
from workloadmgr.db.sqlalchemy import models
from workloadmgr.db.sqlalchemy.session import get_session
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import timeutils
from workloadmgr.openstack.common import uuidutils
from workloadmgr.apscheduler import job


FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


def is_admin_context(context):
    """Indicates if the request context is an administrator."""
    if not context:
        warnings.warn(_('Use of empty request context is deprecated'),
                      DeprecationWarning)
        raise Exception('die')
    return context.is_admin


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def authorize_project_context(context, project_id):
    """Ensures a request has permission to access the given project."""
    if is_user_context(context):
        if not context.project_id:
            raise exception.NotAuthorized()
        elif context.project_id != project_id:
            raise exception.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures a request has permission to access the given user."""
    if is_user_context(context):
        if not context.user_id:
            raise exception.NotAuthorized()
        elif context.user_id != user_id:
            raise exception.NotAuthorized()


def authorize_quota_class_context(context, class_name):
    """Ensures a request has permission to access the given quota class."""
    if is_user_context(context):
        if not context.quota_class:
            raise exception.NotAuthorized()
        elif context.quota_class != class_name:
            raise exception.NotAuthorized()


def require_admin_context(f):
    """Decorator to require admin request context.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]):
            raise exception.AdminRequired()
        return f(*args, **kwargs)
    return wrapper


def require_context(f):
    """Decorator to require *any* user or admin context.

    This does no authorization for user or project access matching, see
    :py:func:`authorize_project_context` and
    :py:func:`authorize_user_context`.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]) and not is_user_context(args[0]):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper

def model_query(context, *args, **kwargs):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: context to query under
    :param session: if present, the session to use
    :param read_deleted: if present, overrides context's read_deleted field.
    :param project_only: if present and context is user-type, then restrict
            query to match the context's project_id.
    """
    session = kwargs.get('session') or get_session()
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only')

    query = session.query(*args)

    if read_deleted == 'no':
        query = query.filter_by(deleted=False)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter_by(deleted=True)
    else:
        raise Exception(
            _("Unrecognized read_deleted value '%s'") % read_deleted)

    if project_only and is_user_context(context):
        query = query.filter_by(project_id=context.project_id)

    return query


def exact_filter(query, model, filters, legal_keys):
    """Applies exact match filtering to a query.

    Returns the updated query.  Modifies filters argument to remove
    filters consumed.

    :param query: query to apply filters to
    :param model: model object the query applies to, for IN-style
                  filtering
    :param filters: dictionary of filters; values that are lists,
                    tuples, sets, or frozensets cause an 'IN' test to
                    be performed, while exact matching ('==' operator)
                    is used for other values
    :param legal_keys: list of keys to apply exact filtering to
    """

    filter_dict = {}

    # Walk through all the keys
    for key in legal_keys:
        # Skip ones we're not filtering on
        if key not in filters:
            continue

        # OK, filtering on this key; what value do we search for?
        value = filters.pop(key)

        if isinstance(value, (list, tuple, set, frozenset)):
            # Looking for values in a list; apply to query directly
            column_attr = getattr(model, key)
            query = query.filter(column_attr.in_(value))
        else:
            # OK, simple exact match; save for later
            filter_dict[key] = value

    # Apply simple exact matches
    if filter_dict:
        query = query.filter_by(**filter_dict)

    return query


###################


@require_admin_context
def service_destroy(context, service_id):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        service_ref.delete(session=session)


@require_admin_context
def service_get(context, service_id, session=None):
    result = model_query(
        context,
        models.Service,
        session=session).\
        filter_by(id=service_id).\
        first()
    if not result:
        raise exception.ServiceNotFound(service_id=service_id)

    return result


@require_admin_context
def service_get_all(context, disabled=None):
    query = model_query(context, models.Service)

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


@require_admin_context
def service_get_all_by_topic(context, topic):
    return model_query(
        context, models.Service, read_deleted="no").\
        filter_by(disabled=False).\
        filter_by(topic=topic).\
        all()


@require_admin_context
def service_get_by_host_and_topic(context, host, topic):
    result = model_query(
        context, models.Service, read_deleted="no").\
        filter_by(disabled=False).\
        filter_by(host=host).\
        filter_by(topic=topic).\
        first()
    if not result:
        raise exception.ServiceNotFound(service_id=None)
    return result


@require_admin_context
def service_get_all_by_host(context, host):
    return model_query(
        context, models.Service, read_deleted="no").\
        filter_by(host=host).\
        all()


@require_admin_context
def _service_get_all_topic_subquery(context, session, topic, subq, label):
    sort_value = getattr(subq.c, label)
    return model_query(context, models.Service,
                       func.coalesce(sort_value, 0),
                       session=session, read_deleted="no").\
        filter_by(topic=topic).\
        filter_by(disabled=False).\
        outerjoin((subq, models.Service.host == subq.c.host)).\
        order_by(sort_value).\
        all()


@require_admin_context
def service_get_by_args(context, host, binary):
    result = model_query(context, models.Service).\
        filter_by(host=host).\
        filter_by(binary=binary).\
        first()

    if not result:
        raise exception.HostBinaryNotFound(host=host, binary=binary)

    return result


@require_admin_context
def service_create(context, values):
    service_ref = models.Service()
    service_ref.update(values)
    if not FLAGS.enable_new_services:
        service_ref.disabled = True
    service_ref.save()
    return service_ref


@require_admin_context
def service_update(context, service_id, values):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        service_ref.update(values)
        service_ref.save(session=session)


###################


@require_context
def workload_get(context, workload_id, session=None):
    result = model_query(context, models.WorkloadMgr,
                             session=session, project_only=True).\
        filter_by(id=workload_id).\
        first()

    if not result:
        raise exception.WorkloadMgrNotFound(workload_id=workload_id)

    return result

@require_context
def workload_show(context, workload_id, session=None):
    result = model_query(context, models.WorkloadMgr,
                             session=session, project_only=True).\
        filter_by(id=workload_id).\
        first()
    if not result:
        raise exception.WorkloadMgrNotFound(workload_id=workload_id)

    return result

@require_admin_context
def workload_get_all(context):
    return model_query(context, models.WorkloadMgr).all()


@require_admin_context
def workload_get_all_by_host(context, host):
    return model_query(context, models.WorkloadMgr).filter_by(host=host).all()


@require_context
def workload_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    return model_query(context, models.WorkloadMgr).\
        filter_by(project_id=project_id).all()


@require_context
def workload_create(context, values):
    workload = models.WorkloadMgr()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    workload.update(values)
    workload.save()
    return workload


@require_context
def workload_update(context, workload_id, values):
    session = get_session()
    with session.begin():
        workload = model_query(context, models.WorkloadMgr,
                             session=session, read_deleted="yes").\
            filter_by(id=workload_id).first()

        if not workload:
            raise exception.WorkloadMgrNotFound(
                _("No workload with id %(workload_id)s") % locals())

        workload.update(values)
        workload.save(session=session)
    return workload


@require_context
def workload_destroy(context, workload_id):
    session = get_session()
    with session.begin():
        session.query(models.WorkloadMgr).\
            filter_by(id=workload_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

@require_context
def workload_vms_create(context, values):
    workload_vm = models.WorkloadMgrVMs()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    workload_vm.update(values)
    workload_vm.save()
    return workload_vm

@require_context
def workload_vms_get(context, workload_id, session=None):
    result = model_query(context, models.WorkloadMgrVMs,
                             session=session).\
        filter_by(workload_id=workload_id).\
        all()

    if not result:
        raise exception.VMsofWorkloadMgrNotFound(workload_id=workload_id)

    return result

@require_context
def workload_vms_destroy(context, vm_id, workload_id):
    session = get_session()
    with session.begin():
        session.query(models.WorkloadMgrVMs).\
            filter_by(vm_id=vm_id).\
            filter_by(workload_id=workload_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
                    
@require_context
def scheduledjob_create(context, scheduledjob):
    values = scheduledjob.__getstate__()
    schjob = models.ScheduledJobs()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    schjob.update(values)
    schjob.save()
    return schjob

@require_context
def scheduledjob_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.ScheduledJobs).\
            filter_by(id=id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

@require_context
def scheduledjob_get(context):
    scheduledjob = []
    rows =  model_query(context, models.ScheduledJobs).all()
    for row in rows:
        try:
            j = job.Job.__new__(job.Job)
            job_dict = dict(row.__dict__)
            j.__setstate__(job_dict)
            scheduledjob.append(j)
        except Exception:
            logger.exception('Unable to schedule jobs')
    return scheduledjob

@require_context
def scheduledjob_update(context, scheduledjob):
    session = get_session()
    values = scheduledjob.__getstate__()
    del values['_sa_instance_state']
    with session.begin():
        dbjob = model_query(context, models.ScheduledJobs,
                             session=session, read_deleted="yes").\
            filter_by(id=scheduledjob.id).first()

        if not dbjob:
            raise exception.WorkloadMgrNotFound(
                _("No workload with id %s"), scheduledjob.id)

        dbjob.update(values)
        dbjob.save(session=session)
        return dbjob

@require_context
def snapshot_get(context, snapshot_id, session=None):
    result = model_query(context, models.Snapshots,
                             session=session).\
        filter_by(id=snapshot_id).\
        first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result

@require_admin_context
def snapshot_get_all(context):
    return model_query(context, models.Snapshots).all()

@require_context
def snapshot_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    return model_query(context, models.Snapshots).\
        filter_by(project_id=project_id).all()
        
@require_context
def snapshot_get_all_by_project_workload(context, project_id, workload_id):
    authorize_project_context(context, project_id)
    return model_query(context, models.Snapshots).\
        filter_by(project_id=project_id).\
        filter_by(workload_id=workload_id).all()

@require_context
def snapshot_show(context, snapshot_id, session=None):
    result = model_query(context, models.Snapshots,
                             session=session).\
        filter_by(id=snapshot_id).\
        first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result

@require_context
def snapshot_create(context, values):
    snapshot = models.Snapshots()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    snapshot.update(values)
    snapshot.save()
    return snapshot

@require_context
def snapshot_update(context, snapshot_id, values):
    session = get_session()
    with session.begin():
        snapshot = model_query(context, models.Snapshots,
                             session=session, read_deleted="yes").\
            filter_by(id=snapshot_id).first()

        if not snapshot:
            raise exception.SnapshotNotFound(
                _("No snapshot with id %(snapshot_id)s") % locals())

        snapshot.update(values)
        snapshot.save(session=session)
    return snapshot

@require_context
def snapshot_destroy(context, snapshot_id):
    session = get_session()
    with session.begin():
        session.query(models.Snapshots).\
            filter_by(id=snapshot_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

@require_context
def snapshot_vm_create(context, values):
    snapshot_vm = models.SnapshotVMs()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    snapshot_vm.update(values)
    snapshot_vm.save()
    return snapshot_vm

@require_context
def snapshot_vm_get(context, snapshot_id, session=None):
    result = model_query(context, models.SnapshotVMs,
                             session=session).\
        filter_by(snapshot_id=snapshot_id).\
        all()

    if not result:
        raise exception.VMsOfSnapshotNotFound(snapshot_id=snapshot_id)

    return result

@require_context
def snapshot_vm_destroy(context, vm_id, snapshot_id):
    session = get_session()
    with session.begin():
        session.query(models.SnapshotVMs).\
            filter_by(vm_id=vm_id).\
            filter_by(snapshot_id=snapshot_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

@require_context
def vm_recent_snapshot_create(context, values):
    vm_recent_snapshot = models.VMRecentSnapshot()
    vm_recent_snapshot.update(values)
    vm_recent_snapshot.save()
    return vm_recent_snapshot

@require_context
def vm_recent_snapshot_get(context, vm_id, session=None):
    result = model_query(context, models.VMRecentSnapshot,
                             session=session).\
        filter_by(vm_id=vm_id).\
        first()

    if not result:
        raise exception.VMRecentSnapshotNotFound(vm_id=vm_id)

    return result

@require_context
def vm_recent_snapshot_update(context, vm_id, values):
    session = get_session()
    with session.begin():
        vm_recent_snapshot = model_query(context, models.VMRecentSnapshot,
                             session=session, read_deleted="yes").\
            filter_by(vm_id = vm_id).first()

        if not vm_recent_snapshot:
            #raise exception.VMRecentSnapshotNotFound(
            #    _("Recent snapshot for VM %(vm_id)s is not found") % locals())
            values['vm_id'] = vm_id
            vm_recent_snapshot = models.VMRecentSnapshot()
            
        vm_recent_snapshot.update(values)
        vm_recent_snapshot.save(session=session)
        
    return vm_recent_snapshot

@require_context
def vm_recent_snapshot_destroy(context, vm_id):
    session = get_session()
    with session.begin():
        session.query(models.VMRecentSnapshot).\
            filter_by(vm_id=vm_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

require_context
def snapshot_vm_resource_create(context, values):
    snapshot_vm_resource = models.SnapshotVMResources()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    snapshot_vm_resource.update(values)
    snapshot_vm_resource.save()
    return snapshot_vm_resource

@require_context
def snapshot_vm_resources_get(context, vm_id, snapshot_id, session=None):
    result = model_query(context, models.SnapshotVMResources,
                             session=session).\
        filter_by(vm_id=vm_id).\
        filter_by(snapshot_id=snapshot_id).\
        all()

    if not result:
        raise exception.SnapshotVMResourcesNotFound(vm_id = vm_id, snapshot_id = snapshot_id)

    return result

@require_context
def snapshot_vm_resource_get_by_resource_name(context, vm_id, snapshot_id, resource_name, session=None):
    result = model_query(context, models.SnapshotVMResources,
                             session=session).\
        filter_by(vm_id=vm_id).\
        filter_by(snapshot_id=snapshot_id).\
        filter_by(resource_name=resource_name).\
        first()

    if not result:
        raise exception.SnapshotVMResourcesWithNameNotFound(vm_id = vm_id, 
                                                        snapshot_id = snapshot_id,
                                                        resource_name = resource_name)

    return result

def snapshot_vm_resource_get(context, id, session=None):
    result = model_query(context, models.SnapshotVMResources,
                             session=session).\
        filter_by(id=id).\
        first()

    if not result:
        raise exception.SnapshotVMResourcesWithIdNotFound(id = id)

    return result

@require_context
def snapshot_vm_resource_destroy(context, id, vm_id, snapshot_id):
    session = get_session()
    with session.begin():
        session.query(models.SnapshotVMResources).\
            filter_by(id=id).\
            filter_by(vm_id=vm_id).\
            filter_by(snapshot_id=snapshot_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

def _set_metadata_for_vm_disk_resource_snap(context, vm_disk_resource_snap_ref, metadata,
                              purge_metadata=False, session=None):
    """
    Create or update a set of vm_disk_resource_snap_metadata for a given snapshot

    :param context: Request context
    :param image_ref: An vm_disk_resource_snap object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in vm_disk_resource_snap_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'vm_disk_resource_snap_id': vm_disk_resource_snap_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _vm_disk_resource_snap_metadata_update(context, metadata_ref, metadata_values,
                                   session=session)
        else:
            vm_disk_resource_snap_metadata_create(context, metadata_values, session=session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                vm_disk_resource_snap_metadata_delete(context, metadata_ref, session=session)


def vm_disk_resource_snap_metadata_create(context, values, session=None):
    """Create an VMDiskResourceSnapMetadata object"""
    metadata_ref = models.VMDiskResourceSnapMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _vm_disk_resource_snap_metadata_update(context, metadata_ref, values, session=session)


def _vm_disk_resource_snap_metadata_update(context, metadata_ref, values, session=None):
    """
    Used internally by vm_disk_resource_snap_metadata_create and vm_disk_resource_snap_metadata_update
    """
    session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref


def vm_disk_resource_snap_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by vm_disk_resource_snap_metadata_create and vm_disk_resource_snap_metadata_update
    """
    session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _vm_disk_resource_snap_update(context, values, snapshot_vm_resource_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    if snapshot_vm_resource_id:
        vm_disk_resource_snap_ref = vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, None)
    else:
        vm_disk_resource_snap_ref = models.VMDiskResourceSnaps()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    vm_disk_resource_snap_ref.update(values)
    vm_disk_resource_snap_ref.save()
    
    _set_metadata_for_vm_disk_resource_snap(context, vm_disk_resource_snap_ref, metadata, purge_metadata)  
      
    return vm_disk_resource_snap_ref


@require_context
def vm_disk_resource_snap_create(context, values):
    
    return _vm_disk_resource_snap_update(context, values, None, False)

def vm_disk_resource_snap_update(context, snapshot_vm_resource_id, values, purge_metadata=False):
   
    return _vm_disk_resource_snap_update(context, values, snapshot_vm_resource_id, purge_metadata)

@require_context
def vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, session=None):
    session = get_session()
    try:
        query = session.query(models.VMDiskResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMDiskResourceSnaps.metadata))\
                       .filter_by(snapshot_vm_resource_id=snapshot_vm_resource_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        vm_disk_resource_snaps = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(snapshot_vm_resource_id = snapshot_vm_resource_id)
    
    return vm_disk_resource_snaps

@require_context
def vm_disk_resource_snap_get_top(context, snapshot_vm_resource_id, session=None):
    session = get_session()
    try:
        query = session.query(models.VMDiskResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMDiskResourceSnaps.metadata))\
                       .filter_by(snapshot_vm_resource_id = snapshot_vm_resource_id)\
                       .filter_by(top= True)

        #TODO(gbasava): filter out resource snapshots if context disallows it
        vm_disk_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(snapshot_vm_resource_id = snapshot_vm_resource_id)
    
    return vm_disk_resource_snap

@require_context
def vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session=None):
    session = get_session()
    try:
        query = session.query(models.VMDiskResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMDiskResourceSnaps.metadata))\
                       .filter_by(id= vm_disk_resource_snap_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_disk_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(vm_disk_resource_snap_id = vm_disk_resource_snap_id)
    
    return vm_disk_resource_snap


@require_context
def vm_disk_resource_snaps_destroy(context, snapshot_vm_resource_id):
    session = get_session()
    with session.begin():
        session.query(models.VMDiskResourceSnaps).\
            filter_by(snapshot_vm_resource_id=snapshot_vm_resource_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
    
""" network resource snapshot functions """
def _set_metadata_for_vm_network_resource_snap(context, vm_network_resource_snap_ref, metadata,
                              purge_metadata=False, session=None):
    """
    Create or update a set of vm_network_resource_snap_metadata for a given snapshot

    :param context: Request context
    :param vm_network_resource_snap_ref: An vm_network_resource_snap object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in vm_network_resource_snap_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'vm_network_resource_snap_id': vm_network_resource_snap_ref.vm_network_resource_snap_id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _vm_network_resource_snap_metadata_update(context, metadata_ref, metadata_values,
                                   session=session)
        else:
            vm_network_resource_snap_metadata_create(context, metadata_values, session=session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                vm_network_resource_snap_metadata_delete(context, metadata_ref, session=session)


def vm_network_resource_snap_metadata_create(context, values, session=None):
    """Create an VMNetworkResourceSnapMetadata object"""
    metadata_ref = models.VMNetworkResourceSnapMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _vm_network_resource_snap_metadata_update(context, metadata_ref, values, session=session)


def _vm_network_resource_snap_metadata_update(context, metadata_ref, values, session=None):
    """
    Used internally by vm_network_resource_snap_metadata_create and vm_network_resource_snap_metadata_update
    """
    session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref


def vm_network_resource_snap_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by vm_network_resource_snap_metadata_create and vm_network_resource_snap_metadata_update
    """
    session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _vm_network_resource_snap_update(context, values, snapshot_vm_resource_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    if snapshot_vm_resource_id:
        vm_network_resource_snap_ref = vm_network_resource_snaps_get(context, snapshot_vm_resource_id, None)
    else:
        vm_network_resource_snap_ref = models.VMNetworkResourceSnaps()
    
    vm_network_resource_snap_ref.update(values)
    vm_network_resource_snap_ref.save()
    
    _set_metadata_for_vm_network_resource_snap(context, vm_network_resource_snap_ref, metadata, purge_metadata)  
      
    return vm_network_resource_snap_ref


@require_context
def vm_network_resource_snap_create(context, values):
    
    return _vm_network_resource_snap_update(context, values, None, False)

def vm_network_resource_snap_update(context, snapshot_vm_resource_id, values, purge_metadata=False):
   
    return _vm_network_resource_snap_update(context, values, snapshot_vm_resource_id, purge_metadata)

@require_context
def vm_network_resource_snaps_get(context, snapshot_vm_resource_id, session=None):
    session = get_session()
    try:
        query = session.query(models.VMNetworkResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMNetworkResourceSnaps.metadata))\
                       .filter_by(vm_network_resource_snap_id==snapshot_vm_resource_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        vm_network_resource_snaps = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(snapshot_vm_resource_id = snapshot_vm_resource_id)
    
    return vm_network_resource_snaps

@require_context
def vm_network_resource_snap_get(context, snapshot_vm_resource_id, session=None):
    session = get_session()
    try:
        query = session.query(models.VMNetworkResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMNetworkResourceSnaps.metadata))\
                       .filter_by(vm_network_resource_snap_id=snapshot_vm_resource_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_network_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(snapshot_vm_resource_id = snapshot_vm_resource_id)
    
    return vm_network_resource_snap


@require_context
def vm_network_resource_snaps_destroy(context, snapshot_vm_network_resource_id):
    session = get_session()
    with session.begin():
        session.query(models.VMNetworkResourceSnaps).\
            filter_by(snapshot_vm_network_resource_id=snapshot_vm_network_resource_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
            
def get_metadata_value(metadata, key):
    for metadata in metadata:
        if metadata['key'] == key:
            return metadata['value']
    return None