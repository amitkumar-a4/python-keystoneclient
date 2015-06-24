    # vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2015 TrilioData, Inc.
# All Rights Reserved.

"""Global Settings."""


import os
import ConfigParser
from workloadmgr.openstack.common import log as logging
from workloadmgr.db.workloadmgrdb import WorkloadMgrDB


LOG = logging.getLogger(__name__)
db = WorkloadMgrDB().db

settings_file_dir = '/opt/stack/data/wlm/settings/'
settings_file_name = 'workloadmgr-settings.conf'

default_settings = {
'cassandra_discovery_timeout' : '120',
'mongodb_discovery_timeout' : '120',
'smtp_email_enable' : 'no',
'smtp_server_name' : 'localhost',
'smtp_default_recipient' : 'administrator@tvault.com',
'smtp_default_sender' : 'administrator@tvault.com',
'smtp_port' : '587',
'smtp_server_username' : '',
'smtp_server_password' : '',
}

def get_settings(context=None):                           
    """get settings"""
    try:
        persisted_settings = {}
        persisted_setting_objs = db.setting_get_all(context)
        for persisted_setting in persisted_setting_objs:
            persisted_settings[persisted_setting.key] = persisted_setting.value
        for setting, value in default_settings.iteritems():
            if setting not in persisted_settings:
                persisted_settings[setting] = value
        return persisted_settings
            
    except Exception as ex:
        LOG.exception(ex)
        return default_settings

def set_settings(context, new_settings):                           
    """set settings"""
    try:
        persisted_setting_objs = db.setting_get_all(context)
        for key, value in new_settings.iteritems():
            key_found = False
            for persisted_setting in persisted_setting_objs:
                if persisted_setting.key == key:
                    db.setting_update(context, key, {'value' : value})
                    key_found = True
                    break
            if key_found == False:
                db.setting_create(context, {'key' : key, 
                                            'value' : value,
                                            'user_id': context.user_id,
                                            'project_id': context.project_id,                                             
                                            'status': 'available'})
        return get_settings() 
    except Exception as ex:
        LOG.exception(ex)
        return default_settings