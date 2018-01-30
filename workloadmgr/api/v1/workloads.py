# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The workloads api."""

import os
import json
import time
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
from workloadmgr import exception as wlm_exceptions

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import socket

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
        elem = xmlutil.SubTemplateElement(
            root, 'workload', selector='workloads')
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
            database_only = False
            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                database_only = qs.get('database_only', [''])[0]
                database_only = escape(database_only)
                if database_only.lower() == 'true':
                    database_only = True

            self.workload_api.workload_delete(context, id, database_only)
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

    def reset(self, req, id):
        try:
            context = req.environ['workloadmgr.context']
            self.workload_api.workload_reset(context, id)
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
            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                full = var.get('full', [''])[0]
                full = escape(full)

            snapshot_type = 'incremental'
            if (full and full == '1'):
                snapshot_type = 'full'
            if (body and 'snapshot' in body):

                name = body['snapshot'].get('name', "") or 'Snapshot'
                name = name.strip() or 'Snapshot'
                description = body['snapshot'].get(
                    'description', "") or 'no-description'
                description = description.strip() or 'no-description'

                snapshot_type = body['snapshot'].get(
                    'snapshot_type', snapshot_type)
            new_snapshot = self.workload_api.workload_snapshot(
                context, id, snapshot_type, name, description)
            return self.snapshot_view_builder.summary(
                req, dict(new_snapshot.iteritems()))
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
        try:
            context = req.environ['workloadmgr.context']
            all_workloads = None
            # Get value of query parameter 'all_workloads'
            page_number = None
            nfs_share = None
            project_id = None
            if ('QUERY_STRING' in req.environ):
                var = parse_qs(req.environ['QUERY_STRING'])
                all_workloads = var.get('all_workloads', [''])[0]
                all_workloads = bool(escape(all_workloads))
                page_number = var.get('page_number', [''])[0]
                nfs_share = var.get('nfs_share', [''])[0]
                project_id = var.get('project_id', [''])[0]
            workloads_all = self.workload_api.workload_get_all(
                context,
                search_opts={
                    'page_number': page_number,
                    'nfs_share': nfs_share,
                    'all_workloads': all_workloads,
                    'project_id': project_id})
            limited_list = common.limited(workloads_all, req)
            if is_detail:
                workloads = self._view_builder.detail_list(
                    req, workloads_all, self.workload_api)
            else:
                workloads = self._view_builder.summary_list(req, workloads_all)
            return workloads
        except exception.WorkloadNotFound as error:
            LOG.exception(error)
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

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

            name = workload.get('name', "") or 'workload'
            name = name.strip() or "workload"
            description = workload.get('description', "") or 'no-description'
            description = description.strip() or "no-description"

            workload_type_id = workload.get('workload_type_id', None)
            source_platform = workload.get(
                'source_platform', "") or 'openstack'
            source_platform = source_platform.strip() or "openstack"

            metadata = workload.get('metadata', {})
            if not metadata:
                metadata = {}

            assignments = self.workload_api.get_assigned_policies(
                context, context.project_id)
            available_policies = [
                assignment.policy_id for assignment in assignments]
            policy_id = metadata.get('policy_id', None)

            if policy_id is None and len(available_policies) > 0:
                message = "Please provide policy id from available policies: %s" % (
                    str(available_policies))
                raise exception.ErrorOccurred(message)

            jobdefaults = {
                'fullbackup_interval': '-1',
                'start_time': '09:00 PM',
                'interval': u'24hr',
                'enabled': u'true',
                'start_date': time.strftime("%m/%d/%Y"),
                'end_date': "No End",
                'retention_policy_type': 'Number of Snapshots to Keep',
                'retention_policy_value': '30'}

            jobschedule = workload.get('jobschedule', jobdefaults)
            if not jobschedule:
                jobschedule = {}

            if 'fullbackup_interval' not in jobschedule:
                jobschedule['fullbackup_interval'] = jobdefaults['fullbackup_interval']

            if 'start_time' not in jobschedule:
                jobschedule['start_time'] = jobdefaults['start_time']

            if 'interval' not in jobschedule:
                jobschedule['interval'] = jobdefaults['interval']

            if 'enabled' not in jobschedule:
                jobschedule['enabled'] = jobdefaults['enabled']

            if 'start_date' not in jobschedule:
                jobschedule['start_date'] = jobdefaults['start_date']

            if 'retention_policy_type' not in jobschedule:
                jobschedule['retention_policy_type'] = jobdefaults['retention_policy_type']

            if 'retention_policy_value' not in jobschedule:
                jobschedule['retention_policy_value'] = jobdefaults['retention_policy_value']

            instances = workload.get('instances', {})
            if not instances:
                instances = {}

            try:
                new_workload = self.workload_api.workload_create(
                    context,
                    name,
                    description,
                    workload_type_id,
                    source_platform,
                    instances,
                    jobschedule,
                    metadata)
                new_workload_dict = self.workload_api.workload_show(
                    context, new_workload.id)
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
                try:
                    workload = body['workload']
                except KeyError:
                    msg = _("Incorrect request body format")
                    raise exc.HTTPBadRequest(explanation=msg)

                jobdefaults = {
                    'fullbackup_interval': '-1',
                    'start_time': '09:00 PM',
                    'interval': u'24hr',
                    'enabled': u'true',
                    'start_date': time.strftime("%x"),
                    'end_date': "No End",
                    'retention_policy_type': 'Number of Snapshots to Keep',
                    'retention_policy_value': '30'}

                jobschedule = workload.get('jobschedule', jobdefaults)
                self.workload_api.workload_modify(
                    context, id, body['workload'])
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
                workload_workflow = self.workload_api.workload_get_workflow(
                    context, workload_id=id)
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
                workload_topology = self.workload_api.workload_get_topology(
                    context, workload_id=id)
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
            instances = self.workload_api.workload_discover_instances(
                context, id)
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

    def get_import_workloads_list(self, req):
        try:
            context = req.environ['workloadmgr.context']
            try:
                workloads = self.workload_api.get_import_workloads_list(
                    context)
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

    def import_workloads(self, req, body={}):
        try:
            context = req.environ['workloadmgr.context']
            workload_ids = []
            try:
                workload_ids = body['workload_ids']
            except KeyError:
                pass

            upgrade = True
            try:
                upgrade = body.get('upgrade')
            except KeyError:
                pass

            try:
                workloads = self.workload_api.import_workloads(
                    context, workload_ids, upgrade)

                imported_workloads = self._view_builder.detail_list(
                    req, workloads['workloads']['imported_workloads'])
                workloads['workloads']['imported_workloads'] = imported_workloads['workloads']
                return workloads
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
            nodes = {'nodes': []}
            try:
                nodes = self.workload_api.get_nodes(context)
            except Exception as ex:
                LOG.exception(ex)
                raise ex
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
                raise ex
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
                raise ex
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
            storages_usage = {'storage_usage': [
                {'total': 0, 'full': 0, 'incremental': 0}]}
            try:
                storages_usage = self.workload_api.get_storage_usage(context)
            except Exception as ex:
                LOG.exception(ex)
                raise ex
            return storages_usage
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

    def get_contego_status(self, req):
        try:
            context = req.environ['workloadmgr.context']
            host, ip = None, None

            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                host = qs.get('host', [''])[0]
                host = str(escape(host))

            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                ip = qs.get('ip', [''])[0]
                ip = str(escape(ip))

            compute_contego_records = {}
            try:
                compute_contego_records = self.workload_api.get_contego_status(
                    context, host, ip)
            except Exception as ex:
                LOG.exception(ex)
                raise ex
            return compute_contego_records
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
            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                time_in_minutes = var.get('time_in_minutes', [''])[0]
                time_in_minutes = int(escape(time_in_minutes))

            recentactivities = {'recentactivities': []}
            try:
                recentactivities = self.workload_api.get_recentactivities(
                    context, time_in_minutes)
            except Exception as ex:
                LOG.exception(ex)
                raise ex
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
            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                time_in_minutes = var.get('time_in_minutes', None)
                if time_in_minutes:
                    time_in_minutes = time_in_minutes[0]
                    time_in_minutes = int(escape(time_in_minutes))

                start_range = var.get('start_range', None)
                end_range = var.get('end_range', None)
                if start_range:
                    start_range = datetime.strptime(
                        start_range[0] + " 00:00:00", "%m-%d-%Y  %H:%M:%S")
                if end_range:
                    end_range = datetime.strptime(
                        end_range[0] + " 23:59:59", "%m-%d-%Y  %H:%M:%S")

            auditlog = {'auditlog': []}
            try:
                auditlog = self.workload_api.get_auditlog(
                    context, time_in_minutes, start_range, end_range)
            except Exception as ex:
                LOG.exception(ex)
                raise ex
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
            get_hidden = False
            get_smtp_settings = False
            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                get_hidden = var.get('get_hidden', [''])[0]
                get_hidden = escape(get_hidden)
                if get_hidden.lower() == 'true':
                    get_hidden = True
                get_smtp_settings = var.get('get_smtp_settings', [''])[0]
                get_smtp_settings = escape(get_smtp_settings)
                if get_smtp_settings.lower() == 'true':
                    get_smtp_settings = True
            Config = ConfigParser.RawConfigParser()
            Config.read('/var/triliovault/settings/workloadmgr-settings.conf')
            settings = None
            if (body and 'settings' in body):
                settings = settings_module.set_settings(
                    context, body['settings'])
            if (body and 'page_size' in body['settings']):
                settings = self.workload_api.setting_get(context, 'page_size')
            if not settings:
                settings = settings_module.get_settings(
                    context, get_hidden, get_smtp_settings)
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
                settings = settings_module.get_settings(context)
                import re
                found_smtp_settings = False
                for setting in settings:
                    if setting.strip().find('smtp_') >= 0:
                        found_smtp_settings = True
                        value = settings_module.get_settings(
                            context).get(setting)
                        if (value == "" or len(value) <=
                                1) and setting != 'smtp_email_enable':
                            if settings_module.get_settings(context).get('smtp_server_name') == 'localhost' and (
                                    setting == 'smtp_server_password' or setting == 'smtp_server_username'):
                                continue
                            else:
                                raise exception.ErrorOccurred(
                                    "Mandatory field " + setting + " cannot be empty")
                        elif (setting == 'smtp_default_sender' or setting == 'smtp_default_recipient') and not re.search(r'[\w.-]+@[\w.-]+.\w+', value):
                            raise exception.ErrorOccurred(
                                "Please enter valid email address for " + setting)
                        elif setting == 'smtp_timeout' and int(value) > 10:
                            raise exception.ErrorOccurred(
                                setting + " cannot be greater than 10")

                if found_smtp_settings is not True:
                   raise exception.ErrorOccurred("No Email settings found. Save them first.")

                msg = MIMEMultipart('alternative')
                msg['From'] = settings_module.get_settings(
                    context).get('smtp_default_sender')
                if settings_module.get_settings(context).get(
                        'smtp_default_recipient') is None:
                    msg['To'] = msg['From']
                else:
                    msg['To'] = settings_module.get_settings(
                        context).get('smtp_default_recipient')

                msg['Subject'] = 'Testing email configuration'
                part2 = MIMEText(html, 'html')
                msg.attach(part2)
                try:
                    socket.setdefaulttimeout(
                        int(settings_module.get_settings(context).get('smtp_timeout')))
                    s = smtplib.SMTP(
                        settings_module.get_settings(context).get('smtp_server_name'), int(
                            settings_module.get_settings(context).get('smtp_port')))
                    if settings_module.get_settings(context).get(
                            'smtp_server_name') != 'localhost':
                        s.ehlo()
                        s.starttls()
                        s.ehlo
                        s.login(
                            str(settings_module.get_settings(
                                context).get('smtp_server_username')),
                            str(settings_module.get_settings(context).get('smtp_server_password')))
                    s.sendmail(msg['From'], msg['To'], msg.as_string())
                    s.quit()
                except smtplib.SMTPException as ex:
                    if getattr(ex, 'smtp_code', 0)  == 535:
                        msg = ex.smtp_error
                    else:
                        msg = "Error authenticating with given email settings."
                    raise exception.ErrorOccurred(msg)
            except Exception as error:
                msg = error
                try:
                    if hasattr(error, 'message') and error.message[0] == -5:
                        msg = 'smtp_server_name is not valid'
                    if hasattr(error, 'message') and error.message.__class__.__name__ == 'timeout':
                        msg = 'smtp server unreachable with this smtp_server_name and smtp_port values'
                    if hasattr(error, 'strerror') and error.strerror != '':
                        msg = error.strerror
                    if 'reason' in error.message:
                        msg = error.args[0]
                except Exception as ex:
                    msg = "Error validation email settings"
                raise exception.ErrorOccurred(msg)
        except exception.InvalidState as error:
            LOG.exception(error)
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except Exception as error:
            LOG.exception(error)
            raise exc.HTTPServerError(explanation=unicode(error))

    def license_create(self, req, body):
        """Create a new license. Clobbers old license"""
        try:
            context = req.environ['workloadmgr.context']

            license_data = body['license']
            license = self.workload_api.license_create(context, license_data)
            return {'license': license}
        except exc.HTTPNotFound as error:
            raise error
        except exc.HTTPBadRequest as error:
            raise error
        except exc.HTTPServerError as error:
            raise error
        except Exception as error:
            raise exc.HTTPServerError(explanation=unicode(error))

    def license_list(self, req):
        """Returns license."""
        try:
            context = req.environ['workloadmgr.context']
            license = self.workload_api.license_list(context)
            return {'license': license}

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

    def license_check(self, req):
        """Verify license check."""
        try:
            context = req.environ['workloadmgr.context']
            message = self.workload_api.license_check(context)
            return {'message': message}
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

    def get_orphaned_workloads_list(self, req, path_info=None):
        try:
            context = req.environ['workloadmgr.context']
            qs = parse_qs(req.environ['QUERY_STRING'])
            migrate = qs.get('migrate_cloud')[0]
            if migrate == 'True' or migrate == 'true':
                migrate_cloud = True
            else:
                migrate_cloud = False
            try:
                workloads = self.workload_api.get_orphaned_workloads_list(
                    context, migrate_cloud)
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

    def workloads_reassign(self, req, body=[]):
        try:
            context = req.environ['workloadmgr.context']
            tenant_maps = body
            for tenant_map in tenant_maps:
                workload_ids = tenant_map['workload_ids']
                old_tenant_ids = tenant_map['old_tenant_ids']
                new_tenant_id = tenant_map['new_tenant_id']
                user_id = tenant_map['user_id']
                if workload_ids and old_tenant_ids:
                    raise exc.HTTPBadRequest(
                        explanation=unicode(
                            "Please provide "
                            "only one parameter among workload_ids and old_tenant_ids."))
                if new_tenant_id is None:
                    raise exc.HTTPBadRequest(
                        explanation=unicode(
                            "Please provide "
                            "required parameters: new_tenant_id."))
                if user_id is None:
                    raise exc.HTTPBadRequest(
                        explanation=unicode(
                            "Please provide "
                            "required parameters: user_id."))
            try:
                workloads = self.workload_api.workloads_reassign(
                    context, tenant_maps)
                reassigned_workloads = self._view_builder.detail_list(
                    req, workloads['workloads']['reassigned_workloads'])
                workloads['workloads']['reassigned_workloads'] = reassigned_workloads['workloads']
                return workloads
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

    def get_tenants_usage(self, req):
        try:
            context = req.environ['workloadmgr.context']
            try:
                tenants_usage = self.workload_api.get_tenants_usage(context)
                return tenants_usage
            except Exception as ex:
                LOG.exception(ex)
                raise ex
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

    def get_protected_vms(self, req):
        try:
            context = req.environ['workloadmgr.context']
            try:
                protected_vms = self.workload_api.workload_vms_get_all(context)
                return protected_vms
            except Exception as ex:
                LOG.exception(ex)
                raise ex
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


def create_resource():
    return wsgi.Resource(WorkloadMgrsController())
