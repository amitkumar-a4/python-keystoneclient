
from oslo.config import cfg

from nova.db import base
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
from nova.virt.vmwareapi import volumeops

LOG = logging.getLogger(__name__)

compute_opts = []
CONF = cfg.CONF
CONF.register_opts(compute_opts)
CONF.import_opt('compute_topic', 'nova.compute.rpcapi')
CONF.import_opt('enable', 'nova.cells.opts', group='cells')
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')


class VMwareAPI(base.Base):
    """API for interacting with vmware vcenter to discover top level abstracts"""

    def __init__(self, **kwargs):
        self.cm = driver.load_compute_driver(None, "vmwareapi.VMwareVCDriver")
        super(API, self).__init__(**kwargs)

    def get_datacenters(self):
        dcs = cm.list_datacenters()

        # get the datastores, hosts (clusters) and networks
        for dc in dcs:
            pass

    def get_clusters(self, datacenter=None):
        clusters = cm.list_clusters()

    def get_resourcepools(self, clustername=None):
        resourcepools = cm.list_resourcepools()

    def get_networks(self, datacenter=None):
        networks = cm.list_networks()

    def get_datastores(self, datacenter=None, clustername=None):
        datastores = cmd.list_datastores()


VMwareAPI()
