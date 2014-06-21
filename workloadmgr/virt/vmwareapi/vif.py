# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


"""VIF drivers for VMware."""

from oslo.config import cfg

from workloadmgr import exception
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr.openstack.common import log as logging
from workloadmgr.virt.vmwareapi import error_util
from workloadmgr.virt.vmwareapi import network_util
from workloadmgr.virt.vmwareapi import vim_util
from workloadmgr.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

vmwareapi_vif_opts = [
    cfg.StrOpt('vlan_interface',
               default='vmnic0',
               deprecated_name='vmwareapi_vlan_interface',
               deprecated_group='DEFAULT',
               help='Physical ethernet adapter name for vlan networking'),
]

CONF.register_opts(vmwareapi_vif_opts, 'vmware')


def _get_associated_vswitch_for_interface(session, interface, cluster=None):
    # Check if the physical network adapter exists on the host.
    if not network_util.check_if_vlan_interface_exists(session,
                                        interface, cluster):
        raise exception.NetworkAdapterNotFound(adapter=interface)
    # Get the vSwitch associated with the Physical Adapter
    vswitch_associated = network_util.get_vswitch_for_vlan_interface(
                                    session, interface, cluster)
    if not vswitch_associated:
        raise exception.SwitchNotFoundForNetworkAdapter(adapter=interface)
    return vswitch_associated


def ensure_vlan_bridge(session, vif, cluster=None, create_vlan=True):
    """Create a vlan and bridge unless they already exist."""
    vlan_num = vif['network'].get_meta('vlan')
    bridge = vif['network']['bridge']
    vlan_interface = CONF.vmware.vlan_interface

    network_ref = network_util.get_network_with_the_name(session, bridge,
                                                         cluster)
    if network_ref and network_ref['type'] == 'DistributedVirtualPortgroup':
        return network_ref

    if not network_ref:
        # Create a port group on the vSwitch associated with the
        # vlan_interface corresponding physical network adapter on the ESX
        # host.
        vswitch_associated = _get_associated_vswitch_for_interface(session,
                                 vlan_interface, cluster)
        network_util.create_port_group(session, bridge,
                                       vswitch_associated,
                                       vlan_num if create_vlan else 0,
                                       cluster)
        network_ref = network_util.get_network_with_the_name(session,
                                                             bridge,
                                                             cluster)
    elif create_vlan:
        # Get the vSwitch associated with the Physical Adapter
        vswitch_associated = _get_associated_vswitch_for_interface(session,
                                 vlan_interface, cluster)
        # Get the vlan id and vswitch corresponding to the port group
        _get_pg_info = network_util.get_vlanid_and_vswitch_for_portgroup
        pg_vlanid, pg_vswitch = _get_pg_info(session, bridge, cluster)

        # Check if the vswitch associated is proper
        if pg_vswitch != vswitch_associated:
            raise exception.InvalidVLANPortGroup(
                bridge=bridge, expected=vswitch_associated,
                actual=pg_vswitch)

        # Check if the vlan id is proper for the port group
        if pg_vlanid != vlan_num:
            raise exception.InvalidVLANTag(bridge=bridge, tag=vlan_num,
                                       pgroup=pg_vlanid)
    return network_ref


def _is_valid_opaque_network_id(opaque_id, bridge_id, integration_bridge,
                                num_networks):
    return (opaque_id == bridge_id or
            (num_networks == 1 and
             opaque_id == integration_bridge))


def _get_network_ref_from_opaque(opaque_networks, integration_bridge, bridge):
    num_networks = len(opaque_networks)
    for network in opaque_networks:
        if _is_valid_opaque_network_id(network['opaqueNetworkId'], bridge,
                                       integration_bridge, num_networks):
            return {'type': 'OpaqueNetwork',
                    'network-id': network['opaqueNetworkId'],
                    'network-name': network['opaqueNetworkName'],
                    'network-type': network['opaqueNetworkType']}
    LOG.warning(_("No valid network found in %(opaque)s, from %(bridge)s "
                  "or %(integration_bridge)s"),
                {'opaque': opaque_networks, 'bridge': bridge,
                 'integration_bridge': integration_bridge})


def get_neutron_network(session, network_name, cluster, vif):
    host = vm_util.get_host_ref(session, cluster)
    try:
        opaque = session._call_method(vim_util, "get_dynamic_property", host,
                                      "HostSystem",
                                      "config.network.opaqueNetwork")
    except error_util.VimFaultException:
        opaque = None
    if opaque:
        bridge = vif['network']['id']
        opaque_networks = opaque.HostOpaqueNetworkInfo
        network_ref = _get_network_ref_from_opaque(opaque_networks,
                CONF.vmware.integration_bridge, bridge)
    else:
        bridge = network_name
        network_ref = network_util.get_network_with_the_name(
                session, network_name, cluster)
    if not network_ref:
        raise exception.NetworkNotFoundForBridge(bridge=bridge)
    return network_ref


def get_network_ref(session, cluster, vif, is_neutron):
    if is_neutron:
        network_name = (vif['network']['bridge'] or
                        CONF.vmware.integration_bridge)
        network_ref = get_neutron_network(session, network_name, cluster, vif)
    else:
        create_vlan = vif['network'].get_meta('should_create_vlan', False)
        network_ref = ensure_vlan_bridge(session, vif, cluster=cluster,
                                         create_vlan=create_vlan)
    return network_ref
