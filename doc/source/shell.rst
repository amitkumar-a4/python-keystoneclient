The :program:`workloadmgr` shell utility
=========================================

.. program:: workloadmgr
.. highlight:: bash

The :program:`workloadmgr` shell utility interacts with the OpenStack WorkloadMgr API
from the command line. It supports the entirety of the OpenStack WorkloadMgr API.

You'll need to provide :program:`workloadmgr` with your OpenStack username and
API key. You can do this with the :option:`--os-username`, :option:`--os-password`
and :option:`--os-tenant-name` options, but it's easier to just set them as
environment variables by setting two environment variables:

.. envvar:: OS_USERNAME or WORKLOADMGR_USERNAME

    Your OpenStack WorkloadMgr username.

.. envvar:: OS_PASSWORD or WORKLOADMGR_PASSWORD

    Your password.

.. envvar:: OS_TENANT_NAME or WORKLOADMGR_PROJECT_ID

    Project for work.

.. envvar:: OS_AUTH_URL or WORKLOADMGR_URL

    The OpenStack API server URL.

.. envvar:: OS_DPAAS_API_VERSION

    The OpenStack DPAAS API version.

For example, in Bash you'd use::

    export OS_USERNAME=yourname
    export OS_PASSWORD=yadayadayada
    export OS_TENANT_NAME=myproject
    export OS_AUTH_URL=http://...
    export OS_VOLUME_API_VERSION=1

From there, all shell commands take the form::

    workloadmgr <command> [arguments...]

Run :program:`workloadmgr help` to get a full list of all possible commands,
and run :program:`workloadmgr help <command>` to get detailed help for that
command.
