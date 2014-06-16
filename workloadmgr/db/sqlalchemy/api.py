# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Implementation of SQLAlchemy backend."""

import datetime
import uuid
import warnings
import threading

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

lock = threading.Lock()


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
def service_delete(context, service_id):
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


#### Work load Types #################
""" workload_type functions """
def _set_metadata_for_workload_type(context, workload_type_ref, metadata,
                              purge_metadata=False, session=None):
    """
    Create or update a set of workload_type_metadata for a given workload_type

    :param context: Request context
    :param workload_type_ref: An workload_type object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in workload_type_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'workload_type_id': workload_type_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _workload_type_metadata_update(context, metadata_ref, metadata_values,
                                   session=session)
        else:
            workload_type_metadata_create(context, metadata_values, session=session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                workload_type_metadata_delete(context, metadata_ref, session=session)

@require_context
def workload_type_metadata_create(context, values, session=None):
    """Create an WorkloadTypeMetadata object"""
    metadata_ref = models.WorkloadTypeMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _workload_type_metadata_update(context, metadata_ref, values, session=session)


def _workload_type_metadata_update(context, metadata_ref, values, session=None):
    """
    Used internally by workload_type_metadata_create and workload_type_metadata_update
    """
    if session == None: 
        session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def workload_type_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by workload_type_metadata_create and workload_type_metadata_update
    """
    if session == None: 
        session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _workload_type_update(context, values, workload_type_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    session = get_session()
    if workload_type_id:
        workload_type_ref = workload_type_get(context, workload_type_id, session)
    else:
        workload_type_ref = models.WorkloadTypes()
        if not values.get('id'):
            values['id'] = str(uuid.uuid4())        
    
    workload_type_ref.update(values)
    workload_type_ref.save(session)
    
    _set_metadata_for_workload_type(context, workload_type_ref, metadata, purge_metadata)  
      
    return workload_type_ref


@require_context
def workload_type_create(context, values):
    return _workload_type_update(context, values, None, False)

@require_context
def workload_type_update(context, id, values, purge_metadata=False):
    return _workload_type_update(context, values, id, purge_metadata)

@require_context
def workload_types_get(context, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.WorkloadTypes)\
                       .options(sa_orm.joinedload(models.WorkloadTypes.metadata))\
                       .filter((models.WorkloadTypes.project_id == context.project_id) | (models.WorkloadTypes.is_public == True))

        #TODO(gbasava): filter out deleted workload_types if context disallows it
        workload_types = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadTypesNotFound()
    
    return workload_types

@require_context
def workload_type_get(context, id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.WorkloadTypes)\
                       .options(sa_orm.joinedload(models.WorkloadTypes.metadata))\
                       .filter_by(id=id)

        #TODO(gbasava): filter out deleted workload_types if context disallows it
        workload_types = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadTypesWithIdNotFound(id = id)

    return workload_types

@require_context
def workload_type_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.WorkloadTypes).\
            filter_by(id=id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

#### Workloads ################################################################
""" workload functions """
def _set_metadata_for_workload(context, workload_ref, metadata,
                              purge_metadata=False, session=None):
    """
    Create or update a set of workload_metadata for a given workload

    :param context: Request context
    :param workload_ref: An workload object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in workload_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    import pdb;pdb.set_trace()
    for key, value in metadata.iteritems():
        metadata_values = {'workload_id': workload_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _workload_metadata_update(context, metadata_ref, metadata_values,
                                   session=session)
        else:
            workload_metadata_create(context, metadata_values, session=session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                workload_metadata_delete(context, metadata_ref, session=session)

@require_context
def workload_metadata_create(context, values, session=None):
    """Create an WorkloadMetadata object"""
    metadata_ref = models.WorkloadMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _workload_metadata_update(context, metadata_ref, values, session=session)


def _workload_metadata_update(context, metadata_ref, values, session=None):
    """
    Used internally by workload_metadata_create and workload_metadata_update
    """
    if session == None: 
        session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def workload_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by workload_metadata_create and workload_metadata_update
    """
    if session == None: 
        session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _workload_update(context, values, workload_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    session = get_session()
    if workload_id:
        workload_ref = workload_get(context, workload_id, session)
    else:
        workload_ref = models.Workloads()
        if not values.get('id'):
            values['id'] = str(uuid.uuid4())        
    
    workload_ref.update(values)
    workload_ref.save(session)
    
    if metadata:
        _set_metadata_for_workload(context, workload_ref, metadata, purge_metadata)  
      
    return workload_ref


@require_context
def workload_create(context, values):
    return _workload_update(context, values, None, False)

@require_context
def workload_update(context, id, values, purge_metadata=False):
    return _workload_update(context, values, id, purge_metadata)

@require_context
def workload_get_all(context, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.Workloads)\
                       .options(sa_orm.joinedload(models.Workloads.metadata))\
                       .filter_by(project_id=context.project_id)

        #TODO(gbasava): filter out deleted workloads if context disallows it
        workloads = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadsNotFound()
    
    return workloads

@require_admin_context
def workload_get_all_by_host(context, host, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.Workloads)\
                       .options(sa_orm.joinedload(models.Workloads.metadata))\
                       .filter_by(host=host)

        #TODO(gbasava): filter out deleted workloads if context disallows it
        workloads = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadsNotFound()
    
    return workloads

@require_context
def workload_get_all_by_project(context, project_id, session=None):
    authorize_project_context(context, project_id)    
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.Workloads)\
                       .options(sa_orm.joinedload(models.Workloads.metadata))\
                       .filter_by(project_id=project_id)

        #TODO(gbasava): filter out deleted workloads if context disallows it
        workloads = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadsNotFound()
    
    return workloads
    
@require_context
def workload_get(context, id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.Workloads)\
                       .options(sa_orm.joinedload(models.Workloads.metadata))\
                       .filter_by(id=id)\
                       .filter_by(project_id=context.project_id)

        #TODO(gbasava): filter out deleted workloads if context disallows it
        workloads = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadsWithIdNotFound(id = id)

    return workloads

@require_context
def workload_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.Workloads).\
            filter_by(id=id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

######################################################################################################
@require_context
def workload_vms_create(context, values):
    workload_vm = models.WorkloadVMs()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    workload_vm.update(values)
    workload_vm.save()
    return workload_vm

@require_context
def workload_vms_get(context, workload_id, session=None):
    result = model_query(context, models.WorkloadVMs,
                             session=session).\
        filter_by(workload_id=workload_id).\
        all()

    if not result:
        return []

    return result

@require_context
def workload_vms_delete(context, vm_id, workload_id):
    session = get_session()
    with session.begin():
        session.query(models.WorkloadVMs).\
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
            raise exception.WorkloadsNotFound(
                _("No workload with id %s"), scheduledjob.id)

        dbjob.update(values)
        dbjob.save(session=session)
        return dbjob

@require_context
def snapshot_get(context, snapshot_id, session=None):
    result = model_query(   context, models.Snapshots, session=session).\
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
    if not values.get('size'):
        values['size'] = 0
    if not values.get('uploaded_size'):
        values['uploaded_size'] = 0
    if not values.get('progress_percent'):
        values['progress_percent'] = 0    
    snapshot.update(values)
    snapshot.save()
    return snapshot

@require_context
def snapshot_update(context, snapshot_id, values):
    try:
        lock.acquire()
        session = get_session()
        with session.begin():
            snapshot = model_query(context, models.Snapshots,
                                 session=session, read_deleted="yes").\
                filter_by(id=snapshot_id).first()
    
            if not snapshot:
                lock.release()
                raise exception.SnapshotNotFound(
                    _("No snapshot with id %(snapshot_id)s") % locals())
    
            if not values.get('uploaded_size'):
                if values.get('uploaded_size_incremental'):
                    values['uploaded_size'] =  snapshot.uploaded_size + values.get('uploaded_size_incremental') 
                    if not values.get('progress_percent') and snapshot.size > 0:
                        values['progress_percent'] = (100 * values.get('uploaded_size'))/snapshot.size
    
    
            snapshot.update(values)
            snapshot.save(session=session)
    finally:
        lock.release()
    return snapshot

@require_context
def snapshot_delete(context, snapshot_id):
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
    if not values.get('size'):
        values['size'] = 0
        
    snapshot_vm.update(values)
    snapshot_vm.save()
    return snapshot_vm

@require_context
def snapshot_vms_get(context, snapshot_id, session=None):
    result = model_query(context, models.SnapshotVMs,session=session).\
        filter_by(snapshot_id=snapshot_id).\
        all()

    if not result:
        raise exception.VMsOfSnapshotNotFound(snapshot_id=snapshot_id)

    return result

@require_context
def snapshot_vm_get(context, vm_id, snapshot_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.SnapshotVMs)\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(snapshot_id=snapshot_id)

        #TODO(gbasava): filter out deleted snapshot vm if context disallows it
        snapshot_vm = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.VMsOfSnapshotNotFound(snapshot_id = snapshot_id)
    
    return snapshot_vm            

@require_context
def snapshot_vm_update(context, vm_id, snapshot_id, values):
    session = get_session()
    with session.begin():
        snapshot_vm = model_query(context, models.SnapshotVMs, session=session, read_deleted="yes")\
                               .filter_by(vm_id=vm_id)\
                               .filter_by(snapshot_id=snapshot_id).first()

        if not snapshot_vm:
            raise exception.SnapshotNotFound(
                _("No snapshot VM with id %(vm_id)s") % locals())

        snapshot_vm.update(values)
        snapshot_vm.save(session=session)
    return snapshot_vm

@require_context
def snapshot_vm_delete(context, vm_id, snapshot_id):
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
def vm_recent_snapshot_delete(context, vm_id):
    session = get_session()
    with session.begin():
        session.query(models.VMRecentSnapshot).\
            filter_by(vm_id=vm_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

""" snapshot vm resource functions """
def _set_metadata_for_snapshot_vm_resource(context, snapshot_vm_resource_ref, metadata,
                              purge_metadata=False, session=None):
    """
    Create or update a set of snapshot_vm_resource_metadata for a given snapshot resource

    :param context: Request context
    :param snapshot_vm_resource_ref: An snapshot_vm_resource object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in snapshot_vm_resource_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'snapshot_vm_resource_id': snapshot_vm_resource_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _snapshot_vm_resource_metadata_update(context, metadata_ref, metadata_values,
                                   session=session)
        else:
            snapshot_vm_resource_metadata_create(context, metadata_values, session=session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                snapshot_vm_resource_metadata_delete(context, metadata_ref, session=session)

@require_context
def snapshot_vm_resource_metadata_create(context, values, session=None):
    """Create an SnapshotVMResourceMetadata object"""
    metadata_ref = models.SnapshotVMResourceMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _snapshot_vm_resource_metadata_update(context, metadata_ref, values, session=session)


def _snapshot_vm_resource_metadata_update(context, metadata_ref, values, session=None):
    """
    Used internally by snapshot_vm_resource_metadata_create and snapshot_vm_resource_metadata_update
    """
    if session == None: 
        session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def snapshot_vm_resource_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by snapshot_vm_resource_metadata_create and snapshot_vm_resource_metadata_update
    """
    if session == None: 
        session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _snapshot_vm_resource_update(context, values, snapshot_vm_resource_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    session = get_session()
    if snapshot_vm_resource_id:
        snapshot_vm_resource_ref = snapshot_vm_resource_get(context, snapshot_vm_resource_id, session)
    else:
        snapshot_vm_resource_ref = models.SnapshotVMResources()
        if not values.get('size'):
            values['size'] = 0        
    
    snapshot_vm_resource_ref.update(values)
    snapshot_vm_resource_ref.save(session)
    
    _set_metadata_for_snapshot_vm_resource(context, snapshot_vm_resource_ref, metadata, purge_metadata)  
      
    return snapshot_vm_resource_ref


@require_context
def snapshot_vm_resource_create(context, values):
    return _snapshot_vm_resource_update(context, values, None, False)

@require_context
def snapshot_vm_resource_update(context, snapshot_vm_resource_id, values, purge_metadata=False):
   
    return _snapshot_vm_resource_update(context, values, snapshot_vm_resource_id, purge_metadata)

@require_context
def snapshot_vm_resources_get(context, vm_id, snapshot_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.SnapshotVMResources)\
                       .options(sa_orm.joinedload(models.SnapshotVMResources.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(snapshot_id=snapshot_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        snapshot_vm_resources = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotVMResourcesNotFound(vm_id = vm_id, snapshot_id = snapshot_id)
    
    return snapshot_vm_resources

@require_context
def snapshot_vm_resource_get_by_resource_name(context, vm_id, snapshot_id, resource_name, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.SnapshotVMResources)\
                       .options(sa_orm.joinedload(models.SnapshotVMResources.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(snapshot_id=snapshot_id)\
                       .filter_by(resource_name=resource_name)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        snapshot_vm_resource = query.first()

    except sa_orm.exc.NoResultFound:
        snapshot_vm_resource = None

    return snapshot_vm_resource

@require_context
def snapshot_vm_resource_get(context, id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.SnapshotVMResources)\
                       .options(sa_orm.joinedload(models.SnapshotVMResources.metadata))\
                       .filter_by(id=id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        snapshot_vm_resources = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotVMResourcesWithIdNotFound(id = id)

    return snapshot_vm_resources

@require_context
def snapshot_vm_resource_delete(context, id, vm_id, snapshot_id):
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

""" disk resource snapshot functions """
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

@require_context
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
    if session == None: 
        session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref


def vm_disk_resource_snap_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by vm_disk_resource_snap_metadata_create and vm_disk_resource_snap_metadata_update
    """
    if session == None: 
        session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _vm_disk_resource_snap_update(context, values, vm_disk_resource_snap_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    session = get_session()
    if vm_disk_resource_snap_id:
        vm_disk_resource_snap_ref = vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session)
    else:
        vm_disk_resource_snap_ref = models.VMDiskResourceSnaps()
        if not values.get('size'):
            values['size'] = 0

    vm_disk_resource_snap_ref.update(values)
    vm_disk_resource_snap_ref.save(session)
    
    _set_metadata_for_vm_disk_resource_snap(context, vm_disk_resource_snap_ref, metadata, purge_metadata)  
      
    return vm_disk_resource_snap_ref


@require_context
def vm_disk_resource_snap_create(context, values):
    
    return _vm_disk_resource_snap_update(context, values, None, False)

@require_context
def vm_disk_resource_snap_update(context, vm_disk_resource_snap_id, values, purge_metadata=False):
   
    return _vm_disk_resource_snap_update(context, values, vm_disk_resource_snap_id, purge_metadata)

@require_context
def vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, session=None):
    if session == None: 
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
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.VMDiskResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMDiskResourceSnaps.metadata))\
                       .filter_by(snapshot_vm_resource_id = snapshot_vm_resource_id)\
                       .filter_by(top= True)

        #TODO(gbasava): filter out resource snapshots if context disallows it
        vm_disk_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        vm_disk_resource_snap = None
    
    return vm_disk_resource_snap

@require_context
def vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.VMDiskResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMDiskResourceSnaps.metadata))\
                       .filter_by(id=vm_disk_resource_snap_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_disk_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(vm_disk_resource_snap_id = vm_disk_resource_snap_id)
    
    return vm_disk_resource_snap


@require_context
def vm_disk_resource_snaps_delete(context, snapshot_vm_resource_id, session=None):
    if session == None: 
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

@require_context
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
    if session == None: 
        session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def vm_network_resource_snap_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by vm_network_resource_snap_metadata_create and vm_network_resource_snap_metadata_update
    """
    if session == None: 
        session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _vm_network_resource_snap_update(context, values, vm_network_resource_snap_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    session = get_session()
    if vm_network_resource_snap_id:
        vm_network_resource_snap_ref = vm_network_resource_snap_get(context, vm_network_resource_snap_id, session)
    else:
        vm_network_resource_snap_ref = models.VMNetworkResourceSnaps()
    
    vm_network_resource_snap_ref.update(values)
    vm_network_resource_snap_ref.save(session)
    
    _set_metadata_for_vm_network_resource_snap(context, vm_network_resource_snap_ref, metadata, purge_metadata)  
      
    return vm_network_resource_snap_ref


@require_context
def vm_network_resource_snap_create(context, values):
    
    return _vm_network_resource_snap_update(context, values, None, False)

@require_context
def vm_network_resource_snap_update(context, vm_network_resource_snap_id, values, purge_metadata=False):
   
    return _vm_network_resource_snap_update(context, values, vm_network_resource_snap_id, purge_metadata)

@require_context
def vm_network_resource_snaps_get(context, snapshot_vm_resource_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.VMNetworkResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMNetworkResourceSnaps.metadata))\
                       .filter_by(vm_network_resource_snap_id=snapshot_vm_resource_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        vm_network_resource_snaps = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(snapshot_vm_resource_id = snapshot_vm_resource_id)
    
    return vm_network_resource_snaps

@require_context
def vm_network_resource_snap_get(context, vm_network_resource_snap_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.VMNetworkResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMNetworkResourceSnaps.metadata))\
                       .filter_by(vm_network_resource_snap_id=vm_network_resource_snap_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_network_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise 
    
    return vm_network_resource_snap


@require_context
def vm_network_resource_snaps_delete(context, snapshot_vm_network_resource_id):
    session = get_session()
    with session.begin():
        session.query(models.VMNetworkResourceSnaps).\
            filter_by(snapshot_vm_network_resource_id=snapshot_vm_network_resource_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

""" security group rule snapshot functions """
def _set_metadata_for_vm_security_group_rule_snap(context, vm_security_group_rule_snap_ref, metadata,
                              purge_metadata=False, session=None):
    """
    Create or update a set of vm_security_group_rule_snap_metadata for a given snapshot

    :param context: Request context
    :param vm_security_group_rule_snap_ref: An vm_security_group_rule_snap object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in vm_security_group_rule_snap_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'vm_security_group_rule_snap_id': vm_security_group_rule_snap_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _vm_security_group_rule_snap_metadata_update(context, metadata_ref, metadata_values,
                                   session=session)
        else:
            vm_security_group_rule_snap_metadata_create(context, metadata_values, session=session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                vm_security_group_rule_snap_metadata_delete(context, metadata_ref, session=session)

@require_context
def vm_security_group_rule_snap_metadata_create(context, values, session=None):
    """Create an VMSecurityGroupRuleSnapMetadata object"""
    metadata_ref = models.VMSecurityGroupRuleSnapMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _vm_security_group_rule_snap_metadata_update(context, metadata_ref, values, session=session)

def _vm_security_group_rule_snap_metadata_update(context, metadata_ref, values, session=None):
    """
    Used internally by vm_security_group_rule_snap_metadata_create and vm_security_group_rule_snap_metadata_update
    """
    if session == None: 
        session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def vm_security_group_rule_snap_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by vm_security_group_rule_snap_metadata_create and vm_security_group_rule_snap_metadata_update
    """
    if session == None: 
        session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, values, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    session = get_session()
    if id and vm_security_group_snap_id:
        vm_security_group_rule_snap_ref = vm_security_group_rule_snap_get(context, id, vm_security_group_snap_id, session)
    else:
        vm_security_group_rule_snap_ref = models.VMSecurityGroupRuleSnaps()
    
    vm_security_group_rule_snap_ref.update(values)
    vm_security_group_rule_snap_ref.save(session)
    
    _set_metadata_for_vm_security_group_rule_snap(context, vm_security_group_rule_snap_ref, metadata, purge_metadata)  
      
    return vm_security_group_rule_snap_ref

@require_context
def vm_security_group_rule_snap_create(context, values):
    
    return _vm_security_group_rule_snap_update(context, None, None, values, False)

@require_context
def vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, values, purge_metadata=False):
   
    return _vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, values, purge_metadata)

@require_context
def vm_security_group_rule_snaps_get(context, vm_security_group_snap_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.VMSecurityGroupRuleSnaps)\
                       .options(sa_orm.joinedload(models.VMSecurityGroupRuleSnaps.metadata))\
                       .filter_by(vm_security_group_snap_id=vm_security_group_snap_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        vm_security_group_rule_snaps = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapsNotFound(vm_security_group_snap_id = vm_security_group_snap_id)
    
    return vm_security_group_rule_snaps

@require_context
def vm_security_group_rule_snap_get(context, id, vm_security_group_snap_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.VMSecurityGroupRuleSnaps)\
                       .options(sa_orm.joinedload(models.VMSecurityGroupRuleSnaps.metadata))\
                       .filter_by(id=id)\
                       .filter_by(vm_security_group_snap_id=vm_security_group_snap_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_security_group_rule_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise 
    
    return vm_security_group_rule_snap

@require_context
def vm_security_group_rule_snaps_delete(context, id, vm_security_group_snap_id):
    session = get_session()
    with session.begin():
        session.query(models.VMSecurityGroupRuleSnaps).\
            filter_by(id=id).\
            filter_by(vm_security_group_snap_id=vm_security_group_snap_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
            
def get_metadata_value(metadata, key, default=None):
    for kvpair in metadata:
        if kvpair['key'] == key:
            return kvpair['value']
    return default

# Restore Functions

@require_context
def restore_get(context, restore_id, session=None):
    result = model_query(context, models.Restores,
                             session=session).\
        filter_by(id=restore_id).\
        first()

    if not result:
        raise exception.RestoreNotFound(restore_id=restore_id)

    return result

@require_admin_context
def restore_get_all(context):
    return model_query(context, models.Restores).all()

@require_context
def restore_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    return model_query(context, models.Restores).\
        filter_by(project_id=project_id).all()
        
@require_context
def restore_get_all_by_project_snapshot(context, project_id, snapshot_id):
    authorize_project_context(context, project_id)
    return model_query(context, models.Restores).\
        filter_by(project_id=project_id).\
        filter_by(snapshot_id=snapshot_id).all()

@require_context
def restore_show(context, restore_id, session=None):
    result = model_query(context, models.Restores,
                             session=session).\
        filter_by(id=restore_id).\
        first()

    if not result:
        raise exception.RestoreNotFound(restore_id=restore_id)

    return result

@require_context
def restore_create(context, values):
    restore = models.Restores()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    if not values.get('size'):
        values['size'] = 0        
    if not values.get('uploaded_size'):
        values['uploaded_size'] = 0
    if not values.get('progress_percent'):
        values['progress_percent'] = 0         
    restore.update(values)
    restore.save()
    return restore

@require_context
def restore_update(context, restore_id, values):
    try:
        lock.acquire()
        session = get_session()
        with session.begin():
            restore = model_query(context, models.Restores,
                                 session=session, read_deleted="yes").\
                filter_by(id=restore_id).first()
    
            if not restore:
                lock.release()
                raise exception.RestoreNotFound(
                    _("No restore with id %(restore_id)s") % locals())
                
            if not values.get('uploaded_size'):
                if values.get('uploaded_size_incremental'):
                    values['uploaded_size'] =  restore.uploaded_size + values.get('uploaded_size_incremental') 
                    if not values.get('progress_percent'):
                        values['progress_percent'] = (100 * values.get('uploaded_size'))/restore.size
    
            restore.update(values)
            restore.save(session=session)
    finally:
        lock.release()
    return restore

@require_context
def restore_delete(context, restore_id):
    session = get_session()
    with session.begin():
        session.query(models.Restores).\
            filter_by(id=restore_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

@require_context
def restored_vm_create(context, values):
    restored_vm = models.RestoredVMs()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    restored_vm.update(values)
    restored_vm.save()
    return restored_vm

@require_context
def restored_vm_update(context, vm_id, restore_id, values):
    session = get_session()
    with session.begin():
        restore_vm = model_query(context, models.RestoredVMs, session=session, read_deleted="yes")\
                               .filter_by(vm_id=vm_id)\
                               .filter_by(restore_id=restore_id).first()

        if not restore_vm:
            raise exception.RestoreNotFound(
                _("No restored VM with id %(vm_id)s") % locals())

        restore_vm.update(values)
        restore_vm.save(session=session)
    return restore_vm

@require_context
def restored_vm_get(context, restore_id, session=None):
    result = model_query(context, models.RestoredVMs,
                             session=session).\
        filter_by(restore_id=restore_id).\
        all()

    if not result:
        raise exception.VMsOfRestoreNotFound(restore_id=restore_id)

    return result

@require_context
def restored_vm_delete(context, vm_id, restore_id):
    session = get_session()
    with session.begin():
        session.query(models.RestoredVMs).\
            filter_by(vm_id=vm_id).\
            filter_by(restore_id=restore_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

""" restore vm resource functions """
def _set_metadata_for_restored_vm_resource(context, restored_vm_resource_ref, metadata,
                              purge_metadata=False, session=None):
    """
    Create or update a set of restored_vm_resource_metadata for a given restored resource

    :param context: Request context
    :param restored_vm_resource_ref: An restored_vm_resource object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in restored_vm_resource_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'restored_vm_resource_id': restored_vm_resource_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _restored_vm_resource_metadata_update(context, metadata_ref, metadata_values,
                                   session=session)
        else:
            restored_vm_resource_metadata_create(context, metadata_values, session=session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                restored_vm_resource_metadata_delete(context, metadata_ref, session=session)

@require_context
def restored_vm_resource_metadata_create(context, values, session=None):
    """Create an RestoredVMResourceMetadata object"""
    metadata_ref = models.RestoredVMResourceMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _restored_vm_resource_metadata_update(context, metadata_ref, values, session=session)


def _restored_vm_resource_metadata_update(context, metadata_ref, values, session=None):
    """
    Used internally by restored_vm_resource_metadata_create and restored_vm_resource_metadata_update
    """
    if session == None: 
        session = get_session()
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def restored_vm_resource_metadata_delete(context, metadata_ref, session=None):
    """
    Used internally by restored_vm_resource_metadata_create and restored_vm_resource_metadata_update
    """
    if session == None: 
        session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _restored_vm_resource_update(context, values, restored_vm_resource_id, purge_metadata=False):
    
    metadata = values.pop('metadata', {})
    
    session = get_session()
    if restored_vm_resource_id:
        restored_vm_resource_ref = restored_vm_resource_get(context, restored_vm_resource_id, session)
    else:
        restored_vm_resource_ref = models.RestoredVMResources()
    
    restored_vm_resource_ref.update(values)
    restored_vm_resource_ref.save(session)
    
    _set_metadata_for_restored_vm_resource(context, restored_vm_resource_ref, metadata, purge_metadata)  
      
    return restored_vm_resource_ref


@require_context
def restored_vm_resource_create(context, values):
    return _restored_vm_resource_update(context, values, None, False)

@require_context
def restored_vm_resource_update(context, restored_vm_resource_id, values, purge_metadata=False):
   
    return _restored_vm_resource_update(context, values, restored_vm_resource_id, purge_metadata)

@require_context
def restored_vm_resources_get(context, vm_id, restore_id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.RestoredVMResources)\
                       .options(sa_orm.joinedload(models.RestoredVMResources.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(restore_id=restore_id)

        #TODO(gbasava): filter out deleted restores if context disallows it
        restored_vm_resources = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.RestoredVMResourcesNotFound(vm_id = vm_id, restore_id = restore_id)
    
    return restored_vm_resources

@require_context
def restored_vm_resource_get_by_resource_name(context, vm_id, restore_id, resource_name, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.RestoredVMResources)\
                       .options(sa_orm.joinedload(models.RestoredVMResources.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(restore_id=restore_id)\
                       .filter_by(resource_name=resource_name)

        #TODO(gbasava): filter out deleted restores if context disallows it
        restored_vm_resources = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.RestoredVMResourcesWithNameNotFound(vm_id = vm_id, 
                                                        restore_id = restore_id,
                                                        resource_name = resource_name)

    return restored_vm_resources

@require_context
def restored_vm_resource_get(context, id, session=None):
    if session == None: 
        session = get_session()
    try:
        query = session.query(models.RestoredVMResources)\
                       .options(sa_orm.joinedload(models.RestoredVMResources.metadata))\
                       .filter_by(id=id)

        #TODO(gbasava): filter out deleted restored if context disallows it
        restored_vm_resources = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.RestoredVMResourcesWithIdNotFound(id = id)

    return restored_vm_resources

@require_context
def restored_vm_resource_delete(context, id, vm_id, restore_id):
    session = get_session()
    with session.begin():
        session.query(models.RestoredVMResources).\
            filter_by(id=id).\
            filter_by(vm_id=vm_id).\
            filter_by(restore_id=restore_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
