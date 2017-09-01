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

settings_file_dir = '/var/triliovault/settings/'
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
'smtp_timeout' : '10',
}

def get_settings(context=None, get_hidden=False):                           
    """get settings"""
    try:
        copy_settings = {}
        if context.is_admin is True:
           copy_settings = default_settings
        persisted_settings = {}
        persisted_setting_objs = db.setting_get_all(context, read_deleted = 'no',get_hidden = get_hidden)
        for persisted_setting in persisted_setting_objs:
            persisted_settings[persisted_setting.name] = persisted_setting.value
        for setting, value in copy_settings.iteritems():
            if setting not in persisted_settings:
                persisted_settings[setting] = value
        return persisted_settings
            
    except Exception as ex:
        LOG.exception(ex)
        return copy_settings

def set_settings(context, new_settings):                           
    """set settings"""
    from workloadmgr import workloads as workloadAPI
    @workloadAPI.api.upload_settings
    def upload_settings(name, context):
        pass
    try:
        persisted_setting_objs = db.setting_get_all(context)
        for name, value in new_settings.iteritems():
            name_found = False
            for persisted_setting in persisted_setting_objs:
                if persisted_setting.name == name:
                    db.setting_update(context, name, {'value' : value})
                    name_found = True
                    break
            if name_found == False:
                db.setting_create(context, {'name' : name, 
                                            'value' : value,
                                            'user_id': context.user_id,
                                            'project_id': context.project_id,                                             
                                            'status': 'available'})
        upload_settings(name, context)
        return get_settings() 
    except Exception as ex:
        LOG.exception(ex)
        return default_settings
