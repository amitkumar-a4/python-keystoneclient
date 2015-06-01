    # vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""Global Settings."""


import os
import ConfigParser
from workloadmgr.openstack.common import log as logging


LOG = logging.getLogger(__name__)

settings_file_dir = '/opt/stack/data/wlm/settings/'
settings_file_name = 'workloadmgr-settings.conf'

default_settings = {
'cassandra_discovery_timeout' : '120',
'mongodb_discovery_timeout' : '120',
'smtp_email_enable' : 'no',
'smtp_server_name' : 'localhost',
'smtp_default_sender' : 'administrator@tvault.com',
'smtp_default_to' : 'administrator@tvault.com',
}

def get_settings():                           
    """get settings"""
    try:
        Config = ConfigParser.RawConfigParser()
        Config.read(settings_file_dir + settings_file_name)
        persisted_settings = dict(Config._defaults)
        for setting, value in default_settings.iteritems():
            if setting not in persisted_settings:
                persisted_settings[setting] = value
        return persisted_settings
    except Exception as ex:
        LOG.exception(ex)
        return default_settings

def set_settings(new_settings):                           
    """set settings"""
    try:
        Config = ConfigParser.RawConfigParser()
        Config.read(settings_file_dir + settings_file_name)
        for key, value in new_settings.iteritems():
            Config.set(None, key, value)
        if not os.path.exists(settings_file_dir):
            os.makedirs(settings_file_dir)                      
        with open(settings_file_dir + settings_file_name, 'wb') as configfile:
            Config.write(configfile)                
        return get_settings()
    except Exception as ex:
        LOG.exception(ex)
        return default_settings