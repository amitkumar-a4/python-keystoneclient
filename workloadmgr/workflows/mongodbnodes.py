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

import pymongo
from pymongo import MongoClient
from pymongo import MongoReplicaSetClient

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

#


def connect_server(host, port, user, password, verbose=False):
    try:
        connection = None
        if user != '':
            auth = 'mongodb://' + user + ':' + \
                password + '@' + host + ':' + str(port)
            connection = MongoClient(auth)
        else:
            auth = ''
            connection = MongoClient(host, int(port))

        if verbose:
            LOG.debug(_('Connected to ' + host + ' on port ' + port + '...'))

    except Exception as e:
        LOG.error(_('Oops!  There was an error.  Try again...'))
        LOG.error(_(e))
        raise e
    return connection


def isShardedCluster(conn):
    status = conn.admin.command("ismaster")
    return not ('primary' in status and 'secondary' in status)


@autolog.log_method(Logger)
def find_alive_nodes(defaultnode, SSHPort, Username,
                     Password, DBPort, addlnodes=None):
    # Iterate thru all hosts and identify the valid list of mongodb hosts
    # will start with last known hosts
    # the mongo service need not be running. This routine
    # only identifies the nodes that are up and running and take
    # ssh session
    error_msg = 'Unknown Error'
    nodelist = []
    if addlnodes:
        addlnodes = defaultnode + ";" + addlnodes
    else:
        addlnodes = defaultnode + ";"

    try:
        nodes = addlnodes.split(";")
        if '' in nodes:
            nodes.remove('')
        s = set(nodes)
        nodes = list(s)
        cmd = 'mongo --port ' + DBPort
        if dbuser is not '':
            cmd += " -u " + dbuser + " -p " + dbpassword
            cmd += ' --authenticationDatabase admin'
        cmd += ' --eval "printjson(db.adminCommand(\'listDatabases\'))"'
        output = pssh_exec_command(nodes, int(SSHPort), Username,
                                   Password, cmd)
        nodelist = nodes
    except AuthenticationException as ex:
        raise

    except Exception as ex:
        # error_msg = _("Failed to execute '%s' on host(s) '%s' with error: %s") %\
        #                 ('mongo printjson(db.adminCommand("listDatabases")) status', str(addlnodes), str(ex))
        error_msg = _(
            "Failed to authenticate on host %s with host username/password") % (str(addlnodes))

        LOG.info(error_msg)
        nodes = addlnodes.split(";")
        if '' in nodes:
            nodes.remove('')
        if defaultnode not in nodes:
            nodes.append(defaultnode)

        for host in nodes:
            try:
                LOG.info(_('Connecting to MongoDB node %s') % host)
                pssh_exec_command([host],
                                  int(SSHPort),
                                  Username,
                                  Password,
                                  'mongo --eval ' + '"printjson(db.adminCommand(\'listDatabases\'))"')
                LOG.info(_("Selected '" + host + "' for MongoDB mongo"))
                nodelist.append(host)
            except AuthenticationException as ex:
                #error_msg = _("Failed to execute '%s' on host '%s' with error: %s") % ('mongo printjson(db.adminCommand("listDatabases"))', host, str(ex))
                error_msg = _(
                    "Failed to authenticate on host %s with host username/password") % (host)
                raise exception.ErrorOccurred(reason=error_msg)
            except Exception as ex:
                #error_msg = _("Failed to execute '%s' on host '%s' with error: %s") % ('mongo printjson(db.adminCommand("listDatabases"))', host, str(ex))
                error_msg = _(
                    "Failed to authenticate on host %s with host username/password") % (host)
                LOG.info(error_msg)
                pass

    if len(nodelist) == 0:
        LOG.info(error_msg)
        raise Exception(error_msg)

    LOG.info(_("Seed nodes of the MongoDB cluster are '%s'") % str(nodelist))
    return nodelist


@autolog.log_method(Logger)
def pssh_exec_command(hosts, port, user, password, command, sudo=False):
    try:
        LOG.info(_("pssh_exec_command - hosts: %s") % (str(hosts)))
        timeout = settings.get_settings().get('mongodb_discovery_timeout', '120')
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
def get_databases(hosts, port, username, password, dbport, dbuser, dbpassword):
    cmd = 'mongo --quiet --port ' + dbport
    if dbuser is not '':
        cmd += " -u " + dbuser + " -p " + dbpassword
        cmd += ' --authenticationDatabase admin'
    cmd += ' --eval "JSON.stringify(db.adminCommand(\'listDatabases\'))"'
    output = pssh_exec_command(hosts, port, username, password, cmd)
    for host in output:
        if output[host]['exit_code']:
            LOG.warning(_(cmd +
                          "on %s cannot be executed. Error %s. Error Msg: %s") %
                        (host, str(output[host]['exit_code']),
                         output[host]['stdout']))
            continue

        clusterinfo = {}
        for line in output[host]['stdout']:
            clusterinfo = json.loads(line)

        if clusterinfo['ok']:
            return clusterinfo['databases']
    if not clusterinfo['ok'] and "not master" in clusterinfo['errmsg']:
        # We may have a secondary node. Find primary node and issue
        # the request

        # Need more info here
        conn = connect_server(host, dbport, dbuser, dbpassword, verbose=False)
        isMongos = isShardedCluster(conn)
        if isMongos:
            msg = _("Internal Error: 'not a master' error should \
                     not happen on sharded cluster")
            LOG.error(msg)
            raise exception.ErrorOccurred(msg)
        else:
            # Find the master for the replica set
            output = pssh_exec_command([host], port, username, password,
                                       'mongo --quiet --port ' + dbport +
                                       ' --eval "JSON.stringify(rs.status())"')
            rsstatus = json.loads(output[host]['stdout'][0])
            for replica in rsstatus['members']:
                if replica['stateStr'] == 'PRIMARY':
                    primary_host = replica['name'].split(":")[0]
                    primary_dbport = replica['name'].split(":")[1]
                    if primary_host != host:  # break the recursion
                        clusterinfo = get_databases([primary_host], port,
                                                    username, password, primary_dbport, dbuser, dbpassword)
                    else:
                        msg = _(
                            "Failed to execute 'mongo --eval' successfully. Error %s") % (clusterinfo['errmsg'])
                        LOG.error(msg)
                        raise exception.ErrorOccurred(msg)
                    break
    else:
        msg = _(
            "Failed to execute 'mongo --eval' successfully. Error %s") % (clusterinfo['errmsg'])
        LOG.error(msg)
        raise exception.ErrorOccurred(msg)


@autolog.log_method(Logger)
def main(argv):
    try:
        errfile = '/tmp/mongodbnodes_errors.txt'
        outfile = '/tmp/mongodbnodes_output.txt'
        addlnodes = None
        dbport = "27017"
        dbuser = ''
        dbpassword = ''
        port = "22"
        defaultnode = ''
        username = ''
        password = ''

        opts, args = getopt.getopt(argv, "", ["defaultnode=", "port=",
                                              "username=", "password=", "addlnodes=",
                                              "preferredgroups=", "findpartitiontype=",
                                              "outfile=", "errfile=", "dbport=", "dbuser=",
                                              "dbpassword=", ])
        for opt, arg in opts:
            if opt == '--defaultnode':
                defaultnode = arg
            elif opt == '--port':
                port = arg
            elif opt == '--dbport':
                dbport = arg
            elif opt == '--dbuser':
                dbuser = arg
            elif opt == '--dbpassword':
                dbpassword = arg
            elif opt == '--username':
                username = arg
            elif opt == '--password':
                password = arg
            elif opt == '--addlnodes':
                addlnodes = arg
            elif opt == '--outfile':
                outfile = arg
            elif opt == '--errfile':
                errfile = arg

        with open(outfile, 'w') as outfilehandle:
            pass

        alivenodes = find_alive_nodes(
            defaultnode, port, username, password, dbport, addlnodes)

        clusterinfo = {}
        clusterinfo['databases'] = get_databases(
            alivenodes, port, username, password, dbport, dbuser, dbpassword)

        with open(outfile, 'w') as outfilehandle:
            outfilehandle.write(json.dumps(clusterinfo))

    except getopt.GetoptError as ex:
        LOG.exception(ex)
        usage = _("Usage: mongodbnodes.py --config-file /etc/workloadmgr/workloadmgr.conf --defaultnode mongodb1 "
                  "--port 22 --username ubuntu --password password "
                  "--dbport <mongos/mongodport> "
                  "--dbuser <mongo admin> "
                  "--dbpassword <password> "
                  "--addlnodes 'mongodb1;mongodb2;mongodb3' "
                  "--outfile /tmp/mongodbnodes.txt --errfile /tmp/mongodbnodes_error.txt")
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
    LOG = logging.getLogger('workflows.mongodbnodes')
    Logger = autolog.Logger(LOG)
    main(sys.argv[3:])
