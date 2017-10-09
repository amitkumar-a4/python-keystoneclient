# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""The snapshots api."""

import webob
import datetime
from webob import exc
from xml.dom import minidom
from cgi import parse_qs, escape
from datetime import timedelta

from workloadmgr.api import common
from workloadmgr.api import wsgi
from workloadmgr.api import xmlutil
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common import strutils
from workloadmgr import utils
from workloadmgr import workloads as workloadAPI
from workloadmgr.api.views import snapshots as snapshot_views
from workloadmgr.api.views import restores as restore_views
from workloadmgr.api.views import testbubbles as testbubble_views

LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


def make_snapshot(elem):
    elem.set('id')
    elem.set('status')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')


class SnapshotTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshot', selector='snapshot')
        make_snapshot(root)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshots')
        elem = xmlutil.SubTemplateElement(root, 'snapshot',
                                          selector='snapshots')
        make_snapshot(elem)
        return xmlutil.MasterTemplate(root, 1)


def make_snapshot_restore(elem):
    elem.set('snapshot_id')


class SnapshotRestoreTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('restore', selector='restore')
        make_snapshot_restore(root)
        alias = Snapshots.alias
        namespace = Snapshots.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class RestoreDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        restore = self._extract_restore(dom)
        return {'body': {'restore': restore}}

    def _extract_restore(self, node):
        restore = {}
        restore_node = self.find_first_child_named(node, 'restore')
        if restore_node.getAttribute('snapshot_id'):
            restore['snapshot_id'] = restore_node.getAttribute('snapshot_id')
        return restore


class SnapshotsController(wsgi.Controller):
    """The snapshots API controller for the OpenStack API."""

    _view_builder_class = snapshot_views.ViewBuilder
    restore_view_builder = restore_views.ViewBuilder()
    testbubble_view_builder = testbubble_views.ViewBuilder()

    def __init__(self, ext_mgr=None):
        self.workload_api = workloadAPI.API()
        self.ext_mgr = ext_mgr
        super(SnapshotsController, self).__init__()

    @wsgi.serializers(xml=SnapshotTemplate)
    def show(self, req, id, workload_id=None):
        """Return data about the given Snapshot."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                snapshot = self.workload_api.snapshot_show(context, id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return self._view_builder.detail(req, snapshot)
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

    def delete(self, req, id, workload_id=None):
        """Delete a snapshot."""
        try:
            context = req.environ['workloadmgr.context']
            try:
                task_id = self.workload_api.snapshot_delete(context, id)
                return self._view_builder.task(req, task_id)
            except exception.NotFound:
                raise exc.HTTPNotFound()
            return webob.Response(status_int=202)
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

    @wsgi.serializers(xml=SnapshotsTemplate)
    def index(self, req):
        """Returns a summary list of snapshots."""
        try:
            return self._get_snapshots(req, is_detail=False)
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

    @wsgi.serializers(xml=SnapshotsTemplate)
    def detail(self, req):
        """Returns a detailed list of snapshots."""
        try:
            return self._get_snapshots(req, is_detail=True)
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

    def _get_snapshots(self, req, is_detail):
        """Returns a list of snapshots, transformed through view builder."""
        try:
            context = req.environ['workloadmgr.context']
            workload_id = req.GET.get('workload_id', None)
            host = req.GET.get('host', None)
            get_all = bool(req.GET.get('all', False))

            date_from = req.GET.get('date_from', None)
            date_to = req.GET.get('date_to', None)
            status = req.GET.get('status', None)
            get_instances = bool(req.GET.get('get_instances', False))

            # verify workload exists
            if workload_id:
                self.workload_api.workload_get(context, workload_id)

            search_opts = {'workload_id': workload_id,
                           'host': host, 'get_all': get_all,
                           'date_from': date_from, 'date_to': date_to, 'status': status,
                           'get_instances': get_instances}
            snapshots_all = self.workload_api.snapshot_get_all(
                context, search_opts)

            limited_list = common.limited(snapshots_all, req)

            if is_detail:
                snapshots = self._view_builder.detail_list(req, snapshots_all)
            else:
                snapshots = self._view_builder.summary_list(req, snapshots_all)
            return snapshots
        except Exception as ex:
            LOG.exception(ex)
            raise ex

    def _restore(self, context, id, workload_id=None, body=None, test=False):
        """Restore an existing snapshot"""
        try:
            name = ''
            description = ''
            if (body and 'testbubble' in body):
                name = body['testbubble'].get('name', None)
                description = body['testbubble'].get('description', None)
                options = body['testbubble'].get('options', {})
            elif (body and 'restore' in body):
                name = body['restore'].get('name', "") or 'restore'
                name = name.strip() or "restore"
                description = body['restore'].get(
                    'description', "") or 'no-description'
                description = description.strip() or "no-description"

                options = body['restore'].get('options', {})
            if not options:
                options = {'type': 'openstack'}
            restore = self.workload_api.snapshot_restore(context,
                                                         snapshot_id=id,
                                                         test=test,
                                                         name=name,
                                                         description=description,
                                                         options=options)
        except exception.InvalidInput as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.InvalidState as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.NotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        return restore

    @wsgi.response(202)
    @wsgi.serializers(xml=SnapshotRestoreTemplate)
    @wsgi.deserializers(xml=RestoreDeserializer)
    def restore(self, req, id, workload_id=None, body=None):
        try:
            test = None
            if ('QUERY_STRING' in req.environ):
                qs = parse_qs(req.environ['QUERY_STRING'])
                var = parse_qs(req.environ['QUERY_STRING'])
                test = var.get('test', [''])[0]
                test = escape(test)
            if(test and test == '1'):
                test = True
            else:
                test = False
            context = req.environ['workloadmgr.context']
            restore = self._restore(context, id, workload_id, body, test)
            return self.restore_view_builder.detail(
                req, dict(restore.iteritems()))
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
    @wsgi.serializers(xml=SnapshotRestoreTemplate)
    @wsgi.deserializers(xml=RestoreDeserializer)
    def test_restore(self, req, id, workload_id=None, body=None):
        try:
            context = req.environ['workloadmgr.context']
            test_restore = self._restore(
                context, id, workload_id, body, test=True)
            return self.testbubble_view_builder.detail(
                req, dict(test_restore.iteritems()))
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

    def mount(self, req, id, workload_id=None, body=None):
        try:
            context = req.environ['workloadmgr.context']
            mount_vm_id = None
            if 'mount_vm_id' in body['mount']:
                mount_vm_id = body['mount']['mount_vm_id']
            mounturl = self.workload_api.snapshot_mount(
                context, id, mount_vm_id)
            return mounturl
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

    def mounted_list(self, req, workload_id=None):
        try:
            context = req.environ['workloadmgr.context']
            return self.workload_api.mounted_list(context, workload_id)
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

    def snapshot_cancel(self, req, id):
        """cancel snapshot"""
        try:
            context = req.environ['workloadmgr.context']
            self.workload_api.snapshot_cancel(context, id)
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

    def dismount(self, req, id, workload_id=None, body=None):
        try:
            context = req.environ['workloadmgr.context']
            self.workload_api.snapshot_dismount(context, id)
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
    return wsgi.Resource(SnapshotsController(ext_mgr))
