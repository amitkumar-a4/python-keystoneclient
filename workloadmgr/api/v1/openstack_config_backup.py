# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2017 TrilioData, Inc.
# All Rights Reserved.

"""The OpenStack configuration backup api."""

from webob import exc
import time
import pickle
import pdb
import os
import yaml
from workloadmgr.api import wsgi
from workloadmgr import exception as wlm_exceptions
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr import workloads as workloadAPI
from workloadmgr.api import xmlutil
from workloadmgr.api.views import openstack_workload as openstack_workload_views
from workloadmgr.api.views import openstack_snapshot as openstack_snapshot_views

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS
CONFIG_FILES_PATH = "/opt/stack/workloadmgr/workloadmgr/templates/openstack_config.yaml"

services_to_snapshot = {
    'ceilometer': ['/etc/ceilometer'], 
    'compute': ['/etc/nova', "/var/lib/nova'"], 
    'keystone': ['/etc/keystone', '/var/lib/keystone'],
    'Orchestration': ['/etc/heat/'], 
    'cinder': ['/etc/cinder', '/var/lib/cinder'], 
    'glance': ['/etc/glance', '/var/lib/glance'], 
    'swift': ['/etc/swift'], 
    'neutron': ['/etc/neutron', '/var/lib/neutron']
    }


class OpenStackConfigBackupController(wsgi.Controller):
    """The OpenStack config backup API controller for the workload manager API."""

    _view_builder_class = openstack_workload_views.ViewBuilder
    snapshot_view_builder = openstack_snapshot_views.ViewBuilder()
    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(OpenStackConfigBackupController, self).__init__()


    def openstack_config_workload(self, req, body):
        """Update OpenStack config backup"""
        try:
            if not self.is_valid_body(body, 'jobschedule'):
                raise exc.HTTPBadRequest()

            context = req.environ['workloadmgr.context']

            jobschedule = body['jobschedule']
            
            existing_openstack_workload = self.workload_api.openstack_config_workload_show(context)
            existing_jobschedule = None

            #If OpenStack workload is never enabled, Then user should first enable it 
            #before any update.
            if not existing_openstack_workload and jobschedule.get('enabled', '').lower() != 'true':
                message = "OpenStack configuration backup is not enabled. First enable it."
                raise wlm_exceptions.OpenStackWorkload(message=message)
            #If Openstack backup scheduler is disabled then user can't update this
            elif existing_openstack_workload:
                existing_jobschedule = pickle.loads(existing_openstack_workload['jobschedule'])
                if existing_jobschedule['enabled'].lower() == 'false' and \
                   jobschedule.get('enabled', '').lower() != 'true':
                   message = "Can not update OpenStack configuration backup in disabled state."
                   raise wlm_exceptions.OpenStackWorkload(message=message) 

            if existing_jobschedule:
                jobdefaults = existing_jobschedule
            else:
                jobdefaults = {'start_time': '09:00 PM',
                               'interval': u'24hr',
                               'start_date': time.strftime("%x"),
                               'end_date': 'No End',
                               'enabled': 'true',
                               'retention_policy_type': 'Number of Snapshots to Keep',
                               'retention_policy_value': '30'}

            if not 'start_time' in jobschedule:
                jobschedule['start_time'] = jobdefaults['start_time']

            if not 'interval' in jobschedule:
                jobschedule['interval'] = jobdefaults['interval']

            if not 'enabled' in jobschedule:
                jobschedule['enabled'] = jobdefaults['enabled']

            if not 'start_date' in jobschedule:
                jobschedule['start_date'] = jobdefaults['start_date']

            if not 'end_date' in jobschedule:
                jobschedule['end_date'] = jobdefaults['end_date']

            if not 'retention_policy_type' in jobschedule:
                jobschedule['retention_policy_type'] = jobdefaults['retention_policy_type']

            if not 'retention_policy_value' in jobschedule:
                jobschedule['retention_policy_value'] = jobdefaults['retention_policy_value']

            try:
                new_openstack_workload = self.workload_api.openstack_config_workload(context,
                                                                           jobschedule)
            except Exception as error:
                raise exc.HTTPServerError(explanation=unicode(error))

            retval = self._view_builder.summary(req, new_openstack_workload)
            return retval
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def openstack_config_workload_show(self, req):
        """Show OpenStack workload object"""
        #import pdb;pdb.set_trace()
        try:
            context = req.environ['workloadmgr.context']

            openstack_workload = self.workload_api.openstack_config_workload_show(context)
            if openstack_workload:
                return {'openstack_workload': openstack_workload}
            else:
                message = "OpenStack coniguration backup is not enabled."
                raise wlm_exceptions.OpenStackWorkload(message=message)
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def openstack_config_snapshot(self, req, id, body=None):
        """snapshot a openstack workload."""
        #import pdb;pdb.set_trace()
        try:
            context = req.environ['workloadmgr.context']
    
            openstack_workload = self.workload_api.openstack_config_workload_show(context)
            if not openstack_workload:
               message = "OpenStack coniguration backup is not enabled."
               LOG.error(message)
               raise wlm_exceptions.OpenStackWorkload(message=message)

            #Read list of services to snapshot from default file
            #Create a check here if after reaading from file it's empty then read from above map
            #Read list of services to snapshot from default file
            if os.path.exists(CONFIG_FILES_PATH):
                with open(CONFIG_FILES_PATH, 'r') as file:
                    service_list = yaml.load(file)
                    if len(service_list):
                        services_to_snap = service_list
                    else:
                        services_to_snap = services_to_snapshot
            else:
                services_to_snap = services_to_snapshot
    
            if (body and 'snapshot' in body):
                name = body['snapshot'].get('name', "") or 'Snapshot'
                name = name.strip() or 'Snapshot'
                description = body['snapshot'].get('description', "") or 'no-description'
                description = description.strip() or 'no-description'
    
            new_snapshot = self.workload_api.openstack_config_snapshot(context, services_to_snap, name, description)
            return self.snapshot_view_builder.summary(req, dict(new_snapshot.iteritems()))
        except wlm_exceptions.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except wlm_exceptions.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def openstack_config_snapshot_list(self, req):
        """Returns a summary list of snapshots."""
        try:
            context = req.environ['workloadmgr.context']
            snapshots = self.workload_api.get_openstack_config_snapshots(context)
            return self.snapshot_view_builder.summary_list(req, snapshots)
        except exc.HTTPNotFound as error:
            LOG.exception(error)
            raise error
        except exc.HTTPBadRequest as error:
            LOG.exception(error)
            raise error
        except exc.HTTPServerError as error:
            LOG.exception(error)
            raise error
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))
    
    def openstack_config_snapshot_show(self, req, id):
        """Return data about the given Snapshot."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                snapshot = self.workload_api.get_openstack_config_snapshots(context, id)
            except wlm_exceptions.NotFound:
                raise exc.HTTPNotFound()
            return self.snapshot_view_builder.detail(req, snapshot)
        except exc.HTTPNotFound as error:
            LOG.exception(error)
            raise error
        except exc.HTTPBadRequest as error:
            LOG.exception(error)
            raise error
        except exc.HTTPServerError as error:
            LOG.exception(error)
            raise error
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

def create_resource(ext_mgr):
    return wsgi.Resource(OpenStackConfigBackupController(ext_mgr))
