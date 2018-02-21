# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

from __future__ import print_function, unicode_literals

import logging
import signal
import socket

from optparse import OptionParser, OptionGroup, SUPPRESS_HELP
from os import environ, walk, _exit as os_exit
from os.path import isfile, isdir, join
from six import text_type
from sys import argv as sys_argv, exit, stderr
from time import gmtime, strftime

from swiftclient import RequestException
from swiftclient.utils import config_true_value, generate_temp_url, prt_bytes
from swiftclient.multithreading import OutputManager
from swiftclient.exceptions import ClientException
from swiftclient import __version__ as client_version
from swiftclient.service import SwiftService, SwiftError, \
    SwiftUploadObject, get_conn
from swiftclient.command_helpers import print_account_stats, \
    print_container_stats, print_object_stats

try:
    from shlex import quote as sh_quote
except ImportError:
    from pipes import quote as sh_quote

BASENAME = 'swift'
commands = ('delete', 'download', 'list', 'post', 'stat', 'upload',
            'capabilities', 'info', 'tempurl', 'auth')


"""
{'verbose': 1, 'os_username': 'demo', 'os_user_domain_name': None, 'os_cacert': None, 'os_tenant_name': 'demo', 'os_user_domain_id': None, 'prefix': None, 'auth_version': u'2.0', 'ssl_compression': True, 'os_password': 'project1', 'os_user_id': None, 'os_project_id': None, 'long': False, 'totals': False, 'snet': False, 'os_tenant_id': None, 'os_project_name': None, 'os_service_type': None, 'insecure': False, 'os_help': None, 'os_project_domain_id': None, 'os_storage_url': None, 'human': False, 'auth': 'http://192.168.1.138:5000/v2.0', 'os_auth_url': 'http://192.168.1.138:5000/v2.0', 'user': 'demo', 'key': 'project1', 'os_region_name': 'RegionOne', 'info': False, 'retries': 5, 'os_auth_token': None, 'delimiter': None, 'os_options': {u'project_name': None, u'region_name': 'RegionOne', u'tenant_name': 'demo', u'user_domain_name': None, u'endpoint_type': None, u'object_storage_url': None, u'project_domain_id': None, u'user_id': None, u'user_domain_id': None, u'tenant_id': None, u'service_type': None, u'project_id': None, u'auth_token': None, u'project_domain_name': None}, 'debug': False, 'os_project_domain_name': None, 'os_endpoint_type': None}
"""

swift_list = None
swift_stat = None
swift_upload = None
swift_download = None
swift_delete = None
swift_post = None
swift_cap = None


def immediate_exit(signum, frame):
    stderr.write(" Aborted\n")
    os_exit(2)


def st_delete(args, options):
    _opts = dict(options)
    global swift_delete
    if swift_delete is None:
        swift_delete = SwiftService(options=_opts)

    try:
        if not args:
            del_iter = swift_delete.delete(options=_opts)
        else:
            container = args[0]
            if '/' in container:
                raise Exception(
                    'WARNING: / in container name; you '
                    "might have meant '%s' instead of '%s'." %
                    (container.replace('/', ' ', 1), container)
                )
                return
            objects = args[1:]
            if objects:
                del_iter = swift_delete.delete(container=container,
                                               objects=objects, options=_opts)
            else:
                del_iter = swift_delete.delete(
                    container=container, options=_opts)

        for r in del_iter:
            c = r.get('container', '')
            o = r.get('object', '')
            a = r.get('attempts')

        if r['success']:
            if options.verbose:
                a = ' [after {0} attempts]'.format(a) if a > 1 else ''

                if r['action'] == 'delete_object':
                    if options.yes_all:
                        p = '{0}/{1}'.format(c, o)
                    else:
                        p = o
                elif r['action'] == 'delete_segment':
                    p = '{0}/{1}'.format(c, o)
                elif r['action'] == 'delete_container':
                    p = c

                print('{0}{1}'.format(p, a))
        else:
            p = '{0}/{1}'.format(c, o) if o else c
            raise Exception('Error Deleting: {0}: {1}'
                            .format(p, r['error']))
    except SwiftError as err:
        raise Exception(err.value)


def st_download(args, options):
    global swift_download
    if options.out_file == '-':
        options.verbose = 0

    if options.out_file and len(args) != 2:
        raise Exception('-o option only allowed for single file downloads')

    if not options.prefix:
        options.remove_prefix = False

    if options.out_directory and len(args) == 2:
        raise Exception(
            'Please use -o option for single file downloads and renames')

    if (not args and not options.yes_all) or (args and options.yes_all):
        raise Exception('Usage: %s download %s\n%s', BASENAME,
                        st_download_options, st_download_help)
        return

    _opts = dict(options).copy()
    if swift_download is None:
        swift_download = SwiftService(options=_opts)
    try:
        if not args:
            down_iter = swift_download.download(options=_opts)
        else:
            container = args[0]
            if '/' in container:
                raise Exception(
                    'WARNING: / in container name; you '
                    "might have meant '%s' instead of '%s'." %
                    (container.replace('/', ' ', 1), container)
                )
                return
            objects = args[1:]
            if not objects:
                down_iter = swift_download.download(container, options=_opts)
            else:
                down_iter = swift_download.download(
                    container, objects, options=_opts)

        for down in down_iter:
            if options.out_file == '-' and 'contents' in down:
                contents = down['contents']
                for chunk in contents:
                    print(chunk)
            else:
                if down['success']:
                    if options.verbose:
                        start_time = down['start_time']
                        headers_receipt = \
                            down['headers_receipt'] - start_time
                        auth_time = down['auth_end_time'] - start_time
                        finish_time = down['finish_time']
                        read_length = down['read_length']
                        attempts = down['attempts']
                        total_time = finish_time - start_time
                        down_time = total_time - auth_time
                        _mega = 1000000
                        if down['pseudodir']:
                            time_str = (
                                'auth %.3fs, headers %.3fs, total %.3fs, '
                                'pseudo' % (
                                    auth_time, headers_receipt,
                                    total_time
                                )
                            )
                        else:
                            speed = float(read_length) / down_time / _mega
                            time_str = (
                                'auth %.3fs, headers %.3fs, total %.3fs, '
                                '%.3f MB/s' % (
                                    auth_time, headers_receipt,
                                    total_time, speed
                                )
                            )
                        path = down['path']
                        if attempts > 1:
                            print('%s [%s after %d attempts]' % (
                                path, time_str, attempts))
                        else:
                            print('%s [%s]' % (path, time_str))
                else:
                    error = down['error']
                    path = down['path']
                    container = down['container']
                    obj = down['object']
                    if isinstance(error, ClientException):
                        if error.http_status == 304 and \
                                options.skip_identical:
                            print("Skipped identical file '%s'" % path)
                            continue
                        if error.http_status == 404:
                            raise Exception(
                                "Object '%s/%s' not found", container, obj)
                            continue
                    raise Exception(
                        "Error downloading object '%s/%s': %s",
                        container, obj, error)

    except SwiftError as e:
        raise
    except Exception as e:
        raise


def st_list(args, options):
    global swift_list

    def _print_stats(options, stats):
        total_count = total_bytes = 0
        container = stats.get("container", None)
        for item in stats["listing"]:
            item_name = item.get('name')
            if not options.long and not options.human:
                print(item.get('name', item.get('subdir')))
            else:
                if not container:    # listing containers
                    item_bytes = item.get('bytes')
                    byte_str = prt_bytes(item_bytes, options.human)
                    count = item.get('count')
                    total_count += count
                    try:
                        meta = item.get('meta')
                        utc = gmtime(float(meta.get('x-timestamp')))
                        datestamp = strftime('%Y-%m-%d %H:%M:%S', utc)
                    except TypeError:
                        datestamp = '????-??-?? ??:??:??'
                    if not options.totals:
                        print(
                            "%5s %s %s %s" % (count, byte_str,
                                              datestamp, item_name))
                else:    # list container contents
                    subdir = item.get('subdir')
                    content_type = item.get('content_type')
                    if subdir is None:
                        item_bytes = item.get('bytes')
                        byte_str = prt_bytes(item_bytes, options.human)
                        date, xtime = item.get('last_modified').split('T')
                        xtime = xtime.split('.')[0]
                    else:
                        item_bytes = 0
                        byte_str = prt_bytes(item_bytes, options.human)
                        date = xtime = ''
                        item_name = subdir
                    if not options.totals:
                        print(
                            "%s %10s %8s %24s %s" %
                            (byte_str, date, xtime, content_type, item_name))
                total_bytes += item_bytes

        # report totals
        if options.long or options.human:
            if not container:
                print(
                    "%5s %s" % (prt_bytes(total_count, True),
                                prt_bytes(total_bytes, options.human)))
            else:
                print(
                    prt_bytes(total_bytes, options.human))

    if options.delimiter and not args:
        raise Exception('-d option only allowed for container listings')

    _opts = dict(options).copy()
    if _opts['human']:
        _opts.pop('human')
        _opts['long'] = True

    if options.totals and not options.long and not options.human:
        raise Exception(
            "Listing totals only works with -l or --lh.")
        return

    if swift_list is None:
        swift_list = SwiftService(options=_opts)
    try:
        if not args:
            stats_parts_gen = swift_list.list(options=_opts)
        else:
            container = args[0]
            args = args[1:]
            if "/" in container or args:
                raise Exception('Usage error')
                return
            else:
                stats_parts_gen = swift_list.list(
                    container=container, options=_opts)

        for stats in stats_parts_gen:
            if stats["success"]:
                return [item.get('name') for item in stats["listing"]]
            else:
                raise stats["error"]
        return []

    except SwiftError as e:
        raise


def st_stat(args, options):
    global swift_stat
    _opts = dict(options).copy()

    if swift_stat is None:
        swift_stat = SwiftService(options=_opts)

    try:
        if not args:
            stat_result = swift_stat.stat(options=_opts)
            if not stat_result['success']:
                raise stat_result['error']
            return stat_result
        else:
            container = args[0]
            if '/' in container:
                raise Exception(
                    'WARNING: / in container name; you might have '
                    "meant '%s' instead of '%s'." %
                    (container.replace('/', ' ', 1), container))
                return
            args = args[1:]
            if not args:
                stat_result = swift_stat.stat(
                    container=container, options=_opts)
                if not stat_result['success']:
                    raise stat_result['error']
                return stat_result
            else:
                if len(args) == 1:
                    objects = [args[0]]
                    stat_results = swift_stat.stat(
                        container=container, objects=objects, options=_opts)
                    for stat_result in stat_results:  # only 1 result
                        if stat_result["success"]:
                            return stat_result
                        else:
                            raise stat_result
                else:
                    raise Exception(
                        'Usage: %s stat %s\n%s', BASENAME,
                        st_stat_options, st_stat_help)

    except SwiftError as e:
        raise


def st_post(args, options):
    global swift_post
    if (options.read_acl or options.write_acl or options.sync_to or
            options.sync_key) and not args:
        raise Exception(
            '-r, -w, -t, and -k options only allowed for containers')

    _opts = dict(options).copy()

    if swift_post is None:
        swift_post = SwiftService(options=_opts)

    try:
        if not args:
            result = swift_post.post(options=_opts)
        else:
            container = args[0]
            if '/' in container:
                raise Exception(
                    'WARNING: / in container name; you might have '
                    "meant '%s' instead of '%s'." %
                    (args[0].replace('/', ' ', 1), args[0]))
                return
            args = args[1:]
            if args:
                if len(args) == 1:
                    objects = [args[0]]
                    results_iterator = swift_post.post(
                        container=container, objects=objects, options=_opts
                    )
                    result = next(results_iterator)
                else:
                    raise Exception(
                        'Usage: %s post %s\n%s', BASENAME,
                        st_post_options, st_post_help)
                    return
            else:
                result = swift_post.post(container=container, options=_opts)
        if not result["success"]:
            raise result

    except SwiftError as e:
        raise


def st_upload(args, options):
    global swift_upload

    container = args[0]
    files = args[1:]
    if options.object_name is not None:
        if len(files) > 1:
            raise Exception('object-name only be used with 1 file or dir')
            return
        else:
            orig_path = files[0]
    if options.segment_size:
        try:
            # If segment size only has digits assume it is bytes
            int(options.segment_size)
        except ValueError:
            try:
                size_mod = "BKMG".index(options.segment_size[-1].upper())
                multiplier = int(options.segment_size[:-1])
            except ValueError:
                raise Exception("Invalid segment size")
                return

            options.segment_size = str((1024 ** size_mod) * multiplier)
        if int(options.segment_size) <= 0:
            raise Exception("segment-size should be positive")
            return
    _opts = dict(options).copy()
    if swift_upload is None:
        swift_upload = SwiftService(options=_opts)

    try:
        objs = []
        dir_markers = []
        for f in files:
            if isfile(f):
                objs.append(f)
            elif isdir(f):
                for (_dir, _ds, _fs) in walk(f):
                    if not (_ds + _fs):
                        dir_markers.append(_dir)
                    else:
                        objs.extend([join(_dir, _f) for _f in _fs])
            else:
                raise Exception("Local file '%s' not found" % f)

        # Now that we've collected all the required files and dir markers
        # build the tuples for the call to upload
        if options.object_name is not None:
            objs = [
                SwiftUploadObject(
                    o, object_name=o.replace(
                        orig_path, options.object_name, 1
                    )
                ) for o in objs
            ]
            dir_markers = [
                SwiftUploadObject(
                    None, object_name=d.replace(
                        orig_path, options.object_name, 1
                    ), options={'dir_marker': True}
                ) for d in dir_markers
            ]

        for r in swift_upload.upload(
                container, objs + dir_markers, options=_opts):
            if r['success']:
                if options.verbose:
                    if 'attempts' in r and r['attempts'] > 1:
                        if 'object' in r:
                            print(
                                '%s [after %d attempts]' %
                                (r['object'],
                                 r['attempts'])
                            )
                        else:
                            if 'object' in r:
                                print (r['object'])
                            elif 'for_object' in r:
                                print(
                                    '%s segment %s' % (r['for_object'],
                                                       r['segment_index'])
                                )
                else:
                    error = r['error']
                    if 'action' in r and r['action'] == "create_container":
                            # it is not an error to be unable to create the
                            # container so print a warning and carry on
                        if isinstance(error, ClientException):
                            if (r['headers'] and
                                    'X-Storage-Policy' in r['headers']):
                                msg = ' with Storage Policy %s' % \
                                      r['headers']['X-Storage-Policy'].strip()
                            else:
                                msg = ' '.join(str(x) for x in (
                                    error.http_status, error.http_reason)
                                )
                                if error.http_response_content:
                                    if msg:
                                        msg += ': '
                                    msg += error.http_response_content[:60]
                                msg = ': %s' % msg
                        else:
                            msg = ': %s' % error
                        raise Exception(
                            'Warning: failed to create container '
                            "'%s'%s", container, msg
                        )
                    else:
                        raise Exception("%s" % error)
                        too_large = (isinstance(error, ClientException) and
                                     error.http_status == 413)
                        if too_large and options.verbose > 0:
                            raise Exception(
                                "Consider using the --segment-size option "
                                "to chunk the object")

    except SwiftError as e:
        raise


def st_capabilities(args, options):
    global swift_cap

    def _print_compo_cap(name, capabilities):
        for feature, options in sorted(capabilities.items(),
                                       key=lambda x: x[0]):
            print("%s: %s" % (name, feature))
            if options:
                print(" Options:")
                for key, value in sorted(options.items(),
                                         key=lambda x: x[0]):
                    print("  %s: %s" % (key, value))

    if args and len(args) > 2:
        raise Exception('Usage: %s capabilities %s\n%s',
                        BASENAME,
                        st_capabilities_options, st_capabilities_help)
        return

    _opts = dict(options).copy()
    if swift_cap is None:
        swift_cap = SwiftService(options=_opts)

    try:
        if len(args) == 2:
            url = args[1]
            capabilities_result = swift_cap.capabilities(url)
            capabilities = capabilities_result['capabilities']
        else:
            capabilities_result = swift_cap.capabilities()
            capabilities = capabilities_result['capabilities']

        _print_compo_cap('Core', {'swift': capabilities['swift']})
        del capabilities['swift']
        _print_compo_cap('Additional middleware', capabilities)
    except SwiftError as e:
        raise


def st_auth(args, options):
    _opts = vars(options)
    if options.verbose > 1:
        if options.auth_version in ('1', '1.0'):
            print('export ST_AUTH=%s' % sh_quote(options.auth))
            print('export ST_USER=%s' % sh_quote(options.user))
            print('export ST_KEY=%s' % sh_quote(options.key))
        else:
            print('export OS_IDENTITY_API_VERSION=%s' % sh_quote(
                options.auth_version))
            print('export OS_AUTH_VERSION=%s' % sh_quote(options.auth_version))
            print('export OS_AUTH_URL=%s' % sh_quote(options.auth))
            for k, v in sorted(_opts.items()):
                if v and k.startswith('os_') and \
                        k not in ('os_auth_url', 'os_options'):
                    print('export %s=%s' % (k.upper(), sh_quote(v)))
    else:
        conn = get_conn(_opts)
        url, token = conn.get_auth()
        print('export OS_STORAGE_URL=%s' % sh_quote(url))
        print('export OS_AUTH_TOKEN=%s' % sh_quote(token))


def st_tempurl(args, options):
    args = args[1:]
    if len(args) < 4:
        raise Exception('Usage: %s tempurl %s\n%s', BASENAME,
                        st_tempurl_options, st_tempurl_help)
        return
    method, seconds, path, key = args[:4]
    try:
        seconds = int(seconds)
    except ValueError:
        raise Exception('Seconds must be an integer')
        return
    if method.upper() not in ['GET', 'PUT', 'HEAD', 'POST', 'DELETE']:
        print ('WARNING: Non default HTTP method %s for '
               'tempurl specified, possibly an error' %
               method.upper())
    url = generate_temp_url(path, seconds, key, method,
                            absolute=options.absolute_expiry)
    print(url)
