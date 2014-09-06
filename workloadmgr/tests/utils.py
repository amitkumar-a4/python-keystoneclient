# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2014 Trilio Data, Inc


import os

from workloadmgr import context
from workloadmgr import db


def get_test_admin_context():
    return context.get_admin_context()


def create_workload(ctxt,
                    host='test_host',
                    display_name='test_workload',
                    display_description='this is a test workload',
                    status='available',
                    source_platform='openstack',
                    workload_type_id='test_workload_type',
                    availability_zone='nova',
                    jobschedule='test_jobschedule',
                    **kwargs):
    """Create a workload object in the DB."""
    workload_type = db.workload_type_get(ctxt, workload_type_id)
    workload = {}
    workload['host'] = host
    workload['user_id'] = ctxt.user_id
    workload['project_id'] = ctxt.project_id
    workload['status'] = status
    workload['display_name'] = display_name
    workload['display_description'] = display_description
    workload['availability_zone'] = availability_zone
    workload['source_platform'] = source_platform
    workload['workload_type_id'] = workload_type_id
    workload['jobschedule'] = jobschedule
    for key in kwargs:
        workload[key] = kwargs[key]
    return db.workload_create(ctxt, workload)


def create_workloadtype(ctxt,
                        display_name='test_workloadtype',
                        display_description='this is a test workloadtype',
                        status='creating',
                        is_public=True):
    workloadtype = {}
    workloadtype['user_id'] = ctxt.user_id
    workloadtype['project_id'] = ctxt.project_id
    workloadtype['status'] = status
    workloadtype['display_name'] = display_name
    workloadtype['display_description'] = display_description
    return db.workload_type_create(ctxt, workloadtype)

def create_snapshot(ctxt,
                    workload_id,
                    display_name='test_snapshot',
                    display_description='this is a test snapshot',
                    status='creating'):
    workload = db.workload_get(ctxt, workload_id)
    snapshot = {}
    snapshot['workload_id'] = workload_id
    snapshot['user_id'] = ctxt.user_id
    snapshot['project_id'] = ctxt.project_id
    snapshot['status'] = status
    snapshot['display_name'] = display_name
    snapshot['display_description'] = display_description
    return db.snapshot_create(ctxt, snapshot)
