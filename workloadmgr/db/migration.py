# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Database setup and migration commands."""

from workloadmgr import utils


IMPL = utils.LazyPluggable('db_backend',
                           sqlalchemy='workloadmgr.db.sqlalchemy.migration')


INIT_VERSION = 000


def db_sync(version=None):
    """Migrate the database to `version` or the most recent version."""
    return IMPL.db_sync(version=version)


def db_version():
    """Display the current database version."""
    return IMPL.db_version()
