# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Implementation of SQLAlchemy backend."""

from datetime import datetime, timedelta
import os
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
from sqlalchemy import and_

from workloadmgr.common import sqlalchemyutils
from workloadmgr import db
from workloadmgr.db.sqlalchemy import models
from workloadmgr.db.sqlalchemy.session import get_session
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import timeutils
from workloadmgr.openstack.common import uuidutils
from workloadmgr.apscheduler import job
from workloadmgr.vault import vault
from workloadmgr.openstack.common.gettextutils import _

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
    read_deleted = kwargs.get('read_deleted') 
    if read_deleted == None and context != None:
        read_deleted = context.read_deleted
    project_only = kwargs.get('project_only')

    query = session.query(*args)
    if read_deleted == 'no':
        query = query.filter_by(deleted=False)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter_by(deleted=True)
    else:
        raise Exception(_("Unrecognized read_deleted value '%s'") % read_deleted)
    if context:
        if project_only and is_user_context(context):
            query = query.filter_by(project_id=context.project_id)
        elif project_only:
             query = query.filter_by(project_id=context.project_id)
    if 'get_hidden' in kwargs:     
        if kwargs.get('get_hidden', False) == False:
            query = query.filter_by(hidden=False)

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
        service_ref = _service_get(context, service_id, session=session)
        service_ref.delete(session=session)

@require_admin_context
def service_get(context, service_id):
    session = get_session()
    return _service_get(context, service_id, session)

@require_admin_context
def _service_get(context, service_id, session):
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
    session = get_session()
    query = model_query(context, models.Service, session=session)

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


@require_admin_context
def service_get_all_by_topic(context, topic):
    session = get_session()
    return model_query(
        context, models.Service, session=session, read_deleted="no").\
        filter_by(disabled=False).\
        filter_by(topic=topic).\
        all()


@require_admin_context
def service_get_by_host_and_topic(context, host, topic):
    session = get_session()
    result = model_query(
        context, models.Service, session=session, read_deleted="no").\
        filter_by(disabled=False).\
        filter_by(host=host).\
        filter_by(topic=topic).\
        first()
    if not result:
        raise exception.ServiceNotFound(service_id=None)
    return result


@require_admin_context
def service_get_all_by_host(context, host):
    session = get_session()
    return model_query(
        context, models.Service, session=session, read_deleted="no").\
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
    session = get_session()
    result = model_query(context, models.Service, session=session,).\
        filter_by(host=host).\
        filter_by(binary=binary).\
        first()

    if not result:
        raise exception.HostBinaryNotFound(host=host, binary=binary)

    return result


@require_admin_context
def service_create(context, values):
    session = get_session()
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
        service_ref = _service_get(context, service_id, session=session)
        service_ref.update(values)
        service_ref.save(session=session)


#### Work load Types #################
""" workload_type functions """
@require_context
def _set_metadata_for_workload_type(context, workload_type_ref, metadata,
                                    purge_metadata, session):
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
            _workload_type_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _workload_type_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _workload_type_metadata_delete(context, metadata_ref, session)

@require_context
def _workload_type_metadata_create(context, values, session):
    """Create an WorkloadTypeMetadata object"""
    metadata_ref = models.WorkloadTypeMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _workload_type_metadata_update(context, metadata_ref, values, session)

@require_context
def workload_type_metadata_create(context, values):
    """Create an WorkloadTypeMetadata object"""
    session = get_session()
    return _workload_type_metadata_create(context, values, session)

@require_context
def _workload_type_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by workload_type_metadata_create and workload_type_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _workload_type_metadata_delete(context, metadata_ref, session):
    """
    Used internally by workload_type_metadata_create and workload_type_metadata_update
    """
    metadata_ref.delete(session=session)
    return metadata_ref
@require_context
def _workload_type_update(context, values, workload_type_id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if workload_type_id:
        workload_type_ref = workload_type_get(context, workload_type_id, session)
    else:
        workload_type_ref = models.WorkloadTypes()
        if not values.get('id'):
            values['id'] = str(uuid.uuid4())        
    
    workload_type_ref.update(values)
    workload_type_ref.save(session)
    
    _set_metadata_for_workload_type(context, workload_type_ref, metadata, purge_metadata, session)  
      
    return workload_type_ref


@require_context
def workload_type_create(context, values):
    session = get_session()
    return _workload_type_update(context, values, None, False, session)

@require_context
def workload_type_update(context, id, values, purge_metadata=False):
    session = get_session()
    return _workload_type_update(context, values, id, purge_metadata, session)

@require_context
def workload_types_get(context):
    session = get_session()
    try:
        query = model_query(context, models.WorkloadTypes, session=session,
                            read_deleted="no")\
                       .options(sa_orm.joinedload(models.WorkloadTypes.metadata))\
                       .filter((models.WorkloadTypes.project_id == context.project_id) | (models.WorkloadTypes.is_public == True))

        #TODO(gbasava): filter out deleted workload_types if context disallows it
        workload_types = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadTypesNotFound()
    
    return workload_types

@require_context
def workload_type_get(context, id):
    session = get_session()
    try:
        query = session.query(models.WorkloadTypes)\
                       .options(sa_orm.joinedload(models.WorkloadTypes.metadata))\
                       .filter_by(id=id)

        #TODO(gbasava): filter out deleted workload_types if context disallows it
        workload_types = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadTypeNotFound(workload_type_id = id)

    if workload_types is None:
        raise exception.WorkloadTypeNotFound(workload_type_id = id)

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
                               purge_metadata, session):
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

    for key, value in metadata.iteritems():
        metadata_values = {'workload_id': workload_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _workload_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _workload_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _workload_metadata_delete(context, metadata_ref, session=session)

@require_context
def _workload_metadata_create(context, values, session):
    """Create an WorkloadMetadata object"""
    metadata_ref = models.WorkloadMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _workload_metadata_update(context, metadata_ref, values, session)

@require_context
def workload_metadata_create(context, values, session):
    """Create an WorkloadMetadata object"""
    session = get_session()
    return _workload_metadata_create(context, values, session)

@require_context
def _workload_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by workload_metadata_create and workload_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _workload_metadata_delete(context, metadata_ref, session):
    """
    Used internally by workload_metadata_create and workload_metadata_update
    """
    metadata_ref.delete(session=session)

def _workload_update(context, values, workload_id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if workload_id:
        workload_ref = _workload_get(context, workload_id, session)
    else:
        workload_ref = models.Workloads()
        if not values.get('id'):
            values['id'] = str(uuid.uuid4())        
    
    workload_ref.update(values)
    workload_ref.save(session)
    
    if metadata:
        _set_metadata_for_workload(context, workload_ref, metadata, purge_metadata, session=session)  
      
    return workload_ref


@require_context
def workload_create(context, values):
    session = get_session()
    return _workload_update(context, values, None, False, session)

@require_context
def workload_update(context, id, values, purge_metadata=False):
    session = get_session()
    return _workload_update(context, values, id, purge_metadata, session)

@require_context
def workload_get_all(context, **kwargs):
        qs =  model_query( context, models.Workloads, **kwargs).\
                                options(sa_orm.joinedload(models.Workloads.metadata))

        if is_admin_context(context):
           if 'nfs_share' in kwargs and kwargs['nfs_share'] is not None and kwargs['nfs_share'] != '':
              qs = qs.filter(and_(models.Workloads.metadata.any(models.WorkloadMetadata.key.in_(['backup_media_target'])),\
                             models.Workloads.metadata.any(models.WorkloadMetadata.value.in_([kwargs['nfs_share']]))))
           else:
                if 'dashboard_item' in kwargs:
                   if kwargs.get('dashboard_item') ==  'activities':
                      if 'time_in_minutes' in kwargs:
                          time_in_minutes = int(kwargs.get('time_in_minutes'))
                      else:
                           time_in_minutes = 0
                      time_delta = ((time_in_minutes / 60) / 24) * -1
                      qs = model_query( context,
                                 models.Workloads.id,
                                 models.Workloads.deleted,
                                 models.Workloads.deleted_at,
                                 models.Workloads.display_name,
                                 models.Workloads.status,
                                 models.Workloads.created_at,
                                 models.Workloads.user_id,
                                 models.Workloads.project_id,
                                 **kwargs). \
                                 filter(or_(models.Workloads.created_at > func.adddate(func.now(), time_delta),
                                 models.Workloads.deleted_at > func.adddate(func.now(), time_delta)))
           if 'all_workloads' in kwargs and kwargs['all_workloads'] is not True:   
               qs = qs.filter_by(project_id=context.project_id)
        else:
             qs = qs.filter_by(project_id=context.project_id)
        if 'project_list' and 'user_list' in kwargs:
           project_list = kwargs['project_list']
           user_list = kwargs['user_list']
           if isinstance(project_list, list) and isinstance(user_list, list):
              if 'exclude' in kwargs and kwargs['exclude'] is True:
                 qs = qs.filter( models.Workloads.project_id.notin_(project_list) | models.Workloads.user_id.notin_(user_list)  )
              else:
                 qs = qs.filter(models.Workloads.project_id.in_(project_list), models.Workloads.user_id.in_(user_list))
           else:
               error = _('Project list and user list should be list')
               raise exception.ErrorOccurred(reason=error)

        if 'project_list' in kwargs and 'user_list' not in kwargs:
            project_list = kwargs['project_list']
            qs = model_query( context, models.Workloads.id, **kwargs)
            if isinstance(project_list, list):
                if 'exclude_project' in kwargs and kwargs['exclude_project'] is True:
                    qs = qs.filter((models.Workloads.project_id.notin_(project_list)) )
                else:
                    qs = qs.filter((models.Workloads.project_id.in_(project_list)) )
            else:
                error = _('Project list should be list')
                raise exception.ErrorOccurred(reason=error)

        if 'workload_list' in kwargs:
           workload_list = kwargs['workload_list']
           if isinstance(workload_list, list):
              qs = model_query( context, models.Workloads.id, **kwargs)
              if 'exclude_workload' in kwargs and kwargs['exclude_workload'] is True:
                 qs = qs.filter(and_(models.Workloads.id.notin_(workload_list)) )
              else:
                 qs = qs.filter(and_(models.Workloads.id.in_(workload_list)) )
           else:
               error = _('Workload list should be list')
               raise exception.ErrorOccurred(reason=error)


        qs = qs.order_by(models.Workloads.created_at.desc())

        if 'page_number' in kwargs and kwargs['page_number'] is not None and kwargs['page_number'] != '':
           page_size = setting_get(context,'page_size')
           return qs.limit(int(page_size)).offset(int(page_size)*(int(kwargs['page_number'])-1)).all()
        else:
             return qs.all()

@require_context
def _workload_get(context, id, session, **kwargs):
    try:
        workload = model_query(
                     context, models.Workloads, session=session, **kwargs).\
                     options(sa_orm.joinedload(models.Workloads.metadata)).\
                     filter_by(id=id).first()

        #TODO(gbasava): filter out deleted workloads if context disallows it
      
        if workload is None:
            raise exception.WorkloadNotFound(workload_id=id)

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadNotFound(workload_id=id)

    return workload

@require_context
def workload_get(context, id, **kwargs):
    session = get_session() 
    return _workload_get(context, id, session, **kwargs)   

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

#### WorkloadVMs ################################################################
""" workload_vms functions """
def _set_metadata_for_workload_vms(context, workload_vm_ref, metadata,
                                    purge_metadata, session):
    """
    Create or update a set of workload_vms_metadata for a given workload_vm

    :param context: Request context
    :param workload_vm_ref: An workload_vm object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in workload_vm_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'workload_vm_id': workload_vm_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _workload_vms_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _workload_vms_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _workload_vms_metadata_delete(context, metadata_ref, session=session)

@require_context
def _workload_vms_metadata_create(context, values, session):
    """Create an WorkloadMetadata object"""
    metadata_ref = models.WorkloadVMMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _workload_vms_metadata_update(context, metadata_ref, values, session)

@require_context
def workload_vms_metadata_create(context, values, session):
    """Create an WorkloadMetadata object"""
    session = get_session()
    return _workload_vms_metadata_create(context, values, session)

@require_context
def _workload_vms_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by workload_vms_metadata_create and workload_vms_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _workload_vms_metadata_delete(context, metadata_ref, session):
    """
    Used internally by workload_vms_metadata_create and workload_vms_metadata_update
    """
    metadata_ref.delete(session=session)
    return metadata_ref

def _workload_vms_update(context, values, id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if id:
        workload_vm_ref = _workload_vm_get(context, id, session)
    else:
        workload_vm_ref = models.WorkloadVMs()
        if not values.get('id'):
            values['id'] = str(uuid.uuid4())        
    
    workload_vm_ref.update(values)
    workload_vm_ref.save(session)
    
    if metadata:
        _set_metadata_for_workload_vms(context, workload_vm_ref, metadata, purge_metadata, session=session)  
      
    return workload_vm_ref


@require_context
def workload_vms_create(context, values):
    session = get_session()
    return _workload_vms_update(context, values, None, False, session)

@require_context
def workload_vms_update(context, id, values, purge_metadata=False):
    session = get_session()
    return _workload_vms_update(context, values, id, purge_metadata, session)

@require_context
def workload_vms_get(context, workload_id, **kwargs):
    session = kwargs.get('session') or get_session()
    try:
        query = model_query(context, models.WorkloadVMs,
                            session=session, read_deleted="no")\
                       .options(sa_orm.joinedload(models.WorkloadVMs.metadata))\
                       .filter_by(workload_id=workload_id)\
                       .filter(models.WorkloadVMs.status != None)\

        #TODO(gbasava): filter out deleted workload_vms if context disallows it
        workload_vms = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadVMsNotFound(workload_id = workload_id)
    
    return workload_vms

@require_context
def workload_vm_get_by_id(context, vm_id, **kwargs):
    session = kwargs.get('session') or get_session()
    try:
        query = model_query(context, models.WorkloadVMs,
                            session=session, read_deleted="no")\
                     .options(sa_orm.joinedload(models.WorkloadVMs.metadata))\
                     .join(models.Workloads)\
                     .filter(models.WorkloadVMs.status != None)\
                     .filter(models.WorkloadVMs.vm_id==vm_id)\
                     .filter(models.Workloads.project_id == context.project_id)\

        vm_found = query.all()

    except sa_orm.exc.NoResultFound:
           raise exception.WorkloadVMsNotFound(vm_id = vm_id)

    return vm_found

@require_context
def _workload_vm_get(context, id, session):
    try:
        query = session.query(models.WorkloadVMs)\
                       .options(sa_orm.joinedload(models.WorkloadVMs.metadata))\
                       .filter_by(id=id)\

        #TODO(gbasava): filter out deleted workload_vms if context disallows it
        workload_vm = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.WorkloadVMNotFound(workload_vm_id = id)

    return workload_vm

@require_context
def workload_vm_get(context, id):
    session = get_session() 
    return _workload_vm_get(context, id, session)   
    
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
######################################################################################################
@require_admin_context
def snapshot_mark_incomplete_as_error(context, host):
    """
    mark the snapshots that are left hanging from previous run on host as 'error'
    """
    session = get_session()
    now = timeutils.utcnow()  
    snapshots =  model_query(context, models.Snapshots, session=session).\
                            filter_by(host=host).all()
    for snapshot in snapshots:
        if snapshot.status != 'available' and snapshot.status != 'error' and \
           snapshot.status != 'restoring' and snapshot.status != 'mounted' and \
           snapshot.status != 'cancelled':
            values =  {'progress_percent': 100, 'progress_msg': '',
                       'error_msg': 'Snapshot did not finish successfully',
                       'status': 'error' }
            snapshot.update(values)
            snapshot.save(session=session)

        if snapshot.status == 'restoring':
            values =  { 'status': 'available' }
            snapshot.save(session=session)

        workload_update(context, snapshot.workload_id, {'status':'available'})
           
    snapshots =  model_query(context, models.Snapshots, session=session).\
                            all()
    for snapshot in snapshots:
        if snapshot.status != 'available' and snapshot.status != 'error' and\
           snapshot.status != 'restoring' and snapshot.status != 'mounted' and \
           snapshot.status != 'cancelled':
            if (snapshot.host is not None) and snapshot.host == '' and now - snapshot.created_at > timedelta(minutes=60):
                values =  {'progress_percent': 100, 'progress_msg': '',
                           'error_msg': 'Snapshot did not finish successfully',
                           'status': 'error' }
                snapshot.update(values)
                snapshot.save(session=session)
        if snapshot.status == 'restoring':
            values =  { 'status': 'available' }
            snapshot.save(session=session)

#### Snapshot ################################################################
""" snapshot functions """
def _set_metadata_for_snapshot(context, snapshot_ref, metadata,
                                    purge_metadata, session):
    """
    Create or update a set of snapshot_metadata for a given snapshot

    :param context: Request context
    :param snapshot_ref: A snapshot object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in snapshot_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'snapshot_id': snapshot_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _snapshot_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _snapshot_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _snapshot_metadata_delete(context, metadata_ref, session=session)

@require_context
def _snapshot_metadata_create(context, values, session):
    """Create a SnapshotMetadata object"""
    metadata_ref = models.SnapshotMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _snapshot_metadata_update(context, metadata_ref, values, session)

@require_context
def snapshot_metadata_create(context, values, session):
    """Create an SnapshotMetadata object"""
    session = get_session()
    return _snapshot_metadata_create(context, values, session)

@require_context
def _snapshot_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by snapshot_metadata_create and snapshot_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _snapshot_metadata_delete(context, metadata_ref, session):
    """
    Used internally by snapshot_metadata_create and snapshot_metadata_update
    """
    metadata_ref.delete(session=session)

def _snapshot_update(context, values, snapshot_id, purge_metadata, session):
    try:
        lock.acquire()    
        metadata = values.pop('metadata', {})
        
        if snapshot_id:
            snapshot_ref = model_query(context, models.Snapshots, session=session, read_deleted="yes").\
                                        filter_by(id=snapshot_id).first()
            if not snapshot_ref:
                lock.release()
                raise exception.SnapshotNotFound(snapshot_id = snapshot_id)
                                                        
            if not values.get('uploaded_size'):
                if values.get('uploaded_size_incremental'):
                    values['uploaded_size'] =  snapshot_ref.uploaded_size + values.get('uploaded_size_incremental') 
                    if not values.get('progress_percent') and snapshot_ref.size > 0:
                        values['progress_percent'] = min( 99, (100 * values.get('uploaded_size'))/snapshot_ref.size )
        else:
            snapshot_ref = models.Snapshots()
            if not values.get('id'):
                values['id'] = str(uuid.uuid4())
            if not values.get('size'):
                values['size'] = 0
            if not values.get('restore_size'):
                values['restore_size'] = 0                
            if not values.get('uploaded_size'):
                values['uploaded_size'] = 0
            if not values.get('progress_percent'):
                values['progress_percent'] = 0 
        snapshot_ref.update(values)
        snapshot_ref.save(session)
        
        if metadata:
            _set_metadata_for_snapshot(context, snapshot_ref, metadata, purge_metadata, session=session)  
          
        return snapshot_ref
    finally:
        lock.release()
    return snapshot_ref               
        
@require_context
def _snapshot_get(context, snapshot_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    result = model_query(   context, models.Snapshots, **kwargs).\
                            options(sa_orm.joinedload(models.Snapshots.metadata)).\
                            filter_by(id=snapshot_id).\
                            first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result

@require_context
def snapshot_get(context, snapshot_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()    
    return _snapshot_get(context, snapshot_id, **kwargs) 

@require_context
def snapshot_get_metadata_cancel_flag(context, snapshot_id, return_val=0, process=None, **kwargs):
    flag='0'
    snapshot_obj = snapshot_get(context, snapshot_id)
    for meta in snapshot_obj.metadata:
        if meta.key == 'cancel_requested':
            flag = meta.value

    if return_val == 1:
        return flag

    if flag == '1':
        if process:
            process.kill()
        error = _('Cancel requested for snapshot')
        raise exception.ErrorOccurred(reason=error)

@require_context
def snapshot_get_running_snapshots_by_host(context, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()

    result = model_query(   context, models.Snapshots.host, func.count(models.Snapshots.host), **kwargs).\
                            filter(and_(~models.Snapshots.status.in_(['available','error','deleted','cancelled'])),models.Snapshots.host != '').\
                            group_by(models.Snapshots.host).\
                            all() 
    return result

@require_context
def snapshot_get_all(context, **kwargs):
    qs = model_query(context, models.Snapshots, **kwargs).\
                    options(sa_orm.joinedload(models.Snapshots.metadata))
    if 'workload_id' in kwargs and kwargs['workload_id'] is not None and kwargs['workload_id'] != '':  
       qs = qs.filter_by(workload_id=kwargs['workload_id'])
    if 'host' in kwargs and kwargs['host'] is not None and kwargs['host'] != '':
       qs = qs.filter(models.Snapshots.host == kwargs['host'])
    if 'date_from' in kwargs and kwargs['date_from'] is not None and kwargs['date_from'] != '':
       if 'date_to' in kwargs and kwargs['date_to'] is not None and kwargs['date_to'] != '':
           date_to = kwargs['date_to']
       else:
            date_to = datetime.now()
       qs = qs.filter(and_(models.Snapshots.created_at >= func.date_format(kwargs['date_from'],'%y-%m-%dT%H:%i:%s'),\
                      models.Snapshots.created_at <= func.date_format(date_to,'%y-%m-%dT%H:%i:%s')))

    if not is_admin_context(context):
       qs = qs.filter_by(project_id=context.project_id)
    else:
         if 'get_all' in kwargs and kwargs['get_all'] is not True:
            qs = qs.filter_by(project_id=context.project_id)
    return qs.order_by(models.Snapshots.created_at.desc()).all() 

@require_context                            
def snapshot_get_all_by_workload(context, workload_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()

    return model_query(context, models.Snapshots, **kwargs).\
                        options(sa_orm.joinedload(models.Snapshots.metadata)).\
                        filter_by(workload_id=workload_id).\
                        order_by(models.Snapshots.created_at.desc()).all()
@require_context
def snapshot_get_all_by_project(context, project_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    authorize_project_context(context, project_id)
    return model_query(context, models.Snapshots, **kwargs).\
                            options(sa_orm.joinedload(models.Snapshots.metadata)).\
                            filter_by(project_id=project_id).all()
        
@require_context
def snapshot_get_all_by_project_workload(context, project_id, workload_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    authorize_project_context(context, project_id)
    return model_query(context, models.Snapshots, **kwargs).\
                            options(sa_orm.joinedload(models.Snapshots.metadata)).\
                            filter_by(project_id=project_id).\
                            filter_by(workload_id=workload_id).\
                            order_by(models.Snapshots.created_at.desc()).all()

@require_context
def snapshot_show(context, snapshot_id, **kwargs):
    session = get_session()
    result = model_query(context, models.Snapshots, session=session, **kwargs).\
                            options(sa_orm.joinedload(models.Snapshots.metadata)).\
                            filter_by(id=snapshot_id).\
                            first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result

@require_context
def snapshot_create(context, values):
    session = get_session()
    return _snapshot_update(context, values, None, False, session)

@require_context
def snapshot_update(context, snapshot_id, values, purge_metadata=False):
    session = get_session()
    return _snapshot_update(context, values, snapshot_id, purge_metadata, session)

@require_context
def snapshot_type_time_size_update(context, snapshot_id):
    snapshot = snapshot_get(context, snapshot_id, read_deleted='yes')
    workload = workload_get(context, snapshot['workload_id'])

    backup_endpoint = get_metadata_value(workload.metadata,
                                         'backup_media_target')

    backup_target = vault.get_backup_target(backup_endpoint)

    snapshot_type_full = False
    snapshot_type_incremental = False
    snapshot_vm_resources = snapshot_resources_get(context, snapshot_id)
    time_taken = 0
    snapshot_size = 0
    snapshot_restore_size = 0
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        if snapshot_vm_resource.snapshot_type == 'full' and \
            snapshot_vm_resource.resource_name != 'vda':
            snapshot_type_full = True
        if snapshot_vm_resource.snapshot_type == 'incremental':
            snapshot_type_incremental = True
        time_taken = time_taken + snapshot_vm_resource.time_taken

        #update size
        if snapshot_vm_resource.status != 'deleted':
            disk_type = get_metadata_value(snapshot_vm_resource.metadata,'disk_type')
            vm_disk_resource_snaps = vm_disk_resource_snaps_get(context, snapshot_vm_resource.id)
            snapshot_vm_resource_size = 0
            for vm_disk_resource_snap in vm_disk_resource_snaps:
                vm_disk_resource_snap_restore_size = 0

                if vm_disk_resource_snap.vault_url is None:
                    continue

                resource_snap_path = os.path.join(backup_target.mount_path,
                                                  vm_disk_resource_snap.vault_url.strip(os.sep))
                vm_disk_resource_snap_size = backup_target.get_object_size(resource_snap_path)
                if vm_disk_resource_snap_size == 0:
                    vm_disk_resource_snap_size = vm_disk_resource_snap.size
                    
                disk_format = get_metadata_value(vm_disk_resource_snap.metadata,'disk_format')
                if disk_format == 'vmdk':
                    vault_path = os.path.join(backup_target.mount_path, 
                                              vm_disk_resource_snap.vault_url.strip(os.sep))
                    vm_disk_resource_snap_restore_size = vault.get_restore_size(vault_path,
                                                                                disk_format, disk_type)
                else:
                    vm_disk_resource_snap_restore_size = vm_disk_resource_snap_size
                    vm_disk_resource_snap_backing_id = vm_disk_resource_snap.vm_disk_resource_snap_backing_id
                    while vm_disk_resource_snap_backing_id:
                        vm_disk_resource_snap_backing = vm_disk_resource_snap_get(context, vm_disk_resource_snap_backing_id)
                        vm_disk_resource_snap_restore_size = vm_disk_resource_snap_restore_size + vm_disk_resource_snap_backing.size
                        vm_disk_resource_snap_backing_id = vm_disk_resource_snap_backing.vm_disk_resource_snap_backing_id

                #For vmdk   
                if vm_disk_resource_snap_restore_size == 0:
                    vm_disk_resource_snap_restore_size = vm_disk_resource_snap_size
                    vm_disk_resource_snap_backing_id = vm_disk_resource_snap.vm_disk_resource_snap_backing_id
                    while vm_disk_resource_snap_backing_id:
                        vm_disk_resource_snap_backing = vm_disk_resource_snap_get(context, vm_disk_resource_snap_backing_id)
                        if vm_disk_resource_snap_backing.vm_disk_resource_snap_backing_id:
                            vm_disk_resource_snap_restore_size = vm_disk_resource_snap_restore_size + vm_disk_resource_snap_backing.size
                        else:
                            vm_disk_resource_snap_restore_size = vm_disk_resource_snap_restore_size + vm_disk_resource_snap_backing.restore_size
                        vm_disk_resource_snap_backing_id = vm_disk_resource_snap_backing.vm_disk_resource_snap_backing_id
                                
                vm_disk_resource_snap_update(context, vm_disk_resource_snap.id, {'size' : vm_disk_resource_snap_size,
                                                                                 'restore_size' : vm_disk_resource_snap_restore_size}) 
                snapshot_vm_resource_size = snapshot_vm_resource_size + vm_disk_resource_snap_size
                    
            vm_disk_resource_snap_top = vm_disk_resource_snap_get_top(context, snapshot_vm_resource.id)
            snapshot_vm_resource_restore_size = vm_disk_resource_snap_top.restore_size
            snapshot_vm_resource_update(context, snapshot_vm_resource.id, {'size' : snapshot_vm_resource_size,
                                                                           'restore_size' : snapshot_vm_resource_restore_size})
            snapshot_size = snapshot_size + snapshot_vm_resource_size
            snapshot_restore_size = snapshot_restore_size + snapshot_vm_resource_restore_size


    snapshot_vms= snapshot_vms_get(context, snapshot_id)
    snapshot_data_transfer_time = 0
    snapshot_object_store_transfer_time = 0
    for snapshot_vm in snapshot_vms:
        snapshot_vm_size = 0
        snapshot_vm_restore_size = 0
        snapshot_vm_data_transfer_time = 0
        snapshot_vm_object_store_transfer_time = 0
        snapshot_vm_resources = snapshot_vm_resources_get(context, snapshot_vm.vm_id, snapshot_id)
        for snapshot_vm_resource in snapshot_vm_resources:
            if snapshot_vm_resource.resource_type != 'disk':
                continue
            snapshot_vm_size = snapshot_vm_size +  snapshot_vm_resource.size
            snapshot_vm_restore_size = snapshot_vm_restore_size + snapshot_vm_resource.restore_size
            snapshot_vm_data_transfer_time += snapshot_vm_resource.time_taken
            snapshot_vm_object_store_transfer_time +=  int(get_metadata_value(snapshot_vm_resource.metadata,  'object_store_transfer_time', '0'))
        snapshot_vm_update(context, snapshot_vm.vm_id, snapshot_id, {'size' : snapshot_vm_size, 
                                                                     'restore_size' : snapshot_vm_restore_size,
                                                                     'metadata' : {'data_transfer_time' : snapshot_vm_data_transfer_time,
                                                                                   'object_store_transfer_time' : snapshot_vm_object_store_transfer_time,
                                                                                   },
                                                                     })
        snapshot_data_transfer_time += snapshot_vm_data_transfer_time        
        snapshot_object_store_transfer_time += snapshot_vm_object_store_transfer_time

    if snapshot.finished_at:
        time_taken = max(time_taken, int((snapshot.finished_at - snapshot.created_at).total_seconds()))
    else:
        time_taken = max(time_taken, int((timeutils.utcnow() - snapshot.created_at).total_seconds()))

    if snapshot_type_full and snapshot_type_incremental:
        snapshot_type = 'mixed'
    elif snapshot_type_incremental:
        snapshot_type = 'incremental'                
    elif snapshot_type_full:
        snapshot_type = 'full'
    else:
        snapshot_type = 'full'
                          
    return snapshot_update(context, snapshot_id, {'snapshot_type' : snapshot_type, 
                                                  'time_taken' : time_taken,
                                                  'size' : snapshot_size,
                                                  'restore_size' : snapshot_restore_size,
                                                  'uploaded_size' : snapshot_size,
                                                  'metadata' : {'data_transfer_time' : snapshot_data_transfer_time,
                                                                'object_store_transfer_time' : snapshot_object_store_transfer_time,
                                                                },                                                  
                                                  })
    
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
def get_snapshot_children(context, snapshot_id, children):
    grand_children = set()
    snapshot_vm_resources = snapshot_resources_get(context, snapshot_id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        vm_disk_resource_snaps = vm_disk_resource_snaps_get(context, snapshot_vm_resource.id)
        for vm_disk_resource_snap in vm_disk_resource_snaps:
            if vm_disk_resource_snap.vm_disk_resource_snap_child_id:
                try:
                    vm_disk_resource_snap_child = vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_child_id)
                    snapshot_vm_resource_child = snapshot_vm_resource_get(context,vm_disk_resource_snap_child.snapshot_vm_resource_id)
                    if snapshot_vm_resource_child.snapshot_id not in grand_children:
                        grand_children.add(snapshot_vm_resource_child.snapshot_id)
                        if snapshot_vm_resource_child.snapshot_id != snapshot_id:
                            grand_children = get_snapshot_children(context, snapshot_vm_resource_child.snapshot_id, grand_children)
                except Exception as ex:
                    LOG.exception(ex)
    if children:
        return grand_children.union(children)
    else:
        return grand_children

@require_context            
def get_snapshot_parents(context, snapshot_id, parents):
    grand_parents = set()
    snapshot_vm_resources = snapshot_resources_get(context, snapshot_id)
    for snapshot_vm_resource in snapshot_vm_resources:
        if snapshot_vm_resource.resource_type != 'disk':
            continue
        vm_disk_resource_snaps = vm_disk_resource_snaps_get(context, snapshot_vm_resource.id)
        for vm_disk_resource_snap in vm_disk_resource_snaps:
            if vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
                try:
                    vm_disk_resource_snap_parent = vm_disk_resource_snap_get(context, vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
                    snapshot_vm_resource_parent = snapshot_vm_resource_get(context, vm_disk_resource_snap_parent.snapshot_vm_resource_id)
                    if snapshot_vm_resource_parent.snapshot_id not in grand_parents:
                        grand_parents.add(snapshot_vm_resource_parent.snapshot_id)
                        if snapshot_vm_resource_parent.snapshot_id != snapshot_id:
                            grand_parents = get_snapshot_parents(context, snapshot_vm_resource_parent.snapshot_id, grand_parents)
                except Exception as ex:
                    LOG.exception(ex)
    if parents:
        return grand_parents.union(parents)
    else:
        return grand_parents    

#### SnapshotVMs ################################################################
""" snapshot_vms functions """
def _set_metadata_for_snapshot_vms(context, snapshot_vm_ref, metadata,
                                    purge_metadata, session):
    """
    Create or update a set of snapshot_vms_metadata for a given snapshot_vm

    :param context: Request context
    :param snapshot_vm_ref: An snapshot_vm object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in snapshot_vm_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'snapshot_vm_id': snapshot_vm_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _snapshot_vms_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _snapshot_vms_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _snapshot_vms_metadata_delete(context, metadata_ref, session=session)

@require_context
def _snapshot_vms_metadata_create(context, values, session):
    """Create an SnapshotMetadata object"""
    metadata_ref = models.SnapshotVMMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _snapshot_vms_metadata_update(context, metadata_ref, values, session)

@require_context
def snapshot_vms_metadata_create(context, values, session):
    """Create an SnapshotMetadata object"""
    session = get_session()
    return _snapshot_vms_metadata_create(context, values, session)

@require_context
def _snapshot_vms_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by snapshot_vms_metadata_create and snapshot_vms_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _snapshot_vms_metadata_delete(context, metadata_ref, session):
    """
    Used internally by snapshot_vms_metadata_create and snapshot_vms_metadata_update
    """
    metadata_ref.delete(session=session)

def _snapshot_vm_update(context, values, vm_id, snapshot_id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if vm_id:
        snapshot_vm_ref = _snapshot_vm_get(context, vm_id, snapshot_id, session)
        if snapshot_vm_ref is None:
            return
    else:
        snapshot_vm_ref = models.SnapshotVMs()
        if not values.get('id'):
            values['id'] = str(uuid.uuid4())
        if not values.get('size'):
            values['size'] = 0
        if not values.get('restore_size'):
            values['restore_size'] = 0   

    snapshot_vm_ref.update(values)
    snapshot_vm_ref.save(session)
    
    if metadata:
        _set_metadata_for_snapshot_vms(context, snapshot_vm_ref, metadata, purge_metadata, session=session)  
      
    return snapshot_vm_ref


@require_context
def snapshot_vm_create(context, values):
    session = get_session()
    return _snapshot_vm_update(context, values, None, None, False, session)

@require_context
def snapshot_vm_update(context, vm_id, snapshot_id, values, purge_metadata=False):
    session = get_session()
    return _snapshot_vm_update(context, values, vm_id, snapshot_id, purge_metadata, session)

@require_context
def snapshot_vms_get(context, snapshot_id, **kwargs):
    session = kwargs.get('session') or get_session()
    try:
        query = session.query(models.SnapshotVMs)\
                       .options(sa_orm.joinedload(models.SnapshotVMs.metadata))\
                       .filter_by(snapshot_id=snapshot_id)\

        snapshot_vms = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotVMsNotFound(snapshot_id=snapshot_id)
    
    return snapshot_vms    
   
@require_context
def _snapshot_vm_get(context, vm_id, snapshot_id, session):
    try:
        query = session.query(models.SnapshotVMs)\
                       .options(sa_orm.joinedload(models.SnapshotVMs.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(snapshot_id=snapshot_id)

        #TODO(gbasava): filter out deleted snapshot_vm if context disallows it
        snapshot_vm = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotVMsNotFound(snapshot_id=snapshot_id)

    return snapshot_vm

@require_context
def snapshot_vm_get(context, vm_id, snapshot_id):
    session = get_session() 
    return _snapshot_vm_get(context, vm_id, snapshot_id, session)   
    
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
#################################################################################################################
            
@require_context
def vm_recent_snapshot_create(context, values):
    vm_recent_snapshot = models.VMRecentSnapshot()
    vm_recent_snapshot.update(values)
    vm_recent_snapshot.save()
    return vm_recent_snapshot

@require_context
def vm_recent_snapshot_get(context, vm_id, **kwargs):
    session = kwargs.get('session') or get_session()
    result = model_query(context, models.VMRecentSnapshot, session=session).\
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
@require_context
def _set_metadata_for_snapshot_vm_resource(context, snapshot_vm_resource_ref, metadata,
                                           purge_metadata, session):
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
            _snapshot_vm_resource_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _snapshot_vm_resource_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _snapshot_vm_resource_metadata_delete(context, metadata_ref, session)

@require_context
def _snapshot_vm_resource_metadata_create(context, values, session):
    """Create an SnapshotVMResourceMetadata object"""
    metadata_ref = models.SnapshotVMResourceMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _snapshot_vm_resource_metadata_update(context, metadata_ref, values, session)

@require_context
def snapshot_vm_resource_metadata_create(context, values):
    session = get_session()
    return _snapshot_vm_resource_metadata_create(context, values, session)

@require_context
def _snapshot_vm_resource_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by snapshot_vm_resource_metadata_create and snapshot_vm_resource_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _snapshot_vm_resource_metadata_delete(context, metadata_ref, session):
    """
    Used internally by snapshot_vm_resource_metadata_create and snapshot_vm_resource_metadata_update
    """
    metadata_ref.delete(session=session)

@require_context
def _snapshot_vm_resource_update(context, values, snapshot_vm_resource_id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if snapshot_vm_resource_id:
        snapshot_vm_resource_ref = _snapshot_vm_resource_get(context, snapshot_vm_resource_id, session=session)
    else:
        snapshot_vm_resource_ref = models.SnapshotVMResources()
        if not values.get('size'):
            values['size'] = 0        
        if not values.get('restore_size'):
            values['restore_size'] = 0   
                
    snapshot_vm_resource_ref.update(values)
    snapshot_vm_resource_ref.save(session)
    
    _set_metadata_for_snapshot_vm_resource(context, snapshot_vm_resource_ref, metadata, purge_metadata, session)  
      
    return snapshot_vm_resource_ref


@require_context
def snapshot_vm_resource_create(context, values):
    session = get_session()
    return _snapshot_vm_resource_update(context, values, None, False, session)

@require_context
def snapshot_vm_resource_update(context, snapshot_vm_resource_id, values, purge_metadata=False):
    session = get_session()
    return _snapshot_vm_resource_update(context, values, snapshot_vm_resource_id, purge_metadata, session)

@require_context
def snapshot_vm_resources_get(context, vm_id, snapshot_id):
    session = get_session()
    try:
        query = session.query(models.SnapshotVMResources)\
                       .options(sa_orm.joinedload(models.SnapshotVMResources.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(snapshot_id=snapshot_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        snapshot_vm_resources = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotVMResourcesNotFound(snapshot_vm_id = vm_id, snapshot_id = snapshot_id)
    
    return snapshot_vm_resources

@require_context
def snapshot_resources_get(context, snapshot_id, **kwargs):
    session = kwargs.get('session') or get_session()
    try:
        query = session.query(models.SnapshotVMResources)\
                       .options(sa_orm.joinedload(models.SnapshotVMResources.metadata))\
                       .filter_by(snapshot_id=snapshot_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        snapshot_resources = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotResourcesNotFound(snapshot_id = snapshot_id)
    
    return snapshot_resources

@require_context
def snapshot_vm_resource_get_by_resource_name(context, vm_id, snapshot_id, resource_name):
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
        raise exception.SnapshotVMResourceWithNameNotFound(resource_name = resource_name, 
                                                           snapshot_vm_id = vm_id, 
                                                           snapshot_id = snapshot_id)

    return snapshot_vm_resource

@require_context
def snapshot_vm_resource_get_by_resource_pit_id(context, vm_id, snapshot_id, resource_pit_id):
    session = get_session()
    try:
        query = session.query(models.SnapshotVMResources)\
                       .options(sa_orm.joinedload(models.SnapshotVMResources.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(snapshot_id=snapshot_id)\
                       .filter_by(resource_pit_id=resource_pit_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        snapshot_vm_resource = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotVMResourceWithNameNotFound(resource_pit_id = resource_pit_id, 
                                                           snapshot_vm_id = vm_id, 
                                                           snapshot_id = snapshot_id)

    return snapshot_vm_resource

@require_context
def _snapshot_vm_resource_get(context, id, session):
    try:
        query = session.query(models.SnapshotVMResources)\
                       .options(sa_orm.joinedload(models.SnapshotVMResources.metadata))\
                       .filter_by(id=id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        snapshot_vm_resource = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.SnapshotVMResourceNotFound(snapshot_vm_resource_id = id)

    return snapshot_vm_resource

@require_context
def snapshot_vm_resource_get(context, id):
    session = get_session()
    return _snapshot_vm_resource_get(context, id, session)

@require_context
def snapshot_vm_resource_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.SnapshotVMResources).\
            filter_by(id=id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

""" disk resource snapshot functions """
def _set_metadata_for_vm_disk_resource_snap(context, vm_disk_resource_snap_ref, metadata,
                                            purge_metadata, session):
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
            _vm_disk_resource_snap_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _vm_disk_resource_snap_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _vm_disk_resource_snap_metadata_delete(context, metadata_ref, session)

@require_context
def _vm_disk_resource_snap_metadata_create(context, values, session):
    """Create an VMDiskResourceSnapMetadata object"""
    metadata_ref = models.VMDiskResourceSnapMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _vm_disk_resource_snap_metadata_update(context, metadata_ref, values, session)

@require_context
def vm_disk_resource_snap_metadata_create(context, values):
    """Create an VMDiskResourceSnapMetadata object"""
    session = get_session()
    return _vm_disk_resource_snap_metadata_create(context, values, session)


def _vm_disk_resource_snap_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by vm_disk_resource_snap_metadata_create and vm_disk_resource_snap_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref


def _vm_disk_resource_snap_metadata_delete(context, metadata_ref, session):
    """
    Used internally by vm_disk_resource_snap_metadata_create and vm_disk_resource_snap_metadata_update
    """
    metadata_ref.delete(session=session)

def _vm_disk_resource_snap_update(context, values, vm_disk_resource_snap_id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})

    if vm_disk_resource_snap_id:
        vm_disk_resource_snap_ref = _vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session)
    else:
        vm_disk_resource_snap_ref = models.VMDiskResourceSnaps()
        if not values.get('size'):
            values['size'] = 0
        if not values.get('restore_size'):
            values['restore_size'] = 0   
            
    vm_disk_resource_snap_ref.update(values)
    vm_disk_resource_snap_ref.save(session)
    
    _set_metadata_for_vm_disk_resource_snap(context, vm_disk_resource_snap_ref, metadata, purge_metadata, session)  
      
    return vm_disk_resource_snap_ref


@require_context
def vm_disk_resource_snap_create(context, values):
    session = get_session()
    return _vm_disk_resource_snap_update(context, values, None, False, session)

@require_context
def vm_disk_resource_snap_update(context, vm_disk_resource_snap_id, values, purge_metadata=False):
    session = get_session()
    return _vm_disk_resource_snap_update(context, values, vm_disk_resource_snap_id, purge_metadata, session)

@require_context
def vm_disk_resource_snaps_get(context, snapshot_vm_resource_id, **kwargs):
    session = kwargs.get('session') or get_session()
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
def vm_disk_resource_snap_get_top(context, snapshot_vm_resource_id):
    session = get_session()
    try:
        query = session.query(models.VMDiskResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMDiskResourceSnaps.metadata))\
                       .filter_by(snapshot_vm_resource_id = snapshot_vm_resource_id)\
                       .filter_by(top= True)

        #TODO(gbasava): filter out resource snapshots if context disallows it
        vm_disk_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapTopNotFound(snapshot_vm_resource_id = snapshot_vm_resource_id)
    
    return vm_disk_resource_snap

@require_context
def vm_disk_resource_snap_get_bottom(context, snapshot_vm_resource_id):
    vm_disk_resource_snap = db.vm_disk_resource_snap_get_top(context, snapshot_vm_resource_id)
    while vm_disk_resource_snap and vm_disk_resource_snap.vm_disk_resource_snap_backing_id:
        vm_disk_resource_snap_backing = db.vm_disk_resource_snap_get(context,vm_disk_resource_snap.vm_disk_resource_snap_backing_id)
        if vm_disk_resource_snap_backing.snapshot_vm_resource_id == vm_disk_resource_snap.snapshot_vm_resource_id:
            vm_disk_resource_snap = vm_disk_resource_snap_backing
        else:
            break
    return vm_disk_resource_snap

@require_context
def _vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session):
    try:
        query = session.query(models.VMDiskResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMDiskResourceSnaps.metadata))\
                       .filter_by(id=vm_disk_resource_snap_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_disk_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMDiskResourceSnapNotFound(vm_disk_resource_snap_id = vm_disk_resource_snap_id)
    
    return vm_disk_resource_snap

@require_context
def vm_disk_resource_snap_get(context, vm_disk_resource_snap_id):
    session = get_session()
    return _vm_disk_resource_snap_get(context, vm_disk_resource_snap_id, session)

@require_context
def vm_disk_resource_snap_get_snapshot_vm_resource_id(context, vm_disk_resource_snap_id):
    vm_disk_resource_snap = vm_disk_resource_snap_get(context, vm_disk_resource_snap_id)
    return vm_disk_resource_snap.snapshot_vm_resource_id

@require_context
def vm_disk_resource_snap_delete(context, vm_disk_resource_snap_id):
    session = get_session()
    with session.begin():
        session.query(models.VMDiskResourceSnaps).\
            filter_by(id=vm_disk_resource_snap_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
            
""" network resource snapshot functions """
def _set_metadata_for_vm_network_resource_snap(context, vm_network_resource_snap_ref, metadata,
                                               purge_metadata, session):
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
            _vm_network_resource_snap_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _vm_network_resource_snap_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _vm_network_resource_snap_metadata_delete(context, metadata_ref, session)

@require_context
def _vm_network_resource_snap_metadata_create(context, values, session):
    """Create an VMNetworkResourceSnapMetadata object"""
    metadata_ref = models.VMNetworkResourceSnapMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _vm_network_resource_snap_metadata_update(context, metadata_ref, values, session)

@require_context
def vm_network_resource_snap_metadata_create(context, values):
    """Create an VMNetworkResourceSnapMetadata object"""
    session = get_session()
    return _vm_network_resource_snap_metadata_create(context, values, session)

def _vm_network_resource_snap_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by vm_network_resource_snap_metadata_create and vm_network_resource_snap_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _vm_network_resource_snap_metadata_delete(context, metadata_ref, session):
    """
    Used internally by vm_network_resource_snap_metadata_create and vm_network_resource_snap_metadata_update
    """
    metadata_ref.delete(session=session)
    return metadata_ref

def _vm_network_resource_snap_update(context, vm_network_resource_snap_id, values, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if vm_network_resource_snap_id:
        vm_network_resource_snap_ref = vm_network_resource_snap_get(context, vm_network_resource_snap_id, session)
    else:
        vm_network_resource_snap_ref = models.VMNetworkResourceSnaps()
    
    vm_network_resource_snap_ref.update(values)
    vm_network_resource_snap_ref.save(session)
    
    _set_metadata_for_vm_network_resource_snap(context, vm_network_resource_snap_ref, metadata, purge_metadata, session=session)  
      
    return vm_network_resource_snap_ref


@require_context
def vm_network_resource_snap_create(context, values):
    session = get_session()
    return _vm_network_resource_snap_update(context, None, values, False, session)

@require_context
def vm_network_resource_snap_update(context, vm_network_resource_snap_id, values, purge_metadata = False):
    session = get_session()
    return _vm_network_resource_snap_update(context, values, vm_network_resource_snap_id, purge_metadata, session)

@require_context
def vm_network_resource_snaps_get(context, snapshot_vm_resource_id, **kwargs):
    session = kwargs.get('session') or get_session()
    try:
        query = session.query(models.VMNetworkResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMNetworkResourceSnaps.metadata))\
                       .filter_by(vm_network_resource_snap_id=snapshot_vm_resource_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        vm_network_resource_snaps = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.VMNetworkResourceSnapsNotFound(snapshot_vm_resource_id = snapshot_vm_resource_id)
    
    return vm_network_resource_snaps

@require_context
def vm_network_resource_snap_get(context, vm_network_resource_snap_id):
    session = get_session()
    try:
        query = session.query(models.VMNetworkResourceSnaps)\
                       .options(sa_orm.joinedload(models.VMNetworkResourceSnaps.metadata))\
                       .filter_by(vm_network_resource_snap_id=vm_network_resource_snap_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_network_resource_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMNetworkResourceSnapNotFound(vm_network_resource_snap_id = vm_network_resource_snap_id)
    
    return vm_network_resource_snap


@require_context
def vm_network_resource_snap_delete(context, vm_network_resource_snap_id):
    session = get_session()
    with session.begin():
        session.query(models.VMNetworkResourceSnaps).\
            filter_by(id=vm_network_resource_snap_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

""" security group rule snapshot functions """
def _set_metadata_for_vm_security_group_rule_snap(context, vm_security_group_rule_snap_ref, metadata,
                                                  purge_metadata, session):
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
            _vm_security_group_rule_snap_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _vm_security_group_rule_snap_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _vm_security_group_rule_snap_metadata_delete(context, metadata_ref, session)

@require_context
def _vm_security_group_rule_snap_metadata_create(context, values, session):
    """Create an VMSecurityGroupRuleSnapMetadata object"""
    metadata_ref = models.VMSecurityGroupRuleSnapMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _vm_security_group_rule_snap_metadata_update(context, metadata_ref, values, session)

@require_context
def vm_security_group_rule_snap_metadata_create(context, values):
    """Create an VMSecurityGroupRuleSnapMetadata object"""
    session = get_session() 
    return _vm_security_group_rule_snap_metadata_create(context, values, session)

def _vm_security_group_rule_snap_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by vm_security_group_rule_snap_metadata_create and vm_security_group_rule_snap_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _vm_security_group_rule_snap_metadata_delete(context, metadata_ref, session):
    """
    Used internally by vm_security_group_rule_snap_metadata_create and vm_security_group_rule_snap_metadata_update
    """
    metadata_ref.delete(session=session)

def _vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, values, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if id and vm_security_group_snap_id:
        vm_security_group_rule_snap_ref = vm_security_group_rule_snap_get(context, id, vm_security_group_snap_id, session)
    else:
        vm_security_group_rule_snap_ref = models.VMSecurityGroupRuleSnaps()
    
    vm_security_group_rule_snap_ref.update(values)
    vm_security_group_rule_snap_ref.save(session)
    
    _set_metadata_for_vm_security_group_rule_snap(context, vm_security_group_rule_snap_ref, metadata, purge_metadata, session)  
      
    return vm_security_group_rule_snap_ref

@require_context
def vm_security_group_rule_snap_create(context, values):
    session = get_session()
    return _vm_security_group_rule_snap_update(context, None, None, values, False, session)

@require_context
def vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, values, purge_metadata=False):
    session = get_session()
    return _vm_security_group_rule_snap_update(context, id, vm_security_group_snap_id, values, purge_metadata, session)

@require_context
def vm_security_group_rule_snaps_get(context, vm_security_group_snap_id, **kwargs):
    session = kwargs.get('session') or get_session()
    try:
        query = session.query(models.VMSecurityGroupRuleSnaps)\
                       .options(sa_orm.joinedload(models.VMSecurityGroupRuleSnaps.metadata))\
                       .filter_by(vm_security_group_snap_id=vm_security_group_snap_id)

        #TODO(gbasava): filter out deleted snapshots if context disallows it
        vm_security_group_rule_snaps = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.VMSecurityGroupRuleSnapsNotFound(vm_security_group_snap_id = vm_security_group_snap_id)
    
    return vm_security_group_rule_snaps

@require_context
def vm_security_group_rule_snap_get(context, id, vm_security_group_snap_id):
    session = get_session()
    try:
        query = session.query(models.VMSecurityGroupRuleSnaps)\
                       .options(sa_orm.joinedload(models.VMSecurityGroupRuleSnaps.metadata))\
                       .filter_by(id=id)\
                       .filter_by(vm_security_group_snap_id=vm_security_group_snap_id)

        #TODO(gbasava): filter out deleted resource snapshots if context disallows it
        vm_security_group_rule_snap = query.one()

    except sa_orm.exc.NoResultFound:
        raise exception.VMSecurityGroupRuleSnapNotFound(vm_security_group_rule_snap_id = id, vm_security_group_snap_id = vm_security_group_snap_id)
    
    return vm_security_group_rule_snap

@require_context
def vm_security_group_rule_snap_delete(context, id, vm_security_group_rule_snap_id):
    session = get_session()
    with session.begin():
        session.query(models.VMSecurityGroupRuleSnaps).\
            filter_by(id=id).\
            filter_by(id=vm_security_group_rule_snap_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
            
def get_metadata_value(metadata, key, default=None):
    for kvpair in metadata:
        if kvpair['key'] == key:
            return kvpair['value']
    return default

#### Restore ################################################################
""" restore functions """
@require_admin_context
def restore_mark_incomplete_as_error(context, host):
    """
    mark the restores that are left hanging from previous run on host as 'error'
    """
    session = get_session()
    restores =  model_query(context, models.Restores, session=session).\
                            filter_by(host=host).all()
    for restore in restores:
        if restore.status != 'available' and restore.status != 'error' and\
           restore.status != 'cancelled':
            values =  {'progress_percent': 100, 'progress_msg': '',
                       'error_msg': 'Restore did not finish successfully',
                       'status': 'error' }
            restore.update(values)
            restore.save(session=session)
            return snapshot_update(context, restore.snapshot_id, {'status': 'available' })            
            
def _set_metadata_for_restore(context, restore_ref, metadata,
                                    purge_metadata, session):
    """
    Create or update a set of restore_metadata for a given restore

    :param context: Request context
    :param restore_ref: A restore object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in restore_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'restore_id': restore_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _restore_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _restore_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _restore_metadata_delete(context, metadata_ref, session=session)

@require_context
def _restore_metadata_create(context, values, session):
    """Create a RestoreMetadata object"""
    metadata_ref = models.RestoreMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _restore_metadata_update(context, metadata_ref, values, session)

@require_context
def restore_metadata_create(context, values, session):
    """Create an RestoreMetadata object"""
    session = get_session()
    return _restore_metadata_create(context, values, session)

@require_context
def _restore_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by restore_metadata_create and restore_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _restore_metadata_delete(context, metadata_ref, session):
    """
    Used internally by restore_metadata_create and restore_metadata_update
    """
    metadata_ref.delete(session=session)

def _restore_update(context, values, restore_id, purge_metadata, session):
    try:
        lock.acquire()    
        metadata = values.pop('metadata', {})
        
        if restore_id:
            restore_ref = model_query(context, models.Restores, session=session, read_deleted="yes").\
                                        filter_by(id=restore_id).first()
            if not restore_ref:
                lock.release()
                raise exception.RestoreNotFound(restore_id = restore_id)
                                                        
            if not values.get('uploaded_size'):
                if values.get('uploaded_size_incremental'):
                    values['uploaded_size'] =  restore_ref.uploaded_size + values.get('uploaded_size_incremental') 
                    if not values.get('progress_percent') and restore_ref.size > 0:
                        values['progress_percent'] = min( 99, (100 * values.get('uploaded_size'))/restore_ref.size )
        else:
            restore_ref = models.Restores()
            if not values.get('id'):
                values['id'] = str(uuid.uuid4())
            if not values.get('size'):
                values['size'] = 0
            if not values.get('uploaded_size'):
                values['uploaded_size'] = 0
            if not values.get('progress_percent'):
                values['progress_percent'] = 0 
                
        restore_ref.update(values)
        restore_ref.save(session)
        
        if metadata:
            _set_metadata_for_restore(context, restore_ref, metadata, purge_metadata, session=session)  
          
        return restore_ref
    finally:
        lock.release()
    return restore_ref               
        
@require_context
def _restore_get(context, restore_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    result = model_query(   context, models.Restores, **kwargs).\
                            options(sa_orm.joinedload(models.Restores.metadata)).\
                            filter_by(id=restore_id).\
                            first()

    if not result:
        raise exception.RestoreNotFound(restore_id=restore_id)

    return result

@require_context
def restore_get(context, restore_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()    
    return _restore_get(context, restore_id, **kwargs) 


@require_context
def restore_get_metadata_cancel_flag(context, restore_id, return_val=0, process=None, **kwargs):
    flag='0'
    restore_obj = restore_get(context, restore_id)
    for meta in restore_obj.metadata:
        if meta.key == 'cancel_requested':
            flag = meta.value
    
    if return_val == 1:
        return flag

    if flag=='1': 
        if process:
            process.kill() 
        error = _('Cancel requested for restore')
        raise exception.ErrorOccurred(reason=error)

@require_context
def restore_get_all(context, snapshot_id=None, **kwargs):
    if not is_admin_context(context):
        if snapshot_id:
            return restore_get_all_by_snapshot(context, snapshot_id, **kwargs)
        else:
            return restore_get_all_by_project(context, context.project_id, **kwargs)
        
    if snapshot_id == None:
        if 'dashboard_item' in kwargs:
            if kwargs.get('dashboard_item') == 'activities':
                if 'time_in_minutes' in kwargs:
                    time_in_minutes = int(kwargs.get('time_in_minutes'))
                else:
                    time_in_minutes = 0
                time_delta = ((time_in_minutes / 60) / 24) * -1
                result = \
                    model_query(context,
                        models.Restores.id,
                        models.Restores.deleted,
                        models.Restores.deleted_at,
                        models.Restores.display_name,
                        models.Restores.status,
                        models.Restores.created_at,
                        models.Restores.user_id,
                        models.Restores.project_id,
                        (models.Snapshots.display_name).label('snapshot_name'),
                        (models.Snapshots.created_at).label('snapshot_created_at'),
                        (models.Workloads.display_name).label('workload_name'),
                        (models.Workloads.created_at).label('workload_created_at'),
                        **kwargs). \
                    filter(or_(models.Restores.created_at > func.adddate(func.now(), time_delta),
                               models.Restores.deleted_at > func.adddate(func.now(), time_delta))). \
                    outerjoin(models.Snapshots,
                            models.Restores.snapshot_id == models.Snapshots.id). \
                    outerjoin(models.Workloads,
                            models.Snapshots.workload_id == models.Workloads.id). \
                    order_by(models.Restores.created_at.desc()).all()
                return result
        else:
            return model_query(context, models.Restores, **kwargs).\
                            options(sa_orm.joinedload(models.Restores.metadata)).\
                            order_by(models.Restores.created_at.desc()).all()        
    else:
        return model_query(context, models.Restores, **kwargs).\
                            options(sa_orm.joinedload(models.Restores.metadata)).\
                            filter_by(snapshot_id=snapshot_id).\
                            order_by(models.Restores.created_at.desc()).all()

@require_context                            
def restore_get_all_by_snapshot(context, snapshot_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    return model_query(context, models.Restores, **kwargs).\
                        options(sa_orm.joinedload(models.Restores.metadata)).\
                        filter_by(snapshot_id=snapshot_id).\
                        order_by(models.Restores.created_at.desc()).all()
                                                        
@require_context
def restore_get_all_by_project(context, project_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    authorize_project_context(context, project_id)
    return model_query(context, models.Restores, **kwargs).\
                            options(sa_orm.joinedload(models.Restores.metadata)).\
                            filter_by(project_id=project_id).all()
        
@require_context
def restore_get_all_by_project_snapshot(context, project_id, snapshot_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    authorize_project_context(context, project_id)
    return model_query(context, models.Restores, **kwargs).\
                            options(sa_orm.joinedload(models.Restores.metadata)).\
                            filter_by(project_id=project_id).\
                            filter_by(snapshot_id=snapshot_id).\
                            order_by(models.Restores.created_at.desc()).all()

@require_context
def restore_show(context, restore_id):
    session = get_session()
    result = model_query(context, models.Restores, session=session).\
                            options(sa_orm.joinedload(models.Restores.metadata)).\
                            filter_by(id=restore_id).\
                            first()

    if not result:
        raise exception.RestoreNotFound(restore_id=restore_id)

    return result

@require_context
def restore_create(context, values):
    session = get_session()
    return _restore_update(context, values, None, False, session)

@require_context
def restore_update(context, restore_id, values, purge_metadata=False):
    session = get_session()
    return _restore_update(context, values, restore_id, purge_metadata, session)

   
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

#### RestoredVMs ################################################################
""" restored_vms functions """
def _set_metadata_for_restored_vms(context, restored_vm_ref, metadata,
                                    purge_metadata, session):
    """
    Create or update a set of restored_vms_metadata for a given restored_vm

    :param context: Request context
    :param restored_vm_ref: An restored_vm object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in restored_vm_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'restored_vm_id': restored_vm_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _restored_vms_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _restored_vms_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _restored_vms_metadata_delete(context, metadata_ref, session=session)

@require_context
def _restored_vms_metadata_create(context, values, session):
    """Create an RestoredMetadata object"""
    metadata_ref = models.RestoredVMMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _restored_vms_metadata_update(context, metadata_ref, values, session)

@require_context
def restored_vms_metadata_create(context, values, session):
    """Create an RestoredMetadata object"""
    session = get_session()
    return _restored_vms_metadata_create(context, values, session)

@require_context
def _restored_vms_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by restored_vms_metadata_create and restored_vms_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _restored_vms_metadata_delete(context, metadata_ref, session):
    """
    Used internally by restored_vms_metadata_create and restored_vms_metadata_update
    """
    metadata_ref.delete(session=session)

def _restored_vm_update(context, values, vm_id, restore_id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})
    
    if vm_id:
        restored_vm_ref = _restored_vm_get(context, vm_id, restore_id, session)
    else:
        restored_vm_ref = models.RestoredVMs()
        if not values.get('id'):
            values['id'] = str(uuid.uuid4())
        if not values.get('size'):
            values['size'] = 0

    restored_vm_ref.update(values)
    restored_vm_ref.save(session)
    
    if metadata:
        _set_metadata_for_restored_vms(context, restored_vm_ref, metadata, purge_metadata, session=session)  
      
    return restored_vm_ref


@require_context
def restored_vm_create(context, values):
    session = get_session()
    return _restored_vm_update(context, values, None, None, False, session)

@require_context
def restored_vm_update(context, vm_id, restore_id, values, purge_metadata=False):
    session = get_session()
    return _restored_vm_update(context, values, vm_id, restore_id, purge_metadata, session)

@require_context
def restored_vms_get(context, restore_id, **kwargs):
    session = kwargs.get('session') or get_session()
    try:
        query = session.query(models.RestoredVMs)\
                       .options(sa_orm.joinedload(models.RestoredVMs.metadata))\
                       .filter_by(restore_id=restore_id)\

        restored_vms = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.RestoredVMsNotFound(restore_id=restore_id)
    
    return restored_vms    
   
@require_context
def _restored_vm_get(context, vm_id, restore_id, session):
    try:
        query = session.query(models.RestoredVMs)\
                       .options(sa_orm.joinedload(models.RestoredVMs.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(restore_id=restore_id)

        #TODO(gbasava): filter out deleted restored_vm if context disallows it
        restored_vm = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.RestoredVMsNotFound(restore_id=restore_id)

    return restored_vm

@require_context
def restored_vm_get(context, vm_id, restore_id):
    session = get_session() 
    return _restored_vm_get(context, vm_id, restore_id, session)   
    
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
                                           purge_metadata, session):
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
            _restored_vm_resource_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _restored_vm_resource_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                restored_vm_resource_metadata_delete(context, metadata_ref, session=session)

@require_context
def _restored_vm_resource_metadata_create(context, values, session):
    """Create an RestoredVMResourceMetadata object"""
    metadata_ref = models.RestoredVMResourceMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _restored_vm_resource_metadata_update(context, metadata_ref, values, session)

@require_context
def restored_vm_resource_metadata_create(context, values):
    """Create an RestoredVMResourceMetadata object"""
    session = get_session()  
    return _restored_vm_resource_metadata_create(context, values, session)

def _restored_vm_resource_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by restored_vm_resource_metadata_create and restored_vm_resource_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def restored_vm_resource_metadata_delete(context, metadata_ref):
    """
    Used internally by restored_vm_resource_metadata_create and restored_vm_resource_metadata_update
    """
    session = get_session()
    metadata_ref.delete(session=session)
    return metadata_ref

def _restored_vm_resource_update(context, values, restored_vm_resource_id, purge_metadata, session):
    
    metadata = values.pop('metadata', {})

    if restored_vm_resource_id:
        restored_vm_resource_ref = restored_vm_resource_get(context, restored_vm_resource_id, session)
    else:
        restored_vm_resource_ref = models.RestoredVMResources()
    
    restored_vm_resource_ref.update(values)
    restored_vm_resource_ref.save(session)
    
    _set_metadata_for_restored_vm_resource(context, restored_vm_resource_ref, metadata, purge_metadata, session)  
      
    return restored_vm_resource_ref


@require_context
def restored_vm_resource_create(context, values):
    session = get_session()
    return _restored_vm_resource_update(context, values, None, False, session)

@require_context
def restored_vm_resource_update(context, restored_vm_resource_id, values, purge_metadata=False):
    session = get_session()
    return _restored_vm_resource_update(context, values, restored_vm_resource_id, purge_metadata, session)

@require_context
def restored_vm_resources_get(context, vm_id, restore_id):
    session = get_session()
    try:
        query = session.query(models.RestoredVMResources)\
                       .options(sa_orm.joinedload(models.RestoredVMResources.metadata))\
                       .filter_by(vm_id=vm_id)\
                       .filter_by(restore_id=restore_id)

        #TODO(gbasava): filter out deleted restores if context disallows it
        restored_vm_resources = query.all()

    except sa_orm.exc.NoResultFound:
        raise exception.RestoredVMResourcesNotFound(restore_vm_id = vm_id, restore_id = restore_id)
    
    return restored_vm_resources

@require_context
def restored_vm_resource_get_by_resource_name(context, vm_id, restore_id, resource_name):
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
        raise exception.RestoredVMResourceWithNameNotFound(resource_name = resource_name,
                                                           restore_vm_id = vm_id, 
                                                           restore_id = restore_id)

    return restored_vm_resources

@require_context
def restored_vm_resource_get(context, id):
    session = get_session()
    try:
        query = session.query(models.RestoredVMResources)\
                       .options(sa_orm.joinedload(models.RestoredVMResources.metadata))\
                       .filter_by(id=id)

        #TODO(gbasava): filter out deleted restored if context disallows it
        restored_vm_resources = query.first()

    except sa_orm.exc.NoResultFound:
        raise exception.RestoredVMResourceWithIdNotFound(id = id)

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

#### Tasks ################################################################
""" task functions """
def _set_status_messages_for_task(context, task_ref, status_messages, session):
    """
    Create or update a set of task_status_messages for a given task

    :param context: Request context
    :param task_ref: A task object
    :param status_messages: A dict of status_messages to set
    :param session: A SQLAlchemy session to use (if present)
    """
    for key, status_message in status_messages.iteritems():
        status_messages_values = {'task_id': task_ref.id, 'status_message': status_message}
        _task_status_messages_create(context, status_messages_values, session)

@require_context
def _task_status_messages_create(context, values, session):
    """Create a TaskStatusMessages object"""
    status_messages_ref = models.TaskStatusMessages()    
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _task_status_messages_update(context, status_messages_ref, values, session)

@require_context
def task_status_messages_create(context, values, session):
    """Create an TaskStatusMessages object"""
    session = get_session()
    return _task_status_messages_create(context, values, session)

@require_context
def _task_status_messages_update(context, status_messages_ref, values, session):
    """
    Used internally by task_status_messages_create and task_status_messages_update
    """
    values["deleted"] = False
    status_messages_ref.update(values)
    status_messages_ref.save(session=session)
    return status_messages_ref

@require_context
def _task_status_messages_delete(context, status_messages_ref, session):
    """
    Used internally by task_status_messages_create and task_status_messages_update
    """
    status_messages_ref.delete(session=session)

def _task_update(context, values, task_id, session):
    try:
        lock.acquire()    
        status_messages = values.pop('status_messages', {})
        
        if task_id:
            task_ref = model_query(context, models.Tasks, session=session, read_deleted="yes").\
                                        filter_by(id=task_id).first()
            if not task_ref:
                lock.release()
                raise exception.TasksNotFound(task_id = task_id)
                                                        
        else:
            task_ref = models.Tasks()
            if not values.get('id'):
                values['id'] = str(uuid.uuid4())
                
        task_ref.update(values)
        task_ref.save(session)
        
        if status_messages:
            _set_status_messages_for_task(context, task_ref, status_messages, session=session)  
          
        return task_ref
    finally:
        lock.release()
    return task_ref               
        
@require_context
def _task_get(context, task_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    result = model_query(   context, models.Tasks, **kwargs).\
                            options(sa_orm.joinedload(models.Tasks.status_messages)).\
                            filter_by(id=task_id).\
                            first()

    if not result:
        raise exception.TasksNotFound(task_id=task_id)

    return result

@require_context
def task_get(context, task_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()    
    return _task_get(context, task_id, **kwargs) 

@require_context
def task_get_all(context, **kwargs):
    if not is_admin_context(context):
        return task_get_all_by_project(context, context.project_id, **kwargs)

    status = kwargs.get('status',None)    
    size = kwargs.get('size',None)
    page = kwargs.get('page',None)
    time_in_minutes = kwargs.get('time_in_minutes',None)   

    offset = 0
    if page is not None and size is not None:
       offset = (int(page) - 1) * int(size)
 
    query =  model_query(context, models.Tasks, **kwargs)
    query = query.options(sa_orm.joinedload(models.Tasks.status_messages))

    if status is not None:
       query = query.filter_by(status=status)
    
    if time_in_minutes is not None:
       now = timeutils.utcnow()
       minutes_ago = now - timedelta(minutes=int(time_in_minutes))
       query = query.filter(models.Tasks.created_at > minutes_ago)  
 
    query = query.order_by(models.Tasks.created_at.desc())
    if size is not None:
       query = query.limit(int(size))

    if page is not None:
       query = query.offset(offset)

    return query.all()
     
@require_context
def task_get_all_by_project(context, project_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    authorize_project_context(context, project_id)
    return model_query(context, models.Tasks, **kwargs).\
                            options(sa_orm.joinedload(models.Tasks.status_messages)).\
                            filter_by(project_id=project_id).all()
        

@require_context
def task_show(context, task_id):
    session = get_session()
    result = model_query(context, models.Tasks, session=session).\
                            options(sa_orm.joinedload(models.Tasks.status_messages)).\
                            filter_by(id=task_id).\
                            first()

    if not result:
        raise exception.TasksNotFound(task_id=task_id)

    return result

@require_context
def task_create(context, values):
    session = get_session()
    return _task_update(context, values, None, session)

@require_context
def task_update(context, task_id, values):
    session = get_session()
    return _task_update(context, values, task_id, session)

@require_context
def task_delete(context, task_id):
    session = get_session()
    with session.begin():
        session.query(models.Tasks).\
            filter_by(id=task_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
            
            
#### Setting ################################################################
""" setting functions """
def _set_metadata_for_setting(context, setting_ref, metadata,
                                    purge_metadata, session):
    """
    Create or update a set of setting_metadata for a given setting

    :param context: Request context
    :param setting_ref: A setting object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in setting_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'settings_name': setting_ref.name,
                           'settings_project_id' : setting_ref.project_id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _setting_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _setting_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _setting_metadata_delete(context, metadata_ref, session=session)

@require_context
def _setting_metadata_create(context, values, session):
    """Create a SettingMetadata object"""
    metadata_ref = models.SettingMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _setting_metadata_update(context, metadata_ref, values, session)

@require_context
def setting_metadata_create(context, values, session):
    """Create a SettingMetadata object"""
    session = get_session()
    return _setting_metadata_create(context, values, session)

@require_context
def _setting_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by setting_metadata_create and setting_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _setting_metadata_delete(context, metadata_ref, session):
    """
    Used internally by setting_metadata_create and setting_metadata_update
    """
    metadata_ref.delete(session=session)

def _setting_update(context, values, setting_name, purge_metadata, session):
    try:
        lock.acquire()    
        metadata = values.pop('metadata', {})
        
        if setting_name:
            setting_ref = model_query(context, models.Settings, session=session, read_deleted="yes").\
                                        filter_by(name=setting_name).\
                                        filter_by(project_id=context.project_id).\
                                        first()
            if not setting_ref:
                lock.release()
                raise exception.SettingNotFound(setting_name = setting_name)
                                                        
        else:
            setting_ref = models.Settings()
            if not values.get('status'):
                values['status'] = 'available'
            if not values.get('project_id'):
                values['project_id'] = context.project_id                
        if 'is_hidden' in values:
           values['hidden'] = int(values['is_hidden'])
        setting_ref.update(values)
        setting_ref.save(session)
        
        if metadata:
            _set_metadata_for_setting(context, setting_ref, metadata, purge_metadata, session=session)  
          
        return setting_ref
    finally:
        lock.release()
    return setting_ref               
        
@require_context
def _setting_get(context, setting_name, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    get_hidden = kwargs.get('get_hidden', False)         
    result = model_query(   context, models.Settings, **kwargs).\
                    filter_by(hidden=get_hidden).\
                    options(sa_orm.joinedload(models.Settings.metadata)).\
                    filter_by(name=setting_name).\
                    filter_by(project_id=context.project_id).\
                    first()

    if not result:
        if setting_name == 'page_size':
            return 10
        else:
            raise exception.SettingNotFound(setting_name=setting_name)


    return result

@require_context
def setting_get(context, setting_name, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()    
    return _setting_get(context, setting_name, **kwargs) 

def setting_get_all(context, **kwargs):
    if context and not is_admin_context(context):
        return setting_get_all_by_project(context, context.project_id, **kwargs)
    
    get_hidden = kwargs.get('get_hidden', False)
 
    return model_query(context, models.Settings, **kwargs).\
                        options(sa_orm.joinedload(models.Settings.metadata)).\
                        filter_by(hidden=get_hidden).\
                        order_by(models.Settings.created_at.desc()).all()        

@require_context
def setting_get_all_by_project(context, project_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    authorize_project_context(context, project_id)
    return model_query(context, models.Settings, **kwargs).\
                            options(sa_orm.joinedload(models.Settings.metadata)).\
                            filter_by(project_id=project_id).all()
        
@require_context
def setting_create(context, values):
    session = get_session()
    return _setting_update(context, values, None, False, session)

@require_context
def setting_update(context, setting_name, values, purge_metadata=False):
    session = get_session()
    return _setting_update(context, values, setting_name, purge_metadata, session)

@require_context
def setting_delete(context, setting_name):
    session = get_session()
    setting = _setting_get(context, setting_name, session = session)
    for metadata_ref in setting.metadata:
        metadata_ref.purge(session=session)
    session.refresh(setting)
    setting.purge(session=session)
     

#### VaultStorage ################################################################
""" vault_storage functions """
def _set_metadata_for_vault_storage(context, vault_storage_ref, metadata,
                                    purge_metadata, session):
    """
    Create or update a set of vault_storage_metadata for a given vault_storage

    :param context: Request context
    :param vault_storage_ref: A vault_storage object
    :param metadata: A dict of metadata to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_metadata = {}
    for metadata_ref in vault_storage_ref.metadata:
        orig_metadata[metadata_ref.key] = metadata_ref

    for key, value in metadata.iteritems():
        metadata_values = {'vault_storage_id': vault_storage_ref.id,
                           'key': key,
                           'value': value}
        if key in orig_metadata:
            metadata_ref = orig_metadata[key]
            _vault_storage_metadata_update(context, metadata_ref, metadata_values, session)
        else:
            _vault_storage_metadata_create(context, metadata_values, session)

    if purge_metadata:
        for key in orig_metadata.keys():
            if key not in metadata:
                metadata_ref = orig_metadata[key]
                _vault_storage_metadata_delete(context, metadata_ref, session=session)

@require_context
def _vault_storage_metadata_create(context, values, session):
    """Create a VaultStorageMetadata object"""
    metadata_ref = models.VaultStorageMetadata()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())    
    return _vault_storage_metadata_update(context, metadata_ref, values, session)

@require_context
def vault_storage_metadata_create(context, values, session):
    """Create an VaultStorageMetadata object"""
    session = get_session()
    return _vault_storage_metadata_create(context, values, session)

@require_context
def _vault_storage_metadata_update(context, metadata_ref, values, session):
    """
    Used internally by vault_storage_metadata_create and vault_storage_metadata_update
    """
    values["deleted"] = False
    metadata_ref.update(values)
    metadata_ref.save(session=session)
    return metadata_ref

@require_context
def _vault_storage_metadata_delete(context, metadata_ref, session):
    """
    Used internally by vault_storage_metadata_create and vault_storage_metadata_update
    """
    metadata_ref.delete(session=session)

def _vault_storage_update(context, values, vault_storage_id, purge_metadata, session):
    try:
        lock.acquire()    
        metadata = values.pop('metadata', {})
        
        if vault_storage_id:
            vault_storage_ref = model_query(context, models.VaultStorages, session=session, read_deleted="yes").\
                                            filter_by(id=vault_storage_id).first()
            if not vault_storage_ref:
                lock.release()
                raise exception.VaultStorageNotFound(vault_storage_id = vault_storage_id)
                                                        
        else:
            vault_storage_ref = models.VaultStorages()
            if not values.get('id'):
                values['id'] = str(uuid.uuid4())
            if not values.get('capacity'):
                values['capacity'] = 0
            if not values.get('used'):
                values['used'] = 0                
                
        vault_storage_ref.update(values)
        vault_storage_ref.save(session)
        
        if metadata:
            _set_metadata_for_vault_storage(context, vault_storage_ref, metadata, purge_metadata, session=session)  
          
        return vault_storage_ref
    finally:
        lock.release()
    return vault_storage_ref               
        
@require_context
def _vault_storage_get(context, vault_storage_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    result = model_query(   context, models.VaultStorages, **kwargs).\
                            options(sa_orm.joinedload(models.VaultStorages.metadata)).\
                            filter_by(id=vault_storage_id).\
                            first()

    if not result:
        raise exception.VaultStorageNotFound(vault_storage_id=vault_storage_id)

    return result

@require_context
def vault_storage_get(context, vault_storage_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()    
    return _vault_storage_get(context, vault_storage_id, **kwargs) 

@require_context
def vault_storage_get_all(context, workload_id=None, **kwargs):
    if not is_admin_context(context):
        return vault_storage_get_all_by_project(context, context.project_id, **kwargs)
    
    if workload_id == None:
        return model_query(context, models.VaultStorages, **kwargs).\
                            options(sa_orm.joinedload(models.VaultStorages.metadata)).\
                            order_by(models.VaultStorages.created_at.desc()).all()        
    else:
        return model_query(context, models.VaultStorages, **kwargs).\
                            options(sa_orm.joinedload(models.VaultStorages.metadata)).\
                            filter_by(workload_id=workload_id).\
                            order_by(models.VaultStorages.created_at.desc()).all()
                            
@require_admin_context
def vault_storage_get_all_by_workload(context, workload_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
        
    return model_query(context, models.VaultStorages, **kwargs).\
                        options(sa_orm.joinedload(models.VaultStorages.metadata)).\
                        filter_by(workload_id=workload_id).\
                        order_by(models.VaultStorages.created_at.desc()).all()
                                                        
@require_context
def vault_storage_get_all_by_project(context, project_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    authorize_project_context(context, project_id)
    return model_query(context, models.VaultStorages, **kwargs).\
                            options(sa_orm.joinedload(models.VaultStorages.metadata)).\
                            filter_by(project_id=project_id).all()
        
@require_context
def vault_storage_create(context, values):
    session = get_session()
    return _vault_storage_update(context, values, None, False, session)

@require_context
def vault_storage_update(context, vault_storage_id, values, purge_metadata=False):
    session = get_session()
    return _vault_storage_update(context, values, vault_storage_id, purge_metadata, session)

@require_context
def vault_storage_delete(context, vault_storage_id):
    session = get_session()
    with session.begin():
        session.query(models.VaultStorages).\
            filter_by(id=vault_storage_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
            
"""
Permanent Deletes
"""
@require_context
def purge_snapshot(context, id, session=None):
    if session == None:
        session = get_session()
    for snapshot_vm_resource in snapshot_resources_get(context, id, session=session):
        if snapshot_vm_resource.resource_type == 'disk':
            for vm_disk_resource_snap in vm_disk_resource_snaps_get(context, snapshot_vm_resource.id, session=session):
                for metadata_ref in vm_disk_resource_snap.metadata:
                    metadata_ref.purge(session)
                session.refresh(vm_disk_resource_snap)
                vm_disk_resource_snap.purge(session)
        if snapshot_vm_resource.resource_type == 'network' or \
            snapshot_vm_resource.resource_type == 'subnet' or \
            snapshot_vm_resource.resource_type == 'router' or \
            snapshot_vm_resource.resource_type == 'nic':
            for vm_network_resource_snap in vm_network_resource_snaps_get(context, snapshot_vm_resource.id, session=session):
                for metadata_ref in vm_network_resource_snap.metadata:
                    metadata_ref.purge(session)
                session.refresh(vm_network_resource_snap)
                vm_network_resource_snap.purge(session)
        if snapshot_vm_resource.resource_type == 'security_group':
            for vm_security_group_rule_snap in vm_security_group_rule_snaps_get(context, snapshot_vm_resource.id, session=session):
                for metadata_ref in vm_network_resource_snap.metadata:
                    metadata_ref.purge(session)
                session.refresh(vm_security_group_rule_snap)
                vm_security_group_rule_snap.purge(session)
        
        for metadata_ref in snapshot_vm_resource.metadata:
            metadata_ref.purge(session)
        session.refresh(snapshot_vm_resource)
        snapshot_vm_resource.purge(session)
    
    for snapshot_vm in snapshot_vms_get(context, id, session=session):
        for metadata_ref in snapshot_vm.metadata:
            metadata_ref.purge(session)
        vm_recent_snapshot = vm_recent_snapshot_get(context, snapshot_vm.vm_id, session=session)
        if vm_recent_snapshot:
            vm_recent_snapshot.purge(session)
        session.refresh(snapshot_vm)
        snapshot_vm.purge(session)
        
    snapshot = snapshot_get(context, id, session=session, read_deleted='yes')
    if snapshot:
        snapshot.purge(session)
    
@require_admin_context
def purge_workload(context, id):
    try:
        session = get_session()
        for snapshot in snapshot_get_all(context, session=session, read_deleted='yes'):
            purge_snapshot(context, snapshot.id, session)
        for workload_vm in workload_vms_get(context, id, session=session):
            for metadata_ref in workload_vm.metadata:
                metadata_ref.purge(session)
            session.refresh(workload_vm)
            workload_vm.purge(session)
        workload = _workload_get(context, id, session=session)
        if workload:
            for metadata_ref in workload.metadata:
                metadata_ref.purge(session)
            session.refresh(workload)
            workload.purge(session)

    except Exception as ex:
        LOG.exception(ex)

@require_context
def openstack_workload_update(context, openstack_workload_id, values):
    session = get_session()
    return _openstack_workload_update(context, openstack_workload_id, values, session)

@require_context
def openstack_workload_get(context, openstack_workload_id, **kwargs):
    session = get_session()
    return _openstack_workload_get(context, openstack_workload_id, session, **kwargs)

@require_context
def _openstack_workload_update(context, id, values, session):
    try:
        openstack_workload_ref = _openstack_workload_get(context, id, session)
    except Exception as ex:
        openstack_workload_ref = models.OpenstackWorkload()
        if not values.get('id'):
            values['id'] = id

    openstack_workload_ref.update(values)
    openstack_workload_ref.save(session)

    return openstack_workload_ref

@require_context
def _openstack_workload_get(context, id, session, **kwargs):
    try:
        openstack_workload = model_query(
            context, models.OpenstackWorkload, session=session, **kwargs).\
            filter_by(id=id).first()

        if openstack_workload is None:
            raise exception.OpenStackWorkloadNotFound(id=id)

    except sa_orm.exc.NoResultFound:
        raise exception.OpenStackWorkloadNotFound(id=id)

    return openstack_workload

@require_context
def openstack_config_snapshot_create(context, values):
    session = get_session()
    return _openstack_config_snapshot_update(context, None, values, session)

@require_context
def openstack_config_snapshot_update(context, snapshot_id, values ):
    session = get_session()
    return _openstack_config_snapshot_update(context, snapshot_id, values, session)


def _openstack_config_snapshot_update(context, snapshot_id, values, session):
    try:
        lock.acquire()
        metadata = values.pop('metadata', {})

        if snapshot_id:
            snapshot_ref = model_query(context, models.OpenstackSnapshot, session=session, read_deleted="yes"). \
                filter_by(id=snapshot_id).first()
            if not snapshot_ref:
                lock.release()
                raise exception.SnapshotNotFound(snapshot_id=snapshot_id)
        else:
            snapshot_ref = models.OpenstackSnapshot()
            if not values.get('id'):
                values['id'] = str(uuid.uuid4())
            if not values.get('size'):
                values['size'] = 0
        snapshot_ref.update(values)
        snapshot_ref.save(session)

        return snapshot_ref
    finally:
        lock.release()
    return snapshot_ref

@require_context
def _openstack_config_snapshot_get(context, snapshot_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    result = model_query(context, models.OpenstackSnapshot, **kwargs).\
                            filter_by(id=snapshot_id).\
                            first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result

@require_context
def openstack_config_snapshot_get(context, snapshot_id, **kwargs):
    if kwargs.get('session') == None:
        kwargs['session'] = get_session()
    return _openstack_config_snapshot_get(context, snapshot_id, **kwargs)


@require_context
def openstack_config_snapshot_get_all(context, **kwargs):
    qs = model_query(context, models.OpenstackSnapshot, **kwargs)
    if 'openstack_workload_id' in kwargs and kwargs['openstack_workload_id'] is not None and kwargs['openstack_workload_id'] != '':
       qs = qs.filter_by(openstack_workload_id=kwargs['openstack_workload_id'])
    if 'date_from' in kwargs and kwargs['date_from'] is not None and kwargs['date_from'] != '':
       if 'date_to' in kwargs and kwargs['date_to'] is not None and kwargs['date_to'] != '':
           date_to = kwargs['date_to']
       else:
            date_to = datetime.now()
       qs = qs.filter(and_(models.OpenstackSnapshot.created_at >= func.date_format(kwargs['date_from'],'%y-%m-%dT%H:%i:%s'),\
                      models.OpenstackSnapshot.created_at <= func.date_format(date_to,'%y-%m-%dT%H:%i:%s')))

    return qs.order_by(models.OpenstackSnapshot.created_at.desc()).all()


@require_context
def openstack_config_snapshot_delete(context, snapshot_id):
    session = get_session()
    with session.begin():
        session.query(models.OpenstackSnapshot).\
            filter_by(id=snapshot_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
