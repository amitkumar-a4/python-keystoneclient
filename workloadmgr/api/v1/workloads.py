# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The workloads api."""

import os
import json
import webob
from webob import exc
from xml.dom import minidom
from datetime import datetime
import ConfigParser

from cgi import parse_qs, escape
from workloadmgr.api import extensions
from workloadmgr.api import wsgi
from workloadmgr.api import common
from workloadmgr.api.views import workloads as workload_views
from workloadmgr.api.views import snapshots as snapshot_views
from workloadmgr.api import xmlutil
from workloadmgr import workloads as workloadAPI
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr import settings as settings_module

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)

def make_workload(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('vm_id')
    elem.set('object_count')
    elem.set('availability_zone')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
    elem.set('fail_reason')



class WorkloadTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workload', selector='workload')
        make_workload(root)
        alias = WorkloadMgrs.alias
        namespace = WorkloadMgrs.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class WorkloadsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('workloads')
        elem = xmlutil.SubTemplateElement(root, 'workload', selector='workloads')
        make_workload(elem)
        alias = WorkloadMgrs.alias
        namespace = WorkloadMgrs.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})

class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        workload = self._extract_workload(dom)
        return {'body': {'workload': workload}}

class UpdateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        workload = self._extract_workload(dom)
        return {'body': {'workload': workload}}

    def _extract_workload(self, node):
        workload = {}
        workload_node = self.find_first_child_named(node, 'workload')

        attributes = ['display_name', 'display_description']

        for attr in attributes:
            if workload_node.getAttribute(attr):
                workload[attr] = workload_node.getAttribute(attr)
        return workload

class WorkloadMgrsController(wsgi.Controller):
    """The API controller """

    _view_builder_class = workload_views.ViewBuilder
    snapshot_view_builder = snapshot_views.ViewBuilder()

    def __init__(self):
        self.workload_api = workloadAPI.API()
        super(WorkloadMgrsController, self).__init__()

    @wsgi.serializers(xml=WorkloadTemplate)
    def show(self, req, id):
        """Return data about the given workload."""
        try:
            context = req.environ['workloadmgr.context']
            workload = self.workload_api.workload_show(context, workload_id=id)
            return self._view_builder.detail(req, workload)
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))
            

    def delete(self, req, id):
        """Delete a workload."""
        try:
            context = req.environ['workloadmgr.context']
            self.workload_api.workload_delete(context, id)
            return webob.Response(status_int=202)
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))
    
    def unlock(self, req, id):
        try:
            context = req.environ['workloadmgr.context']
            self.workload_api.workload_unlock(context, id)
            return webob.Response(status_int=202)
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))
    
    def snapshot(self, req, id, body=None):
        """snapshot a workload."""
        try:
            context = req.environ['workloadmgr.context']
            full = None
            if ('QUERY_STRING' in req.environ) :
                qs=parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                full = var.get('full',[''])[0]
                full = escape(full)
                
            snapshot_type = 'incremental'
            if (full and full == '1'):
                snapshot_type = 'full'
            name = ''
            description = ''
            if (body and 'snapshot' in body):
                name = body['snapshot'].get('name', '')
                if not name:
                    name = ''
                if not description:
                    description = ''                    
                description = body['snapshot'].get('description', '')
                snapshot_type = body['snapshot'].get('snapshot_type', snapshot_type)                
            new_snapshot = self.workload_api.workload_snapshot(context, id, snapshot_type, name, description)
            return self.snapshot_view_builder.summary(req,dict(new_snapshot.iteritems()))
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))
                
    @wsgi.serializers(xml=WorkloadsTemplate)
    def index(self, req):
        """Returns a summary list of workloads."""
        try:
            return self._get_workloads(req, is_detail=False)
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    @wsgi.serializers(xml=WorkloadsTemplate)
    def detail(self, req):
        """Returns a detailed list of workloads."""
        try:
            return self._get_workloads(req, is_detail=True)
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

        
    def _get_workloads(self, req, is_detail):
        """Returns a list of workloadmgr, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        workloads_all = self.workload_api.workload_get_all(context)
        limited_list = common.limited(workloads_all, req)
        
        #TODO(giri): implement the search_opts to specify the filters
        workloads = []
        for workload in limited_list:
            if workload['deleted'] == False:
                workloads.append(workload)
        
        if is_detail:
            workloads = self._view_builder.detail_list(req, workloads)
        else:
            workloads = self._view_builder.summary_list(req, workloads)
        return workloads

        
    @wsgi.response(202)
    @wsgi.serializers(xml=WorkloadTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new workload."""
        try:
            if not self.is_valid_body(body, 'workload'):
                raise exc.HTTPBadRequest()
    
            context = req.environ['workloadmgr.context']
    
            try:
                workload = body['workload']
            except KeyError:
                msg = _("Incorrect request body format")
                raise exc.HTTPBadRequest(explanation=msg)
            name = workload.get('name', None)
            description = workload.get('description', None)
            workload_type_id = workload.get('workload_type_id', None)
            source_platform = workload.get('source_platform', "openstack")
            jobschedule = workload.get('jobschedule', {})
            if not jobschedule:
                jobschedule = {}
            instances = workload.get('instances', {})
            if not instances:
                instances = {}        
            metadata = workload.get('metadata', {}) 
            if not metadata:
                metadata = {}    
    
            try:
                new_workload = self.workload_api.workload_create(context, 
                                                                 name, 
                                                                 description,
                                                                 workload_type_id, 
                                                                 source_platform,
                                                                 instances,
                                                                 jobschedule,
                                                                 metadata)
                new_workload_dict = self.workload_api.workload_show(context, new_workload.id)
            except Exception as error:
                raise exc.HTTPServerError(explanation=unicode(error))
     
            retval = self._view_builder.summary(req, new_workload_dict)
            return retval
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

    @wsgi.response(202)
    @wsgi.serializers(xml=WorkloadTemplate)
    @wsgi.deserializers(xml=UpdateDeserializer)
    def update(self, req, id, body):
        """Update workload."""
        try:
            if not self.is_valid_body(body, 'workload'):
                raise exc.HTTPBadRequest()
    
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.workload_modify(context, id, body['workload'])
            except exception.WorkloadNotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
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
            

    def get_workflow(self, req, id):
        """Return workflow details of a given workload."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                workload_workflow = self.workload_api.workload_get_workflow(context, workload_id=id)
                return workload_workflow
            except exception.WorkloadNotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
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
    
    def pause(self, req, id):
        """pause a given workload."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.workload_pause(context, workload_id=id)
            except exception.WorkloadNotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
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
        

    def resume(self, req, id):
        """resume a given workload."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.workload_resume(context, workload_id=id)
            except exception.NotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
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
    
    def get_topology(self, req, id):
        """Return topology of a given workload."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                workload_topology = self.workload_api.workload_get_topology(context, workload_id=id)
                return workload_topology
            except exception.NotFound as error:
                raise exc.HTTPNotFound(explanation=unicode(error))
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

    def discover_instances(self, req, id):
        """discover_instances of a workload_type using the metadata"""
        try:
            context = req.environ['workloadmgr.context']
            instances = self.workload_api.workload_discover_instances(context, id)
            return instances
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

    def import_workloads(self, req):
        try:
            context = req.environ['workloadmgr.context']
            try:
                workloads = self.workload_api.import_workloads(context)
                return self._view_builder.detail_list(req, workloads)
            except exception.WorkloadNotFound as error:
                LOG.exception(error)
                raise exc.HTTPNotFound(explanation=unicode(error))
            except exception.InvalidState as error:
                LOG.exception(error)
                raise exc.HTTPBadRequest(explanation=unicode(error))
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
    
    def get_nodes(self, req):
        try:
            context = req.environ['workloadmgr.context']
            nodes = {'nodes':[]}
            try:
                nodes = self.workload_api.get_nodes(context)
            except Exception as ex:
                LOG.exception(ex)
            return nodes
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

    def remove_node(self, req, ip):
        try:
            context = req.environ['workloadmgr.context']
            try:
                self.workload_api.remove_node(context, ip)
            except Exception as ex:
                LOG.exception(ex)
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

    def add_node(self, req, body=None):
        try:
            context = req.environ['workloadmgr.context']
            if body:
               ip = body.get('ip')
            try:
                self.workload_api.add_node(context, ip)
            except Exception as ex:
                LOG.exception(ex)
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
    
    def get_storage_usage(self, req):
        try:
            context = req.environ['workloadmgr.context']
            storage_usage = {'total': 0, 'full': 0, 'incremental': 0}
            try:
                storage_usage = self.workload_api.get_storage_usage(context)
            except Exception as ex:
                LOG.exception(ex)
            return storage_usage
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
    
    def get_recentactivities(self, req):
        try:
            context = req.environ['workloadmgr.context']
            time_in_minutes = 600
            if ('QUERY_STRING' in req.environ) :
                qs=parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                time_in_minutes = var.get('time_in_minutes',[''])[0]
                time_in_minutes = int(escape(time_in_minutes))
            
            recentactivities = {'recentactivities':[]}
            try:
                recentactivities = self.workload_api.get_recentactivities(context, time_in_minutes)
            except Exception as ex:
                LOG.exception(ex)
            return recentactivities
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
    
    def get_auditlog(self, req):
        try:
            context = req.environ['workloadmgr.context']
            time_in_minutes = 1440
            time_from = None
            time_to = None
            if ('QUERY_STRING' in req.environ) :
                qs=parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                time_in_minutes = var.get('time_in_minutes', None)
                if time_in_minutes:
                    time_in_minutes = time_in_minutes[0]
                    time_in_minutes = int(escape(time_in_minutes))
                
                start_range = var.get('start_range',None)
                end_range = var.get('end_range',None)
                if start_range:
                    start_range = datetime.strptime(start_range[0] + " 00:00:00", "%m-%d-%Y  %H:%M:%S")
                if end_range:
                    end_range = datetime.strptime(end_range[0] + " 23:59:59", "%m-%d-%Y  %H:%M:%S")
                    
            auditlog = {'auditlog':[]}
            try:
                auditlog = self.workload_api.get_auditlog(context, time_in_minutes, start_range, end_range)
            except Exception as ex:
                LOG.exception(ex)
            return auditlog
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
        
    def settings(self, req, body=None):                           
        """settings"""
        try:
            context = req.environ['workloadmgr.context']
            Config = ConfigParser.RawConfigParser()
            Config.read('/opt/stack/data/wlm/settings/workloadmgr-settings.conf')
            
            settings = None            
            if (body and 'settings' in body):
                settings = settings_module.set_settings(context, body['settings'])
            if not settings:
                settings = settings_module.get_settings(context)
            return {'settings': settings}
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))
   
    def test_email(self, req):
        """Test email configuration"""
        try:

            context = req.environ['workloadmgr.context']        
            html = '<html><head></head><body>'
            html += 'Test email</body></html>'

            try:
                 msg = MIMEMultipart('alternative')
                 msg['From'] = settings_module.get_settings().get('smtp_default_sender')
                 if settings_module.get_settings().get('smtp_default_recipient') is None: 
                    msg['To'] = msg['From']
                 else:
                      msg['To'] =  settings_module.get_settings().get('smtp_default_recipient')
 
                 msg['Subject'] = 'Testing email configuration'
                 part2 = MIMEText(html, 'html')
                 msg.attach(part2)
                 s = smtplib.SMTP(settings_module.get_settings().get('smtp_server_name'),int(settings_module.get_settings().get('smtp_port')))
                 if settings_module.get_settings().get('smtp_server_name') != 'localhost':
                    s.ehlo()
                    s.starttls()
                    s.ehlo
                    s.login(settings_module.get_settings().get('smtp_server_username'),settings_module.get_settings().get('smtp_server_password'))
                 s.sendmail(msg['From'], msg['To'], msg.as_string())
                 s.quit()

            except Exception as error:
                   raise exception.ErrorOccurred("Not able to send email with this configuration")

        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

def create_resource():
    return wsgi.Resource(WorkloadMgrsController())

