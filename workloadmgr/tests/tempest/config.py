# Copyright 2014 TrilioData Inc.

from oslo_config import cfg

service_available_group = cfg.OptGroup(name="service_available",
                                       title="Available OpenStack Services")


ServiceAvailableGroup = [
    cfg.BoolOpt("workloadmgr",
                default=True,
                help="Whether or not workloadmgr is expected to be available"),
]
