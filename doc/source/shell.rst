The :program:`workloadmanager` shell utility
=========================================

.. program:: workloadmanager
.. highlight:: bash

The :program:`workloadmanager` shell utility interacts with the workloadmanager API
from the command line. It supports the entirety of the workloadmanager API.

You'll need to provide :program:`workloadmanager` with your OpenStack username and
API key. You can do this with the :option:`--os-username`, :option:`--os-password`
and :option:`--os-tenant-name` options, but it's easier to just set them as
environment variables by setting two environment variables:

.. envvar:: OS_USERNAME or WORKLOADMANAGER_USERNAME

    Your OpenStack workloadmanager username.

.. envvar:: OS_PASSWORD or WORKLOADMANAGER_PASSWORD

    Your password.

.. envvar:: OS_TENANT_NAME or WORKLOADMANAGER_PROJECT_ID

    Project for work.

.. envvar:: OS_AUTH_URL or WORKLOADMANAGER_URL

    The API server URL.

.. envvar:: OS_WORKLOADMANAGER_API_VERSION

    The WORKLOADMANAGER API version.

For example, in Bash you'd use::

    export OS_USERNAME=yourname
    export OS_PASSWORD=yadayadayada
    export OS_TENANT_NAME=myproject
    export OS_AUTH_URL=http://...
    export OS_VOLUME_API_VERSION=1

From there, all shell commands take the form::

    workloadmanager <command> [arguments...]

Run :program:`workloadmanager help` to get a full list of all possible commands,
and run :program:`workloadmanager help <command>` to get detailed help for that
command.
