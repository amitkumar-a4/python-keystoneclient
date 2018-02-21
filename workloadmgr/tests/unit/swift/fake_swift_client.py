# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import httplib
import json
import os
import socket

from cinder.openstack.common import log as logging
from swiftclient import client as swift

LOG = logging.getLogger(__name__)


class FakeSwiftClient(object):
    """Logs calls instead of executing."""

    def __init__(self, *args, **kwargs):
        self.conn = self.Connection()
        pass

    @classmethod
    def Connection(self, *args, **kargs):
        LOG.debug("fake FakeSwiftClient Connection")
        return FakeSwiftConnection()

    def put_object(self, container, url, json_data):
        pass


class FakeSwiftConnection(object):
    """Logging calls instead of executing"""

    def __init__(self, *args, **kwargs):
        pass

    def head_container(self, container):
        LOG.debug("fake head_container(%s)" % container)
        if container == 'missing_container':
            raise swift.ClientException('fake exception',
                                        http_status=httplib.NOT_FOUND)
        elif container == 'unauthorized_container':
            raise swift.ClientException('fake exception',
                                        http_status=httplib.UNAUTHORIZED)
        elif container == 'socket_error_on_head':
            raise socket.error(111, 'ECONNREFUSED')
        pass

    def put_container(self, container):
        LOG.debug("fake put_container(%s)" % container)
        pass

    def get_account(self):
        LOG.debug("fake get_account")
        workloads = [[{"header": "fake"}], []]
        for dirname, dirnames, filenames in os.walk('.'):
            for subdirname in dirnames:
                if subdirname.startswith("workload_"):
                    workloads[1].append(
                        {"count": 15, "bytes": 103079319237, "name": subdirname})
        return workloads[0], workloads[1]

    def get_container(self, container, **kwargs):
        LOG.debug("fake get_container(%s)" % container)
        contents = [[{"header": "fake"}], []]
        root = os.path.join("workloadmgr/tests/swift", container)
        for dirname, dirnames, filenames in os.walk(root):
            # print path to all subdirectories first.
            for filename in filenames:
                if dirname.startswith(root):
                    contents[1].append({"count": 15, "bytes": 103079319237, "name": os.path.join(
                        dirname, filename).replace("workloadmgr/tests/swift/", "")})
        return contents[0], contents[1]

    def head_object(self, container, name):
        LOG.debug("fake put_container(%s, %s)" % (container, name))
        return {'etag': 'fake-md5-sum'}

    def get_object(self, container, name):
        LOG.debug("fake get_object(%s, %s)" % (container, name))
        if container == 'socket_error_on_get':
            raise socket.error(111, 'ECONNREFUSED')
        # read the file from container/name file system
        root = os.path.join("workloadmgr/tests/swift", container)
        with open(os.path.join("workloadmgr/tests/swift", name), 'r') as f:
            read_data = f.read()
        return ({"header": "fake"}, read_data)

    def put_object(self, container, name, reader, content_length=None,
                   etag=None, chunk_size=None, content_type=None,
                   headers=None, query_string=None):
        LOG.debug("fake put_object(%s, %s)" % (container, name))
        if container == 'socket_error_on_put':
            raise socket.error(111, 'ECONNREFUSED')
        # put the file into container/name file system and return md5
        return 'fake-md5-sum'

    def delete_object(self, container, name):
        LOG.debug("fake delete_object(%s, %s)" % (container, name))
        if container == 'socket_error_on_delete':
            raise socket.error(111, 'ECONNREFUSED')
        pass
