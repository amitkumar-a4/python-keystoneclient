from __future__ import print_function
import sys
import getopt
import socket
import itertools
import re
import json
from workloadmgr.triliopssh import ParallelSSHClient, AuthenticationException
from workloadmgr.triliopssh import UnknownHostException, ConnectionErrorException, SSHException
from workloadmgr.openstack.common import log as logging
from workloadmgr import autolog
from workloadmgr import exception
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import flags
from workloadmgr import settings

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)


@autolog.log_method(Logger)
def find_alive_nodes(defaultnode, SSHPort, Username, Password, addlnodes=None):
    # Iterate thru all hosts and identify the valid list of cassandra hosts
    # will start with last known hosts
    # the cassandra service need not be running. This routine
    # only identifies the nodes that are up and running and take
    # ssh session
    error_msg = 'Unknown Error'
    nodelist = []
    if not addlnodes or len(addlnodes) == 0:
        LOG.info(
            _("'addlnodes' is empty. Defaulting to defaultnode %s atribute") %
            defaultnode)
        if not defaultnode:
            raise exception.InvalidState(
                "Cassandra workload is in invalid state. Do not have any node information set")
        addlnodes = defaultnode

    try:
        nodes = addlnodes.split(";")
        if '' in nodes:
            nodes.remove('')
        output = pssh_exec_command(nodes,
                                   int(SSHPort),
                                   Username,
                                   Password,
                                   "nodetool status")
        nodelist = nodes
    except AuthenticationException as ex:
        raise
    except Exception as ex:
        error_msg = _("Failed to execute '%s' on host(s) '%s' with error: %s") % (
            'nodetool status', str(addlnodes), str(ex))
        LOG.info(error_msg)
        nodes = addlnodes.split(";")
        if '' in nodes:
            nodes.remove('')
        if defaultnode not in nodes:
            nodes.append(defaultnode)

        for host in nodes:
            try:
                LOG.info(_('Connecting to Cassandra node %s') % host)
                pssh_exec_command([host],
                                  int(SSHPort),
                                  Username,
                                  Password,
                                  "nodetool status")
                LOG.info(_("Selected '" + host + "' for Cassandra nodetool"))
                nodelist.append(host)
            except AuthenticationException as ex:
                error_msg = _("Failed to execute '%s' on host '%s' with error: %s") % (
                    'nodetool status', host, str(ex))
                raise exception.ErrorOccurred(reason=error_msg)
            except Exception as ex:
                error_msg = _("Failed to execute '%s' on host '%s' with error: %s") % (
                    'nodetool status', host, str(ex))
                LOG.info(error_msg)
                pass

    if len(nodelist) == 0:
        LOG.info(error_msg)
        raise Exception(error_msg)

    LOG.info(_("Seed nodes of the Cassandra cluster are '%s'") % str(nodelist))
    return nodelist


@autolog.log_method(Logger)
def pssh_exec_command(hosts, port, user, password, command, sudo=False):
    try:
        LOG.info(_("pssh_exec_command - hosts: %s") % (str(hosts)))
        timeout = settings.get_settings().get('cassandra_discovery_timeout', '120')
        client = ParallelSSHClient(
            hosts,
            user=user,
            password=password,
            port=int(port),
            timeout=int(timeout))
        LOG.info(_("pssh_exec_command: %s") % (command))
        output = client.run_command(command, sudo=sudo)
        # dump environment if any node fails with command not found
        for host in output:
            if output[host]['exit_code']:
                envoutput = client.run_command('env')
                LOG.info(_("Environment dump:"))
                for h in envoutput:
                    for line in envoutput[h]['stdout']:
                        LOG.info(_("[%s]: %s") % (h, line))

                break
        # Dump every command output here for diagnostics puposes
        for host in output:
            output[host]['stdout'], iter1 = itertools.tee(
                output[host]['stdout'])
            output_filtered = []
            for line in iter1:
                if password == line:
                    continue
                output_filtered.append(line)
                LOG.info(_("[%s]\t%s") % (host, line))
            output[host]['stdout'] = output_filtered

    except (AuthenticationException, UnknownHostException, ConnectionErrorException) as ex:
        LOG.exception(ex)
        raise Exception(str(ex))
    except Exception as ex:
        LOG.exception(ex)
        raise Exception(str(ex))

    return output


@autolog.log_method(Logger)
def getclusterinfo(hosts, port, username, password):
    output = pssh_exec_command(
        hosts,
        port,
        username,
        password,
        "nodetool describecluster")
    for host in output:
        if output[host]['exit_code']:
            LOG.info(_("'nodetool describecluster' on %s cannot be executed. Error %s" % (
                host, str(output[host]['exit_code']))))
            continue

        clusterinfo = {}
        for line in output[host]['stdout']:
            if len(line.split(":")) < 2:
                continue
            clusterinfo[line.split(":")[0].strip()] = line.split(":")[
                1].strip()

        return clusterinfo

    msg = _("Failed to execute 'nodetool describecluster' successfully.")
    LOG.error(msg)
    raise exception.ErrorOccurred(msg)


@autolog.log_method(Logger)
def discovercassandranodes(hosts, port, username, password):
    LOG.info(_('Enter discovercassandranodes'))

    # nodetool status Sample output
    # Datacenter: 17
    #==============
    # Status=Up/Down
    #|/ State=Normal/Leaving/Joining/Moving
    #--  Address      Load       Owns (effective)  Host ID                               Token                                    Rack
    # UN  172.17.17.2  55.56 KB   0.2%              7d62d900-f99d-4b88-8012-f06cb639fc02  0                                        17
    # UN  172.17.17.4  76.59 KB   100.0%            75917649-6caa-4c66-b003-71c0eb8c09e8  -9210152678340971410                     17
    # UN  172.17.17.5  86.46 KB   99.8%
    # a03a1287-7d32-42ed-9018-8206fc295dd9  -9218601096928798970
    # 17

    nodelist = []
    output = pssh_exec_command(
        hosts,
        port,
        username,
        password,
        "nodetool status")
    currentdc = ""
    for host in output:
        if output[host]['exit_code'] is not None and output[host]['exit_code'] != 0:
            LOG.info(_("'nodetool status' on %s cannot be executed. Error %s" % (
                host, str(output[host]['exit_code']))))
            continue

        for line in output[host]['stdout']:

            line = line.replace(" KB", "KB")
            line = line.replace(" MB", "MB")
            line = line.replace(" GB", "GB")
            line = line.replace(" (", "(")
            line = line.replace(" ID", "ID")

            if line.startswith("--"):
                casskeys = line.split()
                continue

            if line.startswith("Datacenter"):
                currentdc = line.split(':')[1].strip()
                continue

            desc = line.split()
            if len(desc) == 0:
                continue

            if not desc[0] in ("UN", "UL", "UJ", "UM", "DN", "DL", "DJ", "DM"):
                continue

            node = {}
            node['Data Center'] = currentdc
            for idx, k in enumerate(casskeys):
                node[k] = desc[idx]
            nodelist.append(node)

        break

    if len(nodelist) == 0:
        msg = _('Failed to connect to Cassandra cluster. Please check the status of the cluster and try the operation again')
        LOG.error(msg)
        raise exception.ErrorOccurred(msg)

    cassandranodes = []
    availablenodes = []
    # Put nodes that are marked down in the cassandra nodetool status
    # into list of cassandra nodes. Gather more information
    # on other nodes using 'nodetool info'
    for n in nodelist:
        if n['--'] in ("DN", "DL", "DJ", "DM"):
            LOG.info(_("'%s' is marked down") % n['Address'])
            cassandranodes.append(n)
        else:
            availablenodes.append(n['Address'])

        # Sample output
        # =============
        # Token            : (invoke with -T/--tokens to see all 256 tokens)
        # ID               : f64ced33-2c01-40a3-9979-cf0a0b60d7af
        # Gossip active    : true
        # Thrift active    : true
        # Native Transport active: true
        # Load             : 148.13 KB
        # Generation No    : 1399521595
        # Uptime (seconds) : 36394
        # Heap Memory (MB) : 78.66 / 992.00
        # Data Center      : 17
        # Rack             : 17
        # Exceptions       : 0
        # Key Cache        : size 1400 (bytes), capacity 51380224 (bytes), 96 hits, 114 requests, 0.842 recent hit rate, 14400 save period in seconds
        # Row Cache        : size 0 (bytes), capacity 0 (bytes), 0 hits, 0
        # requests, NaN recent hit rate, 0 save period in seconds

    output = pssh_exec_command(
        availablenodes,
        port,
        username,
        password,
        "nodetool info")
    for host in output:
        if output[host]['exit_code'] is not None and output[host]['exit_code'] != 0:
            LOG.info(
                _("Cannot execute 'nodetool info' on %s. Error: ") %
                (host))
            for line in output[host]['stdout']:
                LOG.info(_("%s") % (line))
            continue

        for node in nodelist:
            if node['Address'] == host:
                break

        for line in output[host]['stdout']:
            fields = line.split(":")
            if len(fields) > 1:
                node[fields[0].strip()] = fields[1].strip()
        cassandranodes.append(node)

    LOG.info(_('Discovered Cassandra Nodes: %s') % str(len(cassandranodes)))
    LOG.info(_('Discovered Cassandra Nodes: ' + str(cassandranodes)))
    LOG.info(_('Exit discovercassandranodes'))

    clusterinfo = getclusterinfo(hosts, port, username, password)

    return cassandranodes, clusterinfo


@autolog.log_method(Logger)
def get_cassandra_nodes(alivenodes, port, username, password,
                        preferredgroups=None, findpartitiontype=False):
    LOG.info(_('Enter get_cassandra_nodes'))
    try:
        #
        # Getting sharding information
        #
        allnodes, clusterinfo = discovercassandranodes(
            alivenodes, port, username, password)

        # filter out nodes that are not in preferred datacenter
        preferrednodes = []
        if preferredgroups and len(preferredgroups):
            datacenters = preferredgroups.split(';')
            datacenters.remove('')
            for dc in datacenters:
                for node in allnodes:
                    if dc == node['Data Center']:
                        preferrednodes.append(node)
                # temporarily we only consider the first group
                # we will figure out how to support second group
                # incase the first one is unavailable

            downnodes = 0
            for node in preferrednodes:
                if node['--'] in ("DN", "DL", "DJ", "DM"):
                    downnodes += 1

            # This one is under the assumption that all keyspaces have a replica factor of 2
            # or more. We need to automatically determine this later
            if downnodes > len(preferrednodes) / 2:
                raise exception.InvalidState(_("More than half the nodes are down in the Data Center %s. \
                                     Choose a new data center or fix the current data center before\
                                     doing backup") % dc)
        else:
            preferrednodes = allnodes

        #
        # Resolve the node name to VMs
        # Usually Hadoop spits out nodes IP addresses. These
        # IP addresses need to be resolved to VM IDs by
        # querying the VM objects from nova
        #
        ips = {}
        for node in preferrednodes:
            # if the node is host name, resolve it to IP address
            try:
                # Make sure the node address is an IP address
                IP(node['Address'])
                node['IPAddress'] = node['Address']
                if node['--'] not in ("DN", "DL", "DJ", "DM"):
                    ips[node['IPAddress']] = 1
            except Exception as e:
                # we got hostnames
                node['IPAddress'] = socket.gethostbyname(node['Address'])
                if node['--'] not in ("DN", "DL", "DJ", "DM"):
                    ips[node['IPAddress']] = 1

        output = pssh_exec_command(
            ips,
            port,
            username,
            password,
            "ifconfig | grep -o -E '([[:xdigit:]]{1,2}:){5}[[:xdigit:]]{1,2}'",
            sudo=True)
        for host in output:
            for line in output[host]['stdout']:
                LOG.info(_('%s') % line)
            if output[host]['exit_code']:
                LOG.info(_('ifconfig failed on host %s') % host)
                raise Exception(
                    _("ifconfig failed on host '%s' Error Code %s") %
                    (host, str(
                        output[host]['exit_code'])))
            MacAddresses = []
            for line in output[host]['stdout']:
                LOG.info(_('%s') % line)
                MacAddress = line.lower()
                LOG.info(
                    _("Found mac address %s on host %s") %
                    (MacAddress, host))
                MacAddresses.append(MacAddress)
            if len(MacAddresses) == 0:
                LOG.info(
                    _("Strange... No MAC addresses were detected on host %s") %
                    (host))
                raise Exception(
                    _("No MAC addresses were detected on host %s") %
                    (host))
            else:
                for node in preferrednodes:
                    if node['IPAddress'] == host:
                        node['MacAddresses'] = MacAddresses
                        break
        for node in preferrednodes:
            node['root_partition_type'] = "lvm"

        if findpartitiontype is True:
            try:
                output = pssh_exec_command(
                    ips, port, username, password, 'df /')
                for host in output:
                    if output[host]['exit_code']:
                        LOG.info(_('"df /" on host %s') % host)
                        for line in output[host]['stdout']:
                            LOG.info(_('%s') % line)

                        continue

                    for line in output[host]['stdout']:
                        try:
                            # find the type of the root partition
                            m = re.search(r'(/[^\s]+)\s', str(line))
                            if m:
                                mp = m.group(1)

                                lvoutput = pssh_exec_command(
                                    [host], port, username, password, "lvdisplay " + mp, sudo=True)
                                LOG.info(
                                    _('lvdisplay: return value %d') %
                                    lvoutput[host]['exit_code'])
                                LOG.info(_('lvdisplay: output\n'))
                                for l in lvoutput[host]['stdout']:
                                    # remove password from the stdout
                                    l.replace(password, '******')
                                    LOG.info(_(l))
                                for node in preferrednodes:
                                    if node['IPAddress'] == host:
                                        if lvoutput[host]['exit_code'] is None or lvoutput[host]['exit_code'] == 0:
                                            node['root_partition_type'] = "lvm"
                                        else:
                                            node['root_partition_type'] = "Linux"
                                        LOG.info(
                                            _('%s: root partition is %s') %
                                            (node['IPAddress'], node['root_partition_type']))
                                        break

                        except Exception as ex:
                            LOG.info(
                                _("Cannot execute lvdisplay command on %s") %
                                host)
                            LOG.exception(ex)
            except Exception as ex:
                LOG.info(_("Failed to find partition type on %s") % host)
                LOG.exception(ex)

        LOG.info(_('Preferred Cassandra Nodes: %s') % str(len(preferrednodes)))
        for node in preferrednodes:
            LOG.info(_(node))
        LOG.info(_('Exit get_cassandra_nodes'))

        return preferrednodes, allnodes, clusterinfo
    except Exception as ex:
        LOG.info(_("Unexpected Error in get_cassandra_nodes"))
        LOG.exception(ex)
        raise

#exec_cqlsh_command(['cass1'], 22, 'ubuntu', 'project1', 'SELECT * FROM system.schema_keyspaces where keyspace_name=\'"\'Keyspace1\'"\'')
# cmd += SELECT * FROM system.schema_keyspaces where
# keyspace_name=\'"\'Keyspace1\'"\';


@autolog.log_method(Logger)
def exec_cqlsh_command(hosts, port, user, password, cqlshcommand):
    cmd = 'bash -c \'echo "'
    cmd += cqlshcommand
    cmd += ';" > /tmp/tvault-keyspace ; cqlsh ' + \
        hosts[0] + ' -f /tmp/tvault-keyspace\''

    return pssh_exec_command(hosts, port, user, password, cmd)


@autolog.log_method(Logger)
def get_keyspaces(alivenodes, port, username, password):
    keyspaces = []
    for alive in alivenodes:
        output = exec_cqlsh_command(
            [alive],
            port,
            username,
            password,
            'SELECT * FROM system.schema_keyspaces')

        for host in output:
            if "Connection error" in output[host]['stdout'][0]:
                continue

            if len(output[host]['stdout']) < 5:
                continue

            output[host]['stdout'].pop(0)
            output[host]['stdout'].pop()
            output[host]['stdout'].pop()
            output[host]['stdout'].pop()

            fieldsout = output[host]['stdout'][0].split('|')

            fields = []
            for f in fieldsout:
                fields.append(f.strip())

            for ksidx, ks in enumerate(output[host]['stdout'][2:]):
                ksfieldsout = ks.split('|')

                ksdict = {}
                for idx, ksfield in enumerate(ksfieldsout):
                    ksdict[fields[idx]] = ksfield.strip()
                keyspaces.append(ksdict)

            tmp = keyspaces
            keyspaces = []
            for idx, key in enumerate(tmp):
                if key['keyspace_name'].lower() not in [
                        'system', 'system_traces', 'dse_system']:
                    keyspaces.append(key)

            return keyspaces

    return keyspaces


@autolog.log_method(Logger)
def main(argv):
    try:
        errfile = '/tmp/cassnodes_errors.txt'
        outfile = '/tmp/cassnodes_output.txt'
        addlnodes = None
        preferredgroups = None
        findpartitiontype = False

        opts, args = getopt.getopt(argv, "", ["defaultnode=", "port=", "username=", "password=",
                                              "addlnodes=", "preferredgroups=", "findpartitiontype=", "outfile=", "errfile="])
        for opt, arg in opts:
            if opt == '--defaultnode':
                defaultnode = arg
            elif opt == '--port':
                port = arg
            elif opt == '--username':
                username = arg
            elif opt == '--password':
                password = arg
            elif opt == '--addlnodes':
                addlnodes = arg
            elif opt == '--preferredgroups':
                preferredgroups = arg
            elif opt == '--findpartitiontype':
                findpartitiontype = (arg == 'True')
            elif opt == '--outfile':
                outfile = arg
            elif opt == '--errfile':
                errfile = arg

        with open(outfile, 'w') as outfilehandle:
            pass

        alivenodes = find_alive_nodes(
            defaultnode, port, username, password, addlnodes)
        cassandranodes, allnodes, clusterinfo = get_cassandra_nodes(alivenodes, port, username, password,
                                                                    preferredgroups=preferredgroups,
                                                                    findpartitiontype=findpartitiontype)

        clusterinfo['preferrednodes'] = cassandranodes
        clusterinfo['allnodes'] = allnodes
        clusterinfo['keyspaces'] = get_keyspaces(
            alivenodes, port, username, password)

        with open(outfile, 'w') as outfilehandle:
            outfilehandle.write(json.dumps(clusterinfo))

    except getopt.GetoptError as ex:
        LOG.exception(ex)
        usage = _(
            "Usage: cassnodes.py --config-file /etc/workloadmgr/workloadmgr.conf --defaultnode cassandra1 "
            "--port 22 --username ubuntu --password password "
            "--addlnodes 'cassandra1;cassandra2;cassandra3' --preferredgroups 'DC1;DC2' "
            "--findpartitiontype False --outfile /tmp/cassnodes.txt --outfile /tmp/cassnodes_errors.txt")
        LOG.info(usage)
        with open(errfile, 'w') as errfilehandle:
            errfilehandle.write(usage)
            errfilehandle.write(str(ex))
        exit(1)
    except Exception as ex:
        LOG.exception(ex)
        with open(errfile, 'w') as errfilehandle:
            errfilehandle.write(str(ex))
        exit(1)


if __name__ == "__main__":
    flags.parse_args(sys.argv[1:2])
    logging.setup("workloadmgr")
    LOG = logging.getLogger('workflows.cassnodes')
    Logger = autolog.Logger(LOG)
    main(sys.argv[3:])
