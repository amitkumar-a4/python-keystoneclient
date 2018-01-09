# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from oslo_log import log as logging
import webob
from webob import exc

from workloadmgr.api import common
from workloadmgr.api import extensions
from workloadmgr.api import wsgi
from workloadmgr.api.views import transfers as transfer_view
from workloadmgr.api import xmlutil
from workloadmgr import exception
from workloadmgr.common.i18n import _, _LI
from workloadmgr import transfer as transferAPI
from workloadmgr import utils

LOG = logging.getLogger(__name__)


def make_transfer(elem):
    elem.set('id')
    elem.set('workload_id')
    elem.set('created_at')
    elem.set('name')
    elem.set('auth_key')


class TransferTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('transfer', selector='transfer')
        make_transfer(root)
        alias = Workloadmgr_transfer.alias
        namespace = Workloadmgr_transfer.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class TransfersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('transfers')
        elem = xmlutil.SubTemplateElement(root, 'transfer',
                                          selector='transfers')
        make_transfer(elem)
        alias = Workloadmgr_transfer.alias
        namespace = Workloadmgr_transfer.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        transfer = self._extract_transfer(dom)
        return {'body': {'transfer': transfer}}

    def _extract_transfer(self, node):
        transfer = {}
        transfer_node = self.find_first_child_named(node, 'transfer')

        attributes = ['workload_id', 'name']

        for attr in attributes:
            if transfer_node.getAttribute(attr):
                transfer[attr] = transfer_node.getAttribute(attr)
        return transfer


class AcceptDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        transfer = self._extract_transfer(dom)
        return {'body': {'accept': transfer}}

    def _extract_transfer(self, node):
        transfer = {}
        transfer_node = self.find_first_child_named(node, 'accept')

        attributes = ['auth_key']

        for attr in attributes:
            if transfer_node.getAttribute(attr):
                transfer[attr] = transfer_node.getAttribute(attr)
        return transfer


class WorkloadmgrTransferController(wsgi.Controller):
    """The Workloadmgr Transfer API controller for the OpenStack API."""

    _view_builder_class = transfer_view.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.transfer_api = transferAPI.API()
        self.ext_mgr = ext_mgr
        super(WorkloadmgrTransferController, self).__init__()

    @wsgi.serializers(xml=TransferTemplate)
    def show(self, req, id):
        """Return data about active transfers."""
        context = req.environ['workloadmgr.context']

        try:
            transfer = self.transfer_api.get(context, transfer_id=id)
        except exception.TransferNotFound as error:
            raise exc.HTTPNotFound(explanation=error.message)

        return self._view_builder.detail(req, transfer)

    @wsgi.serializers(xml=TransfersTemplate)
    def index(self, req):
        """Returns a summary list of transfers."""
        return self._get_transfers(req, is_detail=False)

    @wsgi.serializers(xml=TransfersTemplate)
    def detail(self, req):
        """Returns a detailed list of transfers."""
        return self._get_transfers(req, is_detail=True)

    def _get_transfers(self, req, is_detail):
        """Returns a list of transfers, transformed through view builder."""
        context = req.environ['workloadmgr.context']
        filters = req.params.copy()
        LOG.debug('Listing workload transfers')
        transfers = self.transfer_api.get_all(context, filters=filters)
        transfer_count = len(transfers)
        limited_list = common.limited(transfers, req)

        if is_detail:
            transfers = self._view_builder.detail_list(req, limited_list,
                                                       transfer_count)
        else:
            transfers = self._view_builder.summary_list(req, limited_list,
                                                        transfer_count)

        return transfers

    @wsgi.response(202)
    @wsgi.serializers(xml=TransferTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new workload transfer."""
        LOG.debug('Creating new workload transfer %s', body)
        if not self.is_valid_body(body, 'transfer'):
            raise exc.HTTPBadRequest()

        context = req.environ['workloadmgr.context']

        try:
            transfer = body['transfer']
            workload_id = transfer['workload_id']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)

        name = transfer.get('name', None)

        LOG.info(_LI("Creating transfer of workload %s"),
                 workload_id,
                 context=context)

        try:
            new_transfer = self.transfer_api.create(context, workload_id, name)
        except exception.InvalidWorkload as error:
            raise exc.HTTPBadRequest(explanation=error.message)
        except exception.WorkloadNotFound as error:
            raise exc.HTTPNotFound(explanation=error.message)

        transfer = self._view_builder.create(req,
                                             dict(new_transfer.iteritems()))
        return transfer

    @wsgi.response(202)
    @wsgi.serializers(xml=TransferTemplate)
    @wsgi.deserializers(xml=AcceptDeserializer)
    def accept(self, req, id, body):
        """Accept a new workload transfer."""
        transfer_id = id
        LOG.debug('Accepting workload transfer %s', transfer_id)
        if not self.is_valid_body(body, 'accept'):
            raise exc.HTTPBadRequest()

        context = req.environ['workloadmgr.context']

        try:
            accept = body['accept']
            auth_key = accept['auth_key']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)

        LOG.info(_LI("Accepting transfer %s"), transfer_id,
                 context=context)

        try:
            accepted_transfer = self.transfer_api.accept(context, transfer_id,
                                                         auth_key)
        except exception.InvalidWorkload as error:
            raise exc.HTTPBadRequest(explanation=str(error))
        except exception.InvalidState as error:
            raise exc.HTTPBadRequest(explanation=str(error))

        transfer = \
            self._view_builder.summary(req,
                                       dict(accepted_transfer.iteritems()))
        return transfer

    @wsgi.response(202)
    def complete(self, req, id):
        """Complete a new workload transfer."""
        transfer_id = id
        LOG.debug('Completing workload transfer %s', transfer_id)

        context = req.environ['workloadmgr.context']

        LOG.info(_LI("Completing transfer %s"), transfer_id,
                 context=context)

        try:
            self.transfer_api.complete(context, transfer_id)
        except exception.InvalidWorkload as error:
            raise exc.HTTPBadRequest(explanation=str(error))
        except exception.InvalidState as error:
            raise exc.HTTPBadRequest(explanation=str(error))

    def delete(self, req, id):
        """Delete a transfer."""
        context = req.environ['workloadmgr.context']

        LOG.info(_LI("Delete transfer with id: %s"), id, context=context)

        try:
            self.transfer_api.delete(context, transfer_id=id)
        except exception.TransferNotFound as error:
            raise exc.HTTPNotFound(explanation=error.message)
        return webob.Response(status_int=202)


class Workload_transfer(extensions.ExtensionDescriptor):
    """Workload transfer management support."""

    name = "WorkloadTransfer"
    alias = "os-workload-transfer"
    namespace = "http://docs.triliodata.com/workload/ext/workload-transfer/" + \
                "api/v1.1"
    updated = "2013-05-29T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(Workload_transfer.alias,
                                           WorkloadTransferController(),
                                           collection_actions={'detail':
                                                               'GET'},
                                           member_actions={'accept': 'POST'})
        resources.append(res)
        return resources


def create_resource(ext_mgr):
    return wsgi.Resource(WorkloadmgrTransferController(ext_mgr))
