# Copyright 2015 TrilioData Inc.
# All Rights Reserved.

import os
import threading
import time
from datetime import datetime
from datetime import timedelta
from workloadmgr.openstack.common import timeutils
from workloadmgr.openstack.common import fileutils
from oslo.config import cfg
from keystoneclient.v2_0 import client as keystone_v2
 
auditlog_opts = [
    cfg.StrOpt('auditlog_admin_user',
               default='admin',
               help='auditlog admin user'),
    cfg.StrOpt('keystone_endpoint_url',
               default='http://localhost:35357/v2.0',
               help='keystone endpoint url for connecting to keystone'),                                   
]

CONF = cfg.CONF
CONF.register_opts(auditlog_opts) 

_auditloggers = {}
lock = threading.Lock()

def getAuditLogger(name='auditlog', version='unknown', filepath='/opt/stack/data/wlm/auditlogs/auditlog.log'):
    if name not in _auditloggers:
        _auditloggers[name] = AuditLog(name, version, filepath)
    
    return _auditloggers[name]


class AuditLog(object):
    def __init__(self, name, version, filepath, *args, **kwargs):
        self._name = name
        self._version = version
        self._filepath = filepath
        head, tail = os.path.split(filepath)
        fileutils.ensure_tree(head)

    def log(self, context, message, object=None, *args, **kwargs):
        try:
            lock.acquire()
           
            if message == None:
                message = 'NA'
            if object == None:
                object = {}
            
            keystone = keystone_v2.Client(token=context.auth_token, endpoint=CONF.keystone_endpoint_url)
            user = keystone.users.get(context.user_id)
            
            auditlogmsg = timeutils.utcnow().strftime("%d-%m-%Y %H:%M:%S.%f")
            auditlogmsg = auditlogmsg + ',' + user.name + ',' + context.user_id
            display_name = object.get('display_name', 'NA')
            if not display_name:
                display_name = object.get('id', 'NA')
            auditlogmsg = auditlogmsg + ',' +  display_name + ',' + object.get('id', 'NA')  
            auditlogmsg = auditlogmsg + ',' + message + '\n'

            head, tail = os.path.split(self._filepath)
            fileutils.ensure_tree(head)
            with open(self._filepath, 'a') as auditlogfile:   
                auditlogfile.write(auditlogmsg, *args, **kwargs)
        finally:
            lock.release()
            
    def get_records(self, time_in_minutes, time_from, time_to):
        records = []
        head, tail = os.path.split(self._filepath)
        fileutils.ensure_tree(head)        
        
        if time_in_minutes:
            now = timeutils.utcnow()
            with open(self._filepath) as auditlogfile: 
                for line in auditlogfile:
                    values = line.split(",") 
                    record_time = datetime.strptime(values[0], "%d-%m-%Y %H:%M:%S.%f") 
                    if (now - record_time) < timedelta(minutes=time_in_minutes):
                        record = {'Timestamp' : values[0],
                                  'UserName': values[1],
                                  'UserId': values[2],
                                  'ObjectName': values[3],
                                  'ObjectId': values[4],
                                  'Details':values[5],
                                  }
                        records.append(record)
        else:
            with open(self._filepath) as auditlogfile: 
                for line in auditlogfile:
                    values = line.split(",")
                    record_time = datetime.strptime(values[0], "%d-%m-%Y %H:%M:%S.%f") 
                    if record_time >= time_from and record_time <= time_to:
                        record = {'Timestamp' : values[0],
                                  'UserName': values[1],
                                  'UserId': values[2],
                                  'ObjectName': values[3],
                                  'ObjectId': values[4],
                                  'Details':values[5],
                                  }
                        records.append(record)           
        return records
